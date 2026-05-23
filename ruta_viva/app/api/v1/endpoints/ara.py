from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.ara import (
    AraGenerateItineraryAcceptedResponse,
    AraGenerateItineraryRequest,
    AraGenerateItineraryResponse,
    AraGenerationStatusResponse,
    AraMessageCreate,
    AraMessagesResponse,
    AraSessionCreate,
    AraSessionResponse,
)
from app.services.ara_conversation_orchestrator import (
    create_session_v2,
    handle_message_v2,
)
from app.services.ara_itinerary_generation import (
    ara_repository,
    generate_itinerary_from_session,
    itinerary_repository,
    run_ara_itinerary_generation_job,
)
from app.services.ara_streaming_service import stream_itinerary_generation
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator

router = APIRouter(tags=["ara"])


def _ensure_tourist(current_user: User) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")


@router.post("/sessions", response_model=AraSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_ara_session(
    payload: AraSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraSessionResponse:
    _ensure_tourist(current_user)
    return await create_session_v2(db, current_user, payload)


@router.post("/sessions/{session_id}/messages", response_model=AraSessionResponse)
async def add_ara_message(
    session_id: UUID,
    payload: AraMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraSessionResponse:
    _ensure_tourist(current_user)
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


@router.post(
    "/sessions/{session_id}/generate-itinerary",
    response_model=AraGenerateItineraryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_itinerary_from_ara_session(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    llm_service: ItineraryGenerator = Depends(get_itinerary_generator),
) -> AraGenerateItineraryResponse:
    _ensure_tourist(current_user)
    return await generate_itinerary_from_session(
        session_id=session_id,
        payload=payload,
        db=db,
        current_user=current_user,
        embedding_service=embedding_service,
        llm_service=llm_service,
    )


@router.post(
    "/sessions/{session_id}/generate-itinerary/stream",
)
async def stream_generate_itinerary(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    llm_service: ItineraryGenerator = Depends(get_itinerary_generator),
) -> StreamingResponse:
    _ensure_tourist(current_user)

    async def event_generator() -> AsyncGenerator[str, None]:
        async for event in stream_itinerary_generation(
            session_id=session_id,
            payload=payload,
            db=db,
            current_user=current_user,
            embedding_service=embedding_service,
            llm_service=llm_service,
        ):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/sessions/{session_id}/generate-itinerary/async",
    response_model=AraGenerateItineraryAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_itinerary_generation_from_ara_session(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    payload: AraGenerateItineraryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraGenerateItineraryAcceptedResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")
    if session.generated_itinerary_id is not None:
        return AraGenerateItineraryAcceptedResponse(
            session_id=session.id,
            status="completed",
            generated_itinerary_id=session.generated_itinerary_id,
            detail="This Ara session already has a generated itinerary.",
        )

    await ara_repository.update_session_context(db, session, status="queued")
    await ara_repository.add_message(
        db,
        session.id,
        "assistant",
        "Perfecto, estoy armando tu itinerario. Puedes seguir usando la app y revisar el resultado en unos momentos.",
        metadata={"generation_status": "queued"},
    )
    await ara_repository.commit_or_rollback(db)

    background_tasks.add_task(
        run_ara_itinerary_generation_job,
        session_id,
        current_user.id,
        payload,
    )

    return AraGenerateItineraryAcceptedResponse(
        session_id=session.id,
        status="queued",
        generated_itinerary_id=None,
        detail="Itinerary generation started in background.",
    )


@router.get("/sessions/{session_id}/generation-status", response_model=AraGenerationStatusResponse)
async def get_ara_generation_status(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AraGenerationStatusResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    itinerary = None
    if session.generated_itinerary_id is not None:
        itinerary = await itinerary_repository.get_itinerary_by_id(
            db,
            session.generated_itinerary_id,
            current_user.id,
        )

    detail = None
    if session.status in {"queued", "generating"}:
        detail = "Ara is still generating the itinerary."
    elif session.status == "completed":
        detail = "Itinerary generation completed."
    elif session.status == "failed":
        detail = "Itinerary generation failed."

    return AraGenerationStatusResponse(
        session_id=session.id,
        status=session.status,
        generated_itinerary_id=session.generated_itinerary_id,
        itinerary=itinerary,
        detail=detail,
    )