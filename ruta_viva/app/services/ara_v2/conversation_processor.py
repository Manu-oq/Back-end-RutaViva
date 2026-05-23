from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ara_session import AraSession
from app.models.conversation_memory import ConversationMemory
from app.models.user import User
from app.schemas.ara_comprehension import ComprehensionResult
from app.services.ara_v2.comprehender import get_comprensor
from app.services.ara_v2.memory_service import get_memory_service

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
    ) -> ComprehensionResult:
        """Procesa un mensaje del usuario con memoria semantica.

        Flujo:
        1. Recuperar hechos relevantes de conversation_memory
        2. Obtener ultimos mensajes de la sesion como contexto
        3. Llamar al Comprensor
        4. Guardar hechos nuevos en memoria
        5. Actualizar TouristProfile.interests_embedding si corresponde

        Retorna ComprehensionResult para que el orquestador decida que herramienta ejecutar.
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

        return comprehension

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


_processor: ConversationProcessor | None = None


def get_conversation_processor() -> ConversationProcessor:
    global _processor
    if _processor is None:
        _processor = ConversationProcessor()
    return _processor


def reset_conversation_processor() -> None:
    global _processor
    _processor = None
