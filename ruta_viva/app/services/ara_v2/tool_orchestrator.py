from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ara_session import AraSession
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara_comprehension import ComprehensionResult, QuickReplySuggestion, ToolExecutionResult
from app.schemas.itinerary import GenerateItineraryRequest
from app.services.embedding_service import get_embedding_service
from app.services.itinerary_generation_service import (
    build_schedule_guidance,
    validate_generated_itinerary_rules,
)
from app.services.llm_service import get_itinerary_generator
from app.services.poi_search_service import search_candidate_pois
from app.services.weather_service import get_forecast as get_weather_forecast

logger = logging.getLogger(__name__)

poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


class ToolOrchestrator:
    """Ejecuta herramientas segun ComprehensionResult. No llama a LLM, solo decide y ejecuta."""

    async def execute(
        self,
        comprehension: ComprehensionResult,
        session: AraSession,
        user: User,
        db: AsyncSession,
        current_user_message: str | None = None,
    ) -> ToolExecutionResult:
        tools = list(comprehension.herramientas_necesarias)
        result = ToolExecutionResult(status="respond")
        current_user_message = current_user_message or ""

        if self._looks_like_poi_question(current_user_message, comprehension):
            tools = [tool for tool in tools if tool != "search_pois"]
            if "answer_question" not in tools:
                tools.append("answer_question")

        selected_poi = await self._resolve_poi_reference(db, session, current_user_message, comprehension)
        if selected_poi is not None and self._looks_like_poi_selection(current_user_message):
            self._remember_selected_poi(session, selected_poi)
            result.response_text = (
                f"Perfecto, deje seleccionado {selected_poi.name} para considerarlo en tu viaje. "
                "Puedes seguir eligiendo lugares o pedirme que arme el itinerario."
            )
            result.status = "respond"
            result.candidate_pois = []
            result.quick_replies = [
                QuickReplySuggestion(label="Buscar mas lugares", value="buscar_mas", type="action"),
                QuickReplySuggestion(label="Armar itinerario", value="generar_itinerario", type="generate"),
                QuickReplySuggestion(label="Donde comer cerca?", value="gastronomia_cerca", type="action"),
            ]
            return result

        # 1. Herramientas independientes en paralelo
        tasks: list[asyncio.Task] = []
        if "search_pois" in tools:
            tasks.append(asyncio.create_task(self._search_pois(db, user, comprehension, session, current_user_message)))
        if "get_weather" in tools and session.start_date and session.lat is not None:
            tasks.append(asyncio.create_task(self._get_weather(session)))

        if tasks:
            parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in parallel_results:
                if isinstance(res, Exception):
                    logger.error("Tool failed: %s", res)
                    continue
                if res.get("type") == "pois":
                    result.candidate_pois = res["pois"]
                    result.status = "search"
                if res.get("type") == "weather":
                    result.weather_forecast = res["forecast"]

        # 2. Herramientas dependientes en secuencia
        if "build_itinerary" in tools:
            if not result.candidate_pois:
                search_res = await self._search_pois(db, user, comprehension, session, current_user_message)
                result.candidate_pois = search_res.get("pois", [])

            try:
                itinerary = await self._build_itinerary(
                    db, user, comprehension, session, result.candidate_pois or [], result.weather_forecast
                )
                result.itinerary = itinerary
                result.status = "generate"
            except Exception as exc:
                logger.exception("Build itinerary failed")
                result.status = "error"
                result.error = str(exc)
            return result

        if "suggest_replacement" in tools:
            try:
                replacement = await self._suggest_replacement(db, user, comprehension, session)
                result.candidate_pois = replacement.get("alternatives", [])
                result.status = "replace"
            except Exception as exc:
                logger.exception("Suggest replacement failed")
                result.status = "error"
                result.error = str(exc)
            return result

        if "answer_question" in tools:
            from app.services.ara_v2.answer_service import get_answer_service
            try:
                answer = await get_answer_service().answer(
                    db,
                    comprehension,
                    session,
                    current_user_message=current_user_message,
                )
                result.response_text = answer["text"]
                result.status = "respond"
            except Exception as exc:
                logger.exception("Answer question failed")
                result.status = "error"
                result.error = str(exc)
            return result

        # 3. Clarificacion si hay preguntas pendientes
        if comprehension.preguntas_pendientes:
            result.response_text = self._build_clarification_text(comprehension)
            result.quick_replies = comprehension.sugerir_quick_replies
            result.status = "clarify"
            return result

        # 4. Default
        result.response_text = "Entendido. En que mas puedo ayudarte?"
        return result

    async def _search_pois(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
        current_user_message: str | None = None,
    ) -> dict[str, Any]:
        destinos = [e.valor for e in comprehension.entidades if e.tipo == "destino"]
        destino = destinos[0] if destinos else None
        preferencias = [e.valor for e in comprehension.entidades if e.tipo == "preferencia"]
        categorias = [e.valor for e in comprehension.entidades if e.tipo == "categoria"]
        message = current_user_message or ""

        lat = session.lat
        lon = session.lon
        radius = session.radius or 8000

        query_parts = [destino] if destino else []
        query_parts.extend(preferencias)
        query_parts.extend(categorias)
        specific_query = self._specific_search_query(message, session)
        search_query = specific_query or " ".join(query_parts) or message or session.initial_query

        try:
            pois = await search_candidate_pois(
                db, poi_repository, search_query, user,
                None, lat=lat, lon=lon, radius=radius,
            )
            pois = self._filter_repeated_pois(session, pois)

            # Filter by category if specified
            if categorias:
                filtered = self._filter_pois_by_category(pois, categorias)
                if filtered:
                    pois = filtered

            session.candidate_poi_ids = [poi.id for poi in pois]
            self._remember_shown_pois(session, [poi.id for poi in pois])
            return {"type": "pois", "pois": [self._serialize_poi(poi) for poi in pois], "count": len(pois)}
        except Exception as exc:
            logger.warning("search_pois failed: %s", exc)
            return {"type": "pois", "pois": [], "count": 0}

    @staticmethod
    def _filter_pois_by_category(pois: list, categorias: list[str]) -> list:
        """Filter POIs by category names (case-insensitive partial match)."""
        if not categorias:
            return pois

        category_map = {
            "gastronomía": {"gastronomía", "gastronomia", "restaurante", "comida", "café", "cafe"},
            "alojamiento": {"alojamiento", "hotel", "hostal", "hostel", "cabaña", "cabana", "camping"},
            "naturaleza": {"naturaleza", "senderismo", "trekking", "parque", "reserva"},
            "termas": {"termas", "terma", "thermal", "spa", "bienestar"},
            "aventura": {"aventura", "deportes", "ski", "kayak", "rafting"},
            "cultura": {"cultura", "museo", "patrimonio", "histórico"},
        }

        matched_keywords = set()
        for cat in categorias:
            cat_lower = cat.lower()
            for key, keywords in category_map.items():
                if cat_lower in keywords or key.startswith(cat_lower[:5]):
                    matched_keywords.update(keywords)

        if not matched_keywords:
            return pois

        filtered = []
        for poi in pois:
            poi_text = ""
            if hasattr(poi, "name"):
                poi_text += f" {poi.name}"
            if hasattr(poi, "description") and poi.description:
                poi_text += f" {poi.description}"
            if hasattr(poi, "category_ids"):
                poi_text += f" {poi.category_ids}"
            poi_text = poi_text.lower()

            if any(kw in poi_text for kw in matched_keywords):
                filtered.append(poi)

        return filtered if filtered else pois

    @staticmethod
    def _serialize_poi(poi: Any) -> dict[str, Any]:
        if isinstance(poi, dict):
            return poi

        media = getattr(poi, "multimedia_urls", None)
        image_url = None
        if isinstance(media, dict):
            image_url = media.get("cover") or media.get("image") or media.get("image_url")

        return {
            "id": str(getattr(poi, "id", "")),
            "name": getattr(poi, "name", ""),
            "description": getattr(poi, "description", None),
            "category_ids": list(getattr(poi, "category_ids", []) or []),
            "latitude": getattr(poi, "latitude", None),
            "longitude": getattr(poi, "longitude", None),
            "image_url": image_url,
            "distance_meters": getattr(poi, "distance_meters", None),
            "poi_role": getattr(poi, "poi_role", None),
            "action_value": f"Seleccionar POI {getattr(poi, 'id', '')}",
        }

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_accents.lower()).strip()

    @classmethod
    def _looks_like_poi_question(cls, message: str, comprehension: ComprehensionResult) -> bool:
        normalized = cls._normalize_text(message)
        if any(entity.tipo == "poi" for entity in comprehension.entidades):
            return any(term in normalized for term in ("que es", "que sabes", "cuentame", "vale la pena", "dificil"))
        return any(term in normalized for term in ("que es", "que sabes de", "cuentame sobre", "cuentame de", "vale la pena"))

    @classmethod
    def _looks_like_poi_selection(cls, message: str) -> bool:
        normalized = cls._normalize_text(message)
        return bool(re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", normalized)) or any(
            term in normalized
            for term in (
                "seleccionar poi",
                "usar poi",
                "quiero ir a",
                "me gustaria ir a",
                "me gustaría ir a",
                "elijo",
                "selecciono",
            )
        )

    @classmethod
    def _specific_search_query(cls, message: str, session: AraSession) -> str | None:
        normalized = cls._normalize_text(message)
        base_destination = session.initial_query or "Pucón"
        if any(term in normalized for term in ("nieve", "ski", "esqui", "esquí", "snowboard")):
            return f"nieve ski centro de ski montaña senderismo {base_destination}"
        if any(term in normalized for term in ("alojamiento", "hotel", "cabana", "cabaña", "hostal", "hostel", "camping")):
            return f"alojamiento hotel cabaña hostal {base_destination}"
        return None

    async def _resolve_poi_reference(
        self,
        db: AsyncSession,
        session: AraSession,
        message: str,
        comprehension: ComprehensionResult,
    ) -> Any | None:
        uuid_match = re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            message,
            flags=re.IGNORECASE,
        )
        if uuid_match:
            pois = await poi_repository.get_pois_by_ids(db, [UUID(uuid_match.group(0))])
            if pois:
                return pois[0]

        candidates = []
        if session.candidate_poi_ids:
            candidates = await poi_repository.get_pois_by_ids(db, list(session.candidate_poi_ids))

        normalized_message = self._normalize_text(message)
        entity_names = [entity.valor for entity in comprehension.entidades if entity.tipo == "poi"]
        names_to_match = entity_names or []
        names_to_match.extend([getattr(candidate, "name", "") for candidate in candidates])

        for candidate in candidates:
            candidate_name = self._normalize_text(getattr(candidate, "name", ""))
            if candidate_name and candidate_name in normalized_message:
                return candidate

        for name in names_to_match:
            if not name:
                continue
            normalized_name = self._normalize_text(name)
            if normalized_name and normalized_name in normalized_message:
                matches = await poi_repository.search_by_name(db, name, limit=1)
                if matches:
                    return matches[0]

        return None

    @staticmethod
    def _remember_selected_poi(session: AraSession, poi: Any) -> None:
        preferences = dict(session.preferences_data or {})
        trip_draft = dict(preferences.get("trip_draft") or {})
        selected = list(trip_draft.get("selected_poi_ids") or preferences.get("selected_poi_ids") or [])
        poi_id = str(getattr(poi, "id"))
        if poi_id not in selected:
            selected.append(poi_id)
        trip_draft["selected_poi_ids"] = selected
        preferences["selected_poi_ids"] = selected
        preferences["trip_draft"] = trip_draft
        session.preferences_data = preferences

    @staticmethod
    def _filter_repeated_pois(session: AraSession, pois: list[Any]) -> list[Any]:
        preferences = session.preferences_data or {}
        trip_draft = preferences.get("trip_draft") if isinstance(preferences, dict) else {}
        selected_ids = {str(poi_id) for poi_id in (trip_draft or {}).get("selected_poi_ids", [])}
        shown_ids = {str(poi_id) for poi_id in (trip_draft or {}).get("shown_candidate_poi_ids", [])}

        unseen = [poi for poi in pois if str(getattr(poi, "id", "")) not in selected_ids | shown_ids]
        if unseen:
            return unseen
        return [poi for poi in pois if str(getattr(poi, "id", "")) not in selected_ids]

    @staticmethod
    def _remember_shown_pois(session: AraSession, poi_ids: list[UUID]) -> None:
        preferences = dict(session.preferences_data or {})
        trip_draft = dict(preferences.get("trip_draft") or {})
        shown = list(trip_draft.get("shown_candidate_poi_ids") or [])
        for poi_id in poi_ids:
            value = str(poi_id)
            if value not in shown:
                shown.append(value)
        trip_draft["shown_candidate_poi_ids"] = shown[-50:]
        preferences["trip_draft"] = trip_draft
        session.preferences_data = preferences

    async def _get_weather(self, session: AraSession) -> dict[str, Any]:
        if not (session.lat and session.lon and session.start_date and session.end_date):
            return {"type": "weather", "forecast": None}

        try:
            forecast = await get_weather_forecast(
                lat=session.lat, lon=session.lon,
                start_date=session.start_date, end_date=session.end_date,
            )
            return {"type": "weather", "forecast": forecast}
        except Exception as exc:
            logger.warning("get_weather failed: %s", exc)
            return {"type": "weather", "forecast": None}

    async def _build_itinerary(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
        candidate_pois: list,
        weather_forecast: str | None,
    ) -> Any:
        if not session.start_date or not session.end_date:
            raise ValueError("Fechas de inicio y fin son requeridas para generar itinerario")

        payload = GenerateItineraryRequest(
            query=session.initial_query,
            lat=session.lat,
            lon=session.lon,
            radius=session.radius or 5000,
            start_date=session.start_date,
            end_date=session.end_date,
        )

        messages = session.__dict__.get("messages") or []
        user_messages = [m.content for m in messages if m.role == "user"]
        refined_query = f"Consulta: {session.initial_query}. Mensajes: {' | '.join(user_messages)}"

        schedule_guidance = build_schedule_guidance(payload)

        # Convert dicts back to POIResponse objects for generate_itinerary()
        from app.schemas.poi import POIResponse
        poi_objects: list[POIResponse] = []
        for p in candidate_pois:
            if isinstance(p, dict):
                poi_objects.append(POIResponse(
                    id=p.get("id"),
                    name=p.get("name", ""),
                    description=p.get("description") or "",
                    access_type=p.get("access_type", "public"),
                    latitude=p.get("latitude") or 0.0,
                    longitude=p.get("longitude") or 0.0,
                    category_ids=p.get("category_ids", []),
                    image_url=p.get("image_url"),
                    distance_meters=p.get("distance_meters"),
                    poi_role=p.get("poi_role"),
                ))
            elif hasattr(p, "model_dump"):
                poi_objects.append(p)
            else:
                poi_objects.append(POIResponse(
                    id=getattr(p, "id", None),
                    name=getattr(p, "name", ""),
                    description=getattr(p, "description", "") or "",
                    access_type=getattr(p, "access_type", "public"),
                    latitude=getattr(p, "latitude", 0.0) or 0.0,
                    longitude=getattr(p, "longitude", 0.0) or 0.0,
                    category_ids=list(getattr(p, "category_ids", []) or []),
                    image_url=getattr(p, "image_url", None),
                    distance_meters=getattr(p, "distance_meters", None),
                    poi_role=getattr(p, "poi_role", None),
                ))

        generator = get_itinerary_generator()
        raw_itinerary = await generator.generate_itinerary(
            user_query=refined_query,
            context_pois=poi_objects,
            weather_forecast=weather_forecast or "No disponible",
            schedule_guidance=schedule_guidance,
        )

        validate_generated_itinerary_rules(raw_itinerary, poi_objects, payload)

        saved = await itinerary_repository.create_generated_itinerary(
            db, user.id, session.start_date, session.end_date, raw_itinerary
        )
        session.generated_itinerary_id = saved.id
        return saved

    async def _suggest_replacement(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        from app.services.ara_itinerary_generation import (
            build_step_replacement_context,
            search_step_replacement_alternatives,
        )

        replacement_context = (session.preferences_data or {}).get("replacement_context", {})
        itinerary_id = replacement_context.get("itinerary_id")
        step_id = replacement_context.get("step_id")

        if not (itinerary_id and step_id):
            return {"alternatives": [], "error": "No hay contexto de reemplazo disponible"}

        context = await build_step_replacement_context(db, user, UUID(itinerary_id), UUID(step_id))
        if not context:
            return {"alternatives": [], "error": "Itinerario o paso no encontrado"}

        _, step, current_poi = context
        alternatives = await search_step_replacement_alternatives(
            db, user, get_embedding_service(),
            message="", current_poi=current_poi,
            lat=session.lat, lon=session.lon, radius=8000,
        )

        return {"alternatives": alternatives[:3], "current_poi_name": current_poi.name}

    @staticmethod
    def _build_clarification_text(comprehension: ComprehensionResult) -> str:
        questions = comprehension.preguntas_pendientes
        if len(questions) == 1:
            return questions[0]
        return " ".join(f"{i+1}. {q}" for i, q in enumerate(questions))


_orchestrator: ToolOrchestrator | None = None


def get_tool_orchestrator() -> ToolOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ToolOrchestrator()
    return _orchestrator


def reset_tool_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
