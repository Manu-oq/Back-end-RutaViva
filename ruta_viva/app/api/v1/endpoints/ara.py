from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.schemas.ara import (
    AraGenerateItineraryRequest,
    AraIntentUpdate,
    AraMessageCreate,
    AraMessagesResponse,
    AraSessionCreate,
    AraSessionResponse,
)
from app.services.ara_conversation_orchestrator import (
    create_session_v2,
    handle_message_v2,
)
from app.services.ara_streaming_service import stream_itinerary_generation
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator

ara_repository = AraRepository()

router = APIRouter(tags=["ara"])

logger = logging.getLogger(__name__)


def _ensure_tourist(current_user: User) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")


@router.post("/sessions", response_model=AraSessionResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_ara_session(
    request: Request,
    payload: AraSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraSessionResponse:
    _ensure_tourist(current_user)
    logger.info("Creating Ara session for user=%s", current_user.id)
    return await create_session_v2(db, current_user, payload)


@router.post("/sessions/{session_id}/messages", response_model=AraSessionResponse)
@limiter.limit("10/minute")
async def add_ara_message(
    request: Request,
    session_id: UUID,
    payload: AraMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraSessionResponse:
    _ensure_tourist(current_user)
    logger.info("Adding message to session=%s user=%s", session_id, current_user.id)
    return await handle_message_v2(db, current_user, session_id, payload)


@router.get("/sessions/{session_id}/messages", response_model=AraMessagesResponse)
async def list_ara_messages(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraMessagesResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    return AraMessagesResponse(
        session_id=session.id,
        status=session.status,
        messages=[ara_repository.to_message_response(message) for message in session.messages],
    )


@router.patch("/sessions/{session_id}/intent", response_model=AraSessionResponse)
async def update_session_intent(
    session_id: UUID,
    payload: AraIntentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraSessionResponse:
    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    from app.services.ara_v2.conversation_processor import get_conversation_processor

    processor = get_conversation_processor()
    try:
        response = await processor.update_session_intent(
            db=db,
            session=session,
            payload=payload,
        )
        await ara_repository.commit_or_rollback(db)
        return response
    except Exception:
        logger.exception("Failed to update session intent for session=%s", session_id)
        await db.rollback()
        raise


@router.post(
    "/sessions/{session_id}/generate-itinerary/stream",
)
@limiter.limit("3/minute")
async def stream_generate_itinerary(
    request: Request,
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    llm_service: ItineraryGenerator = Depends(get_itinerary_generator),
) -> StreamingResponse:
    _ensure_tourist(current_user)
    logger.info("Starting itinerary stream generation for session=%s user=%s", session_id, current_user.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for event in stream_itinerary_generation(
            session_id=session_id,
            payload=payload,
            db=db,
            current_user=current_user,
            embedding_service=embedding_service,
            llm_service=llm_service,
        ):
            yield event

    return StreamingResponse(event_generator(), media_type="text/event-stream")


