from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ara_constants import KNOWN_DESTINATION_NAMES
from app.models.ara_session import AraSession
from app.models.conversation_memory import ConversationMemory
from app.models.user import User
from app.schemas.ara import AraMessageResponse, AraQuickReply, AraSessionResponse
from app.schemas.ara_comprehension import ComprehensionResult
from app.services.ara_v2.comprehender import get_comprensor
from app.services.ara_v2.memory_service import get_memory_service
from app.services.ara_v2.response_generator import get_response_generator
from app.services.ara_v2.tool_orchestrator import get_tool_orchestrator

logger = logging.getLogger(__name__)

MAX_SESSION_MESSAGES = 10


class ConversationProcessor:
    """Orquesta: recuperar memoria -> comprender -> guardar hechos -> actualizar perfil."""

    async def process_user_message(
        self,
        db: AsyncSession,
        session: AraSession,
        current_user: User,
        user_message: str,
    ) -> AraSessionResponse:
        """Procesa un mensaje del usuario con memoria semantica.

        Flujo:
        1. Recuperar hechos relevantes de conversation_memory
        2. Obtener ultimos mensajes de la sesion como contexto
        3. Llamar al Comprensor
        4. Guardar hechos nuevos en memoria
        5. Actualizar TouristProfile.interests_embedding si corresponde
        6. Ejecutar herramientas
        7. Generar respuesta
        8. Persistir mensajes y devolver respuesta
        """
        memory_service = get_memory_service()
        comprensor = get_comprensor()

        tourist_id = current_user.id

        # PASO 1: Recuperar hechos relevantes ANTES de comprender
        relevant_facts = await memory_service.retrieve_relevant_facts(
            db, tourist_id, user_message, top_k=5,
        )
        if relevant_facts:
            logger.debug(
                "Retrieved %d relevant facts for tourist=%s: %s",
                len(relevant_facts),
                tourist_id,
                [f["hecho"] for f in relevant_facts],
            )

        # PASO 2: Obtener contexto de sesion
        trip_draft = self._build_trip_draft_context(session)
        candidate_pois_count = len(session.candidate_poi_ids or [])

        session_messages = self._get_recent_messages(session)

        # PASO 3: Comprender
        comprehension = await comprensor.comprehend(
            user_message=user_message,
            session_messages=session_messages,
            relevant_facts=relevant_facts,
            trip_draft=trip_draft,
            candidate_pois_count=candidate_pois_count,
        )
        self._apply_comprehension_to_session(session, comprehension, user_message)
        self._filter_resolved_pending_questions(session, comprehension)

        # PASO 4: Guardar hechos nuevos (batch)
        if comprehension.actualizaciones_memoria:
            facts_list = [
                {
                    "hecho": f.hecho,
                    "categoria": f.categoria,
                    "confianza": f.confianza,
                }
                for f in comprehension.actualizaciones_memoria
            ]
            try:
                await memory_service.store_facts_batch(
                    db=db, tourist_id=tourist_id, session_id=session.id, facts=facts_list,
                )
                logger.info(
                    "Memoria guardada (batch): %d facts para tourist=%s",
                    len(facts_list),
                    tourist_id,
                )
            except Exception:
                logger.warning(
                    "Failed to store facts batch for tourist=%s, falling back to individual.",
                    tourist_id,
                )
                for fact in comprehension.actualizaciones_memoria:
                    try:
                        await memory_service.store_fact(
                            db=db,
                            tourist_id=tourist_id,
                            session_id=session.id,
                            hecho=fact.hecho,
                            categoria=fact.categoria,
                            confianza=fact.confianza,
                        )
                        logger.info("Memoria guardada: %s (%s, confianza=%.2f)", fact.hecho, fact.categoria, fact.confianza)
                    except Exception:
                        logger.warning(
                            "Failed to store fact for tourist=%s: %s. Continuing without embedding.",
                            tourist_id,
                            fact.hecho,
                        )
                        try:
                            fact_obj = ConversationMemory(
                                tourist_id=tourist_id,
                                session_id=session.id,
                                hecho=fact.hecho,
                                categoria=fact.categoria,
                                confianza=fact.confianza,
                                embedding=None,
                            )
                            db.add(fact_obj)
                            await db.flush()
                        except Exception:
                            logger.error("Failed to store fact even without embedding: %s", fact.hecho)

        # PASO 5: Actualizar perfil semantico si es preferencia fuerte
        for fact in comprehension.actualizaciones_memoria:
            if fact.categoria == "preferencia" and fact.confianza > 0.8:
                try:
                    updated = await memory_service.update_tourist_profile_embedding(
                        db, tourist_id, fact.hecho, fact.confianza,
                    )
                    if updated:
                        logger.info("Perfil actualizado: %s para tourist=%s", fact.hecho, tourist_id)
                except Exception:
                    logger.warning("Failed to update profile embedding for tourist=%s", tourist_id)

        # PASO 6: Persistir mensaje del usuario ANTES de ejecutar herramientas
        user_msg = await self._add_message(db, session, "user", user_message)

        # PASO 6.5: Geocodificar destino mencionado
        destinos = [e.valor for e in comprehension.entidades if e.tipo == "destino"]
        if destinos:
            from app.services.ara_v2.geocoding_service import geocode_destination
            coords = await geocode_destination(destinos[0])
            if coords:
                lat, lon = coords
                session.set_coordinates(lat, lon)
                preferences = dict(session.preferences_data or {})
                preferences["geocoded_destination"] = {"name": destinos[0], "lat": lat, "lon": lon}
                session.preferences_data = preferences
                logger.info("Destino geocodificado: %s → (%.4f, %.4f)", destinos[0], lat, lon)

        # PASO 7: Ejecutar herramientas
        orchestrator = get_tool_orchestrator()
        tool_result = await orchestrator.execute(
            comprehension=comprehension,
            session=session,
            user=current_user,
            db=db,
            current_user_message=user_message,
        )

        # PASO 8: Si la intención es build_itinerary con fechas, activar SSE y retornar
        if "build_itinerary" in comprehension.herramientas_necesarias and session.start_date and session.end_date:
            stream_url = f"/api/v1/ara/sessions/{session.id}/generate-itinerary/stream"
            assistant_content = "Perfecto, estoy armando tu itinerario. Puedes seguir usando la app mientras trabajo en ello."
            quick_reply_qr = AraQuickReply(id="qr_progress", label="Ver progreso", value="ver_progreso", type="navigation")

            # Persistir el mensaje del asistente ANTES de retornar
            assistant_msg = await self._add_message(
                db, session, "assistant",
                assistant_content,
                quick_replies=[quick_reply_qr.model_dump(mode="json")],
            )

            # Actualizar status de la sesión en DB
            session.status = "ready_to_generate"
            await db.flush()

            return AraSessionResponse(
                session_id=session.id,
                status="ready_to_generate",
                start_date=session.start_date,
                end_date=session.end_date,
                user_message=self._to_message_response(user_msg),
                assistant_message=self._to_message_response(assistant_msg),
                quick_replies=[quick_reply_qr],
                candidate_pois=[],
                progress={"stream_url": stream_url, "generation_status": "starting"},
            )

        # PASO 9: Generar respuesta
        response_gen = get_response_generator()
        response = await response_gen.generate_response(
            comprehension=comprehension,
            tool_result=tool_result,
            session=session,
        )

        # PASO 10: Persistir respuesta del asistente y devolver
        assistant_msg = await self._add_message(
            db, session, "assistant",
            response["text"],
            quick_replies=[qr.model_dump(mode="json") for qr in response.get("quick_replies", [])],
        )

        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            start_date=session.start_date,
            end_date=session.end_date,
            user_message=self._to_message_response(user_msg),
            assistant_message=self._to_message_response(assistant_msg),
            quick_replies=response.get("quick_replies", []),
            candidate_pois=self._build_candidate_pois(tool_result.candidate_pois),
            weather=tool_result.weather_forecast,
        )

    @staticmethod
    def _build_trip_draft_context(session: AraSession) -> dict[str, Any]:
        preferences = dict(session.preferences_data or {})
        trip_draft = dict(preferences.get("trip_draft") or {})
        trip_draft.setdefault("initial_query", session.initial_query)
        if session.start_date is not None:
            trip_draft["start_date"] = session.start_date.isoformat()
        if session.end_date is not None:
            trip_draft["end_date"] = session.end_date.isoformat()
        trip_draft["has_destination"] = ConversationProcessor._session_has_destination(session)
        return trip_draft

    @staticmethod
    def _parse_iso_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _detect_lodging_preference(user_message: str, comprehension: ComprehensionResult) -> dict[str, str] | None:
        normalized = user_message.lower()
        lodging_terms = {
            "cabaña": ("Cabaña", "cabin"),
            "cabana": ("Cabaña", "cabin"),
            "hotel": ("Hotel", "hotel"),
            "hostal": ("Hostal", "hostel"),
            "hostel": ("Hostal", "hostel"),
            "camping": ("Camping", "camping"),
        }
        for term, (label, lodging_type) in lodging_terms.items():
            if term in normalized:
                return {"name": label, "type": lodging_type, "source": "conversation"}

        for fact in comprehension.actualizaciones_memoria:
            if fact.categoria == "alojamiento":
                return {"name": fact.hecho, "type": "lodging", "source": "memory"}
        return None

    @staticmethod
    def _apply_comprehension_to_session(
        session: AraSession,
        comprehension: ComprehensionResult,
        user_message: str,
    ) -> None:
        preferences = dict(session.preferences_data or {})
        trip_draft = dict(preferences.get("trip_draft") or {})
        trip_draft.setdefault("initial_query", session.initial_query)

        # Las fechas elegidas en la UI tienen prioridad. Solo inferimos fechas
        # desde texto cuando la sesion aun no trae rango.
        if session.start_date is None and session.end_date is None and comprehension.rango_fechas:
            start = ConversationProcessor._parse_iso_date(comprehension.rango_fechas.start)
            end = ConversationProcessor._parse_iso_date(comprehension.rango_fechas.end)
            if start is not None and end is not None and end >= start:
                session.start_date = start
                session.end_date = end

        if session.start_date is not None:
            trip_draft["start_date"] = session.start_date.isoformat()
        if session.end_date is not None:
            trip_draft["end_date"] = session.end_date.isoformat()

        lodging = ConversationProcessor._detect_lodging_preference(user_message, comprehension)
        if lodging is not None:
            preferences["lodging"] = lodging
            trip_draft["lodging"] = lodging

        destinos = [entity.valor for entity in comprehension.entidades if entity.tipo == "destino"]
        if destinos:
            trip_draft["destination"] = destinos[0]

        trip_draft["has_destination"] = ConversationProcessor._session_has_destination(session) or bool(destinos)
        preferences["trip_draft"] = trip_draft
        session.preferences_data = preferences

    @staticmethod
    def _session_has_destination(session: AraSession) -> bool:
        preferences = session.preferences_data or {}
        trip_draft = preferences.get("trip_draft") if isinstance(preferences, dict) else None
        if isinstance(trip_draft, dict):
            if trip_draft.get("destination") or trip_draft.get("search_center"):
                return True
            destination_scope = trip_draft.get("destination_scope")
            if isinstance(destination_scope, dict) and destination_scope.get("label"):
                return True

        initial_query = (session.initial_query or "").lower()
        return any(destination.lower() in initial_query for destination in KNOWN_DESTINATION_NAMES)

    @staticmethod
    def _filter_resolved_pending_questions(
        session: AraSession,
        comprehension: ComprehensionResult,
    ) -> None:
        if not comprehension.preguntas_pendientes:
            return

        has_dates = session.start_date is not None and session.end_date is not None
        has_destination = ConversationProcessor._session_has_destination(session) or any(
            entity.tipo == "destino" for entity in comprehension.entidades
        )
        preferences = session.preferences_data or {}
        trip_draft = preferences.get("trip_draft") if isinstance(preferences, dict) else None
        has_lodging = bool(
            preferences.get("lodging")
            or (trip_draft.get("lodging") if isinstance(trip_draft, dict) else None)
        )

        filtered: list[str] = []
        for question in comprehension.preguntas_pendientes:
            normalized = question.lower()
            asks_dates = any(term in normalized for term in ("fecha", "cuándo", "cuando", "viajar", "planeas"))
            asks_destination = any(term in normalized for term in ("destino", "dónde", "donde", "ir"))
            asks_lodging = any(term in normalized for term in ("hotel", "cabaña", "cabana", "alojamiento", "hosped"))

            if has_dates and asks_dates:
                continue
            if has_destination and asks_destination:
                continue
            if has_lodging and asks_lodging:
                continue
            filtered.append(question)

        comprehension.preguntas_pendientes = filtered

    @staticmethod
    def _loaded_messages(session: AraSession) -> list[Any]:
        """Devuelve mensajes ya cargados sin disparar IO implicito.

        En SQLAlchemy async, acceder a una relacion no cargada puede intentar un
        lazy-load sincronico y terminar en MissingGreenlet. Para el contexto de
        conversacion solo necesitamos los mensajes que ya vienen precargados por
        el repositorio, o una lista vacia en sesiones recien creadas.
        """
        return list(session.__dict__.get("messages") or [])

    @staticmethod
    def _get_recent_messages(session: AraSession) -> list[dict[str, Any]]:
        """Extrae los ultimos MAX_SESSION_MESSAGES mensajes de la sesion."""
        messages = ConversationProcessor._loaded_messages(session)
        if not messages:
            return []

        recent = messages[-MAX_SESSION_MESSAGES:]
        return [
            {"role": msg.role, "content": msg.content, "metadata": msg.message_metadata}
            for msg in recent
        ]


    @staticmethod
    async def _add_message(
        db: AsyncSession,
        session: AraSession,
        role: str,
        content: str,
        quick_replies: list[dict] | None = None,
    ) -> Any:
        """Agrega un mensaje a la sesion."""
        from app.models.ara_message import AraMessage
        msg = AraMessage(
            session_id=session.id,
            role=role,
            content=content,
            quick_replies=quick_replies,
        )
        db.add(msg)
        await db.flush()
        loaded_messages = session.__dict__.get("messages")
        if loaded_messages is not None and msg not in loaded_messages:
            loaded_messages.append(msg)
        return msg

    @staticmethod
    def _to_message_response(msg: Any) -> AraMessageResponse:
        """Convierte AraMessage ORM a AraMessageResponse."""
        from app.repositories.ara_repository import AraRepository
        return AraRepository().to_message_response(msg)

    @staticmethod
    def _build_candidate_pois(candidate_pois: list[dict] | None) -> list:
        """Convierte candidate_pois dicts a formato de respuesta."""
        if not candidate_pois:
            return []
        from app.schemas.ara import AraCandidatePOI
        result = []
        for poi in candidate_pois:
            try:
                poi_id = poi.get("id")
                if isinstance(poi_id, str):
                    poi_id = UUID(poi_id)
                elif poi_id is None:
                    poi_id = uuid4()
                result.append(AraCandidatePOI(
                    id=poi_id,
                    name=poi.get("name", ""),
                    description=poi.get("description"),
                    category_ids=poi.get("category_ids", []),
                    latitude=poi.get("latitude"),
                    longitude=poi.get("longitude"),
                    image_url=poi.get("image_url"),
                    distance_meters=poi.get("distance_meters"),
                    poi_role=poi.get("poi_role"),
                ))
            except Exception as exc:
                logger.warning("Failed to convert POI to AraCandidatePOI: %s", exc)
        return result


_processor: ConversationProcessor | None = None


def get_conversation_processor() -> ConversationProcessor:
    global _processor
    if _processor is None:
        _processor = ConversationProcessor()
    return _processor


def reset_conversation_processor() -> None:
    global _processor
    _processor = None
