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
from app.schemas.ara import AraGenerateItineraryRequest
from app.schemas.ara_comprehension import ComprehensionResult, ToolExecutionResult
from app.services.ara_itinerary_core import generate_itinerary_core
from app.services.embedding_service import get_embedding_service
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
        # Gate de fuera-de-domino: evitar consumir recursos en mensajes irrelevantes
        if comprehension.intencion_principal == "general" and comprehension.confianza < 0.4:
            return ToolExecutionResult(
                status="clarify",
                response_text=(
                    "Soy Ara, tu asistente de viajes. "
                    "Puedo ayudarte a planificar itinerarios, buscar lugares y organizar tu viaje. "
                    "¿A dónde quieres ir?"
                ),
            )

        tools = list(comprehension.herramientas_necesarias)
        result = ToolExecutionResult(status="respond")
        current_user_message = current_user_message or ""

        # Redirigir answer_question → search_pois cuando no hay entidad POI
        # (solo destino/ciudad). Evita que "voy a Pucón" se trate como pregunta.
        if "answer_question" in tools and not any(e.tipo == "poi" for e in comprehension.entidades):
            has_poi_question_terms = any(
                term in self._normalize_text(current_user_message)
                for term in ("que es", "que sabes", "cuentame", "vale la pena", "dificil")
            )
            if not has_poi_question_terms:
                tools = [t for t in tools if t != "answer_question"]
                if "search_pois" not in tools:
                    tools.append("search_pois")
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
            # Use comprehension quick replies if available, otherwise let response generator decide
            result.quick_replies = comprehension.sugerir_quick_replies or []
            return result

        # 1. Herramientas independientes en paralelo
        tasks: list[asyncio.Task] = []
        search_already_executed = "search_pois" in tools
        if search_already_executed:
            tasks.append(asyncio.create_task(self._search_pois(db, user, comprehension, session, current_user_message)))
        if "get_weather" in tools and session.start_date and session.end_date and session.lat is not None:
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
            # Don't build itinerary if critical info is missing — let clarification run first
            if not session.start_date or not session.end_date:
                # Fall through to clarification section below
                pass
            # If SSE streaming already started, don't generate a second itinerary
            elif session.status == "ready_to_generate":
                result.status = "respond"
                result.response_text = "Estoy generando tu itinerario en segundo plano. Puedes ver el progreso en cualquier momento."
                return result
            else:
                # Signal that itinerary generation is needed — actual generation happens via SSE
                # to avoid blocking the conversational flow
                result.status = "itinerary_pending"
                result.response_text = "Estoy armando tu itinerario personalizado..."
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
                # Si no encontro el POI, redirigir a busqueda
                if answer.get("evidence_level") == "unknown" and "no tengo" in answer.get("text", "").lower():
                    logger.info("answer_question no encontro POI, redirigiendo a search_pois")
                    tools = [t for t in tools if t != "answer_question"]
                    if "search_pois" not in tools:
                        tools.append("search_pois")
                    # Continue to search instead of returning
                else:
                    result.response_text = answer["text"]
                    result.status = "respond"
                    return result
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

        # Use geocoded destination coordinates if available, fallback to GPS
        geocoded = (session.preferences_data or {}).get("geocoded_destination")
        if geocoded and isinstance(geocoded, dict):
            lat = geocoded.get("lat")
            lon = geocoded.get("lon")
        else:
            lat = session.lat
            lon = session.lon
        radius = session.radius or 8000

        # Resolve comprehender category intents to DB category names, then to IDs
        resolved_category_ids: list[int] | None = None
        if categorias:
            from app.models.category import Category
            from app.services.ara_v2.category_mapping import CATEGORY_INTENT_TO_DB_NAMES
            from sqlalchemy import func, select

            # Map each intent to its DB category names
            db_category_names: set[str] = set()
            for cat in categorias:
                cat_lower = cat.lower()
                mapped_names = CATEGORY_INTENT_TO_DB_NAMES.get(cat_lower, [])
                if mapped_names:
                    db_category_names.update(mapped_names)
                else:
                    # If no mapping exists, fall back to general search (no category filter)
                    logger.info("Unmapped category '%s' — searching without category filter", cat)
                    db_category_names.clear()
                    break

            # Case-insensitive lookup in the database (only if we have names to look up)
            if db_category_names:
                stmt = select(Category.id).where(
                    func.lower(Category.name).in_([name.lower() for name in db_category_names])
                )
                result = await db.execute(stmt)
                found_ids = [row[0] for row in result.all()]
                if found_ids:
                    resolved_category_ids = found_ids
                # If still no IDs found after mapping, proceed without category filter

        query_parts = [destino] if destino else []
        query_parts.extend(preferencias)
        query_parts.extend(categorias)
        specific_query = self._specific_search_query(message, session)
        search_query = specific_query or " ".join(query_parts) or message or session.initial_query

        try:
            pois = await search_candidate_pois(
                db, poi_repository, search_query, user,
                None, lat=lat, lon=lon, radius=radius,
                category_ids=resolved_category_ids,
            )
            pois = self._filter_repeated_pois(session, pois)

            session.candidate_poi_ids = [poi.id for poi in pois]
            self._remember_shown_pois(session, [poi.id for poi in pois])
            return {"type": "pois", "pois": [self._serialize_poi(poi) for poi in pois], "count": len(pois)}
        except Exception as exc:
            logger.warning("search_pois failed: %s", exc)
            return {"type": "pois", "pois": [], "count": 0}

    async def _search_diverse_pois(
        self,
        db: AsyncSession,
        user: User,
        session: AraSession,
    ) -> dict[str, Any]:
        """Search POIs across multiple categories for diverse itinerary context.

        Parallelizes category searches and caches the embedding to avoid
        redundant OpenAI API calls.
        """
        import asyncio

        from app.models.category import Category
        from app.services.ara_v2.category_mapping import CATEGORY_INTENT_TO_DB_NAMES
        from app.services.embedding_service import get_embedding_service
        from sqlalchemy import func, select

        lat = session.lat
        lon = session.lon
        radius = session.radius or 8000

        # Build diverse category search: pick top categories from mapping
        diverse_categories = ["naturaleza", "gastronomia", "cultura", "aventura", "termas"]
        db_category_names: set[str] = set()
        for cat in diverse_categories:
            mapped = CATEGORY_INTENT_TO_DB_NAMES.get(cat, [])
            db_category_names.update(mapped)

        if not db_category_names:
            return {"type": "pois", "pois": [], "count": 0}

        # Lookup category IDs
        stmt = select(Category.id).where(
            func.lower(Category.name).in_([name.lower() for name in db_category_names])
        )
        result = await db.execute(stmt)
        category_ids = [row[0] for row in result.all()]

        # Generate embedding ONCE for all searches
        search_query = session.initial_query or "turismo La Araucania actividades"
        embedding_service = get_embedding_service()
        try:
            query_embedding = await embedding_service.get_embedding(search_query)
        except Exception as exc:
            logger.warning("Failed to generate embedding for diverse search: %s", exc)
            return {"type": "pois", "pois": [], "count": 0}

        # Parallel search per category
        async def _search_single_category(cat_id: int) -> list:
            try:
                return await search_candidate_pois(
                    db, poi_repository, search_query, user,
                    None, lat=lat, lon=lon, radius=radius,
                    limit=5,
                    category_ids=[cat_id],
                    query_embedding=query_embedding,
                )
            except Exception as exc:
                logger.warning("Diverse search failed for category %s: %s", cat_id, exc)
                return []

        tasks = [_search_single_category(cat_id) for cat_id in category_ids]
        category_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine results, deduplicating by ID
        all_pois: list = []
        seen_ids: set = set()
        for cat_result in category_results:
            if isinstance(cat_result, Exception):
                continue
            for poi in cat_result:
                poi_id = getattr(poi, "id", None)
                if poi_id and poi_id not in seen_ids:
                    all_pois.append(poi)
                    seen_ids.add(poi_id)

        # Ensure minimum POIs: if below 15, do a general search without category filter
        min_pois = 15
        if len(all_pois) < min_pois:
            try:
                general_pois = await search_candidate_pois(
                    db, poi_repository, search_query, user,
                    None, lat=lat, lon=lon, radius=radius,
                    limit=min_pois - len(all_pois),
                    query_embedding=query_embedding,
                )
                for poi in general_pois:
                    poi_id = getattr(poi, "id", None)
                    if poi_id and poi_id not in seen_ids:
                        all_pois.append(poi)
                        seen_ids.add(poi_id)
            except Exception as exc:
                logger.warning("Fallback general POI search failed: %s", exc)

        # Deduplicate against already-shown POIs
        all_pois = self._filter_repeated_pois(session, all_pois)

        if all_pois:
            session.candidate_poi_ids = [poi.id for poi in all_pois]
            self._remember_shown_pois(session, [poi.id for poi in all_pois])

        return {"type": "pois", "pois": [self._serialize_poi(poi) for poi in all_pois], "count": len(all_pois)}

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
            "access_type": getattr(poi, "access_type", "public"),
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
        """Normalize text for keyword matching — strips accents for broader matching."""
        normalized = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_accents.lower()).strip()

    @staticmethod
    def _normalize_for_name_match(value: str) -> str:
        """Normalize text for POI name matching — preserves accents to avoid false positives."""
        return re.sub(r"\s+", " ", (value or "").lower()).strip()

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
            candidate_name = self._normalize_for_name_match(getattr(candidate, "name", ""))
            if candidate_name and candidate_name in normalized_message:
                return candidate

        for name in names_to_match:
            if not name:
                continue
            normalized_name = self._normalize_for_name_match(name)
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

        # Include user-selected POIs in candidate_pois
        if session.preferences_data:
            selected_poi_ids = session.preferences_data.get("selected_poi_ids") or []
            if selected_poi_ids:
                from app.schemas.poi import POIResponse
                existing_ids = {getattr(p, "id", None) for p in candidate_pois} | {p.get("id") for p in candidate_pois if isinstance(p, dict)}
                for sid in selected_poi_ids:
                    try:
                        selected_poi = await poi_repository.get_poi_by_id(db, UUID(str(sid)))
                        if selected_poi and selected_poi.id not in existing_ids:
                            candidate_pois = [selected_poi] + list(candidate_pois)
                            existing_ids.add(selected_poi.id)
                    except Exception:
                        logger.warning("Could not load selected POI %s", sid)

        async def _log_phase(name: str, extra: dict | None = None) -> None:
            logger.info("Itinerary phase: %s extra=%s", name, extra)

        itinerary, _, _ = await generate_itinerary_core(
            session=session,
            payload=AraGenerateItineraryRequest(),
            db=db,
            current_user=user,
            embedding_service=get_embedding_service(),
            llm_service=get_itinerary_generator(),
            candidate_pois=candidate_pois,
            weather_forecast=weather_forecast,
            on_phase=_log_phase,
        )
        return itinerary

    async def _suggest_replacement(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        from app.services.ara_replacement_service import (
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
