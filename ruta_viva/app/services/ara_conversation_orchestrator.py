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

    processor = get_conversation_processor()
    return await processor.process_user_message(
        db=db,
        session=session,
        current_user=current_user,
        user_message=payload.message,
    )


async def create_session_v2(
    db: AsyncSession,
    current_user: User,
    payload: AraSessionCreate,
) -> AraSessionResponse:
    """Crear nueva sesion de Ara v2."""
    from app.schemas.ara import AraIntentInfo, AraPreferenceSummary

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
        preferences_data={},
        candidate_poi_ids=None,
    )

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=None,
        assistant_message=None,
        quick_replies=[],
        intent=AraIntentInfo(
            intents=["planificar_viaje"],
            primary_intent="planificar_viaje",
            turn_count=0,
        ),
        preferences=AraPreferenceSummary(),
        candidate_pois=[],
    )
