from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

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
        trip_draft = session.preferences_data.get("trip_draft") if session.preferences_data else None
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

        # PASO 4: Guardar hechos nuevos
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

        # PASO 6: Ejecutar herramientas
        orchestrator = get_tool_orchestrator()
        tool_result = await orchestrator.execute(
            comprehension=comprehension,
            session=session,
            user=current_user,
            db=db,
        )

        # PASO 7: Generar respuesta
        response_gen = get_response_generator()
        response = await response_gen.generate_response(
            comprehension=comprehension,
            tool_result=tool_result,
            session=session,
        )

        # PASO 8: Persistir mensajes y devolver respuesta
        user_msg = await self._add_message(db, session, "user", user_message)
        assistant_msg = await self._add_message(
            db, session, "assistant",
            response["text"],
            quick_replies=[qr.model_dump(mode="json") for qr in response.get("quick_replies", [])],
        )

        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=self._to_message_response(user_msg),
            assistant_message=self._to_message_response(assistant_msg),
            quick_replies=response.get("quick_replies", []),
            candidate_pois=self._build_candidate_pois(tool_result.candidate_pois),
            weather=tool_result.weather_forecast,
        )

    @staticmethod
    def _get_recent_messages(session: AraSession) -> list[dict[str, Any]]:
        """Extrae los ultimos MAX_SESSION_MESSAGES mensajes de la sesion."""
        if not session.messages:
            return []

        recent = session.messages[-MAX_SESSION_MESSAGES:]
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
            except Exception:
                pass
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
