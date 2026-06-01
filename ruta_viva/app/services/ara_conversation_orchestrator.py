from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.schemas.ara import AraMessageCreate, AraSessionCreate, AraSessionResponse
from app.services.ara_v2.conversation_processor import get_conversation_processor

logger = logging.getLogger(__name__)

ara_repository = AraRepository()


async def handle_message_v2(
    db: AsyncSession,
    current_user: User,
    session_id: UUID,
    payload: AraMessageCreate,
) -> AraSessionResponse:
    """Nuevo handler que usa ConversationProcessor (Ara v2)."""
    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if payload.start_date is not None:
        session.start_date = payload.start_date
    if payload.end_date is not None:
        session.end_date = payload.end_date

    processor = get_conversation_processor()
    try:
        response = await processor.process_user_message(
            db=db,
            session=session,
            current_user=current_user,
            user_message=payload.message,
        )
        await ara_repository.commit_or_rollback(db)
        return response
    except Exception:
        await db.rollback()
        raise


async def create_session_v2(
    db: AsyncSession,
    current_user: User,
    payload: AraSessionCreate,
) -> AraSessionResponse:
    """Crear nueva sesion de Ara v2 y procesar el primer mensaje del usuario."""
    try:
        preferences_data: dict = {
            "trip_draft": {
                "initial_query": payload.initial_message,
                "start_date": payload.start_date.isoformat() if payload.start_date else None,
                "end_date": payload.end_date.isoformat() if payload.end_date else None,
            }
        }

        if payload.metadata and payload.metadata.get("intent") == "change_itinerary_step":
            itinerary_id = payload.metadata.get("itinerary_id")
            step_id = payload.metadata.get("step_id")
            if itinerary_id and step_id:
                preferences_data["replacement_context"] = {
                    "itinerary_id": str(itinerary_id),
                    "step_id": str(step_id),
                }
                preferences_data["conversation_mode"] = "replacement"

        session = await ara_repository.create_session(
            db,
            tourist_id=current_user.id,
            initial_query=payload.initial_message,
            lat=payload.lat,
            lon=payload.lon,
            radius=payload.radius,
            start_date=payload.start_date,
            end_date=payload.end_date,
            intent_data={"initial_query": payload.initial_message},
            preferences_data=preferences_data,
            candidate_poi_ids=None,
        )

        processor = get_conversation_processor()
        response = await processor.process_user_message(
            db=db,
            session=session,
            current_user=current_user,
            user_message=payload.initial_message,
        )
        await ara_repository.commit_or_rollback(db)
        return response
    except Exception:
        await db.rollback()
        raise
