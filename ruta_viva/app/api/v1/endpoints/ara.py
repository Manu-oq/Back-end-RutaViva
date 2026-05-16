from __future__ import annotations

from datetime import date
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.endpoints.itineraries import (
    _build_schedule_guidance,
    _prepare_context_pois,
    _trip_days,
    _validate_generated_itinerary_rules,
)
from app.db.session import get_db
from app.models.ara_message import AraMessage
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import (
    AraGenerateItineraryRequest,
    AraGenerateItineraryResponse,
    AraMessageCreate,
    AraMessageResponse,
    AraMessagesResponse,
    AraSessionCreate,
    AraSessionResponse,
)
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary
from app.services.ara_service import AraConversationService, get_ara_conversation_service
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
from app.services.weather_service import get_forecast

router = APIRouter(tags=["ara"])
ara_repository = AraRepository()
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


def _ensure_tourist(current_user: User) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")


def _normalize_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    normalized_start = start_date or date.today()
    normalized_end = end_date or normalized_start
    return normalized_start, normalized_end


async def _search_candidate_pois(
    db: AsyncSession,
    payload_query: str,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    lat: float | None,
    lon: float | None,
    radius: float | None,
    limit: int = 12,
):
    if lat is None or lon is None:
        return []

    query_embedding = await embedding_service.get_embedding(payload_query)
    return await poi_repository.search_hybrid(
        db,
        lat=lat,
        lon=lon,
        radius_meters=radius or 5000,
        query_embedding=query_embedding,
        user_interests_embedding=current_user.tourist_profile.interests_embedding if current_user.tourist_profile else None,
        limit=limit,
    )


def _session_message_response(message: AraMessage) -> AraMessageResponse:
    return ara_repository.to_message_response(message)


@router.post("/sessions", response_model=AraSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_ara_session(
    payload: AraSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    ara_service: AraConversationService = Depends(get_ara_conversation_service),
) -> AraSessionResponse:
    _ensure_tourist(current_user)

    intent = ara_service.analyze_message(payload.initial_message)
    preferences = ara_service.merge_preferences(payload.initial_message)
    candidate_pois = await _search_candidate_pois(
        db,
        payload.initial_message,
        current_user,
        embedding_service,
        lat=payload.lat,
        lon=payload.lon,
        radius=payload.radius,
    )
    quick_replies = ara_service.build_quick_replies(intent, preferences)
    assistant_text = ara_service.build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=True,
    )

    try:
        start_date, end_date = _normalize_dates(payload.start_date, payload.end_date)
        session = await ara_repository.create_session(
            db,
            tourist_id=current_user.id,
            initial_query=payload.initial_message,
            lat=payload.lat,
            lon=payload.lon,
            radius=payload.radius,
            start_date=start_date,
            end_date=end_date,
            intent_data=intent,
            preferences_data=preferences,
            candidate_poi_ids=[poi.id for poi in candidate_pois],
        )
        user_message = await ara_repository.add_message(
            db,
            session_id=session.id,
            role="user",
            content=payload.initial_message,
        )
        assistant_message = await ara_repository.add_message(
            db,
            session_id=session.id,
            role="assistant",
            content=assistant_text,
            quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
            metadata={"intent": intent, "candidate_poi_count": len(candidate_pois)},
        )
        await ara_repository.commit_or_rollback(db)
    except Exception:
        await db.rollback()
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=_session_message_response(user_message),
        assistant_message=_session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=intent,
        preferences=preferences,
        candidate_pois=ara_service.compact_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
    )


@router.post("/sessions/{session_id}/messages", response_model=AraSessionResponse)
async def add_ara_message(
    session_id: UUID,
    payload: AraMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    ara_service: AraConversationService = Depends(get_ara_conversation_service),
) -> AraSessionResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    previous_intent = session.intent_data or {}
    previous_preferences = session.preferences_data or {}
    intent = ara_service.analyze_message(payload.message, previous_intent)
    preferences = ara_service.merge_preferences(payload.message, previous_preferences)
    query_for_search = f"{session.initial_query}. {payload.message}"
    candidate_pois = await _search_candidate_pois(
        db,
        query_for_search,
        current_user,
        embedding_service,
        lat=session.lat,
        lon=session.lon,
        radius=session.radius,
    )
    if not candidate_pois and session.candidate_poi_ids:
        candidate_pois = await poi_repository.get_pois_by_ids(db, [UUID(poi_id) for poi_id in session.candidate_poi_ids])

    status_value = "ready_to_generate" if preferences.get("auto_generate_requested") else "clarifying"
    quick_replies = ara_service.build_quick_replies(intent, preferences)
    assistant_text = ara_service.build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=False,
    )

    try:
        await ara_repository.update_session_context(
            db,
            session,
            status=status_value,
            intent_data=intent,
            preferences_data=preferences,
            candidate_poi_ids=[poi.id for poi in candidate_pois],
        )
        user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
        assistant_message = await ara_repository.add_message(
            db,
            session.id,
            "assistant",
            assistant_text,
            quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
            metadata={"intent": intent, "candidate_poi_count": len(candidate_pois)},
        )
        await ara_repository.commit_or_rollback(db)
    except Exception:
        await db.rollback()
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=_session_message_response(user_message),
        assistant_message=_session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=intent,
        preferences=preferences,
        candidate_pois=ara_service.compact_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
    )


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


@router.post("/sessions/{session_id}/generate-itinerary", response_model=AraGenerateItineraryResponse, status_code=status.HTTP_201_CREATED)
async def generate_itinerary_from_ara_session(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    llm_service: ItineraryGenerator = Depends(get_itinerary_generator),
    ara_service: AraConversationService = Depends(get_ara_conversation_service),
) -> AraGenerateItineraryResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")
    if session.lat is None or session.lon is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="lat and lon are required to generate an itinerary from an Ara session.",
        )

    final_instruction = payload.final_instruction if payload is not None else None
    user_messages = [message.content for message in session.messages if message.role == "user"]
    if final_instruction:
        user_messages.append(final_instruction)

    refined_query = ara_service.build_refined_query(
        session.initial_query,
        user_messages,
        session.intent_data,
        session.preferences_data,
    )

    start_date, end_date = _normalize_dates(session.start_date, session.end_date)
    generation_payload = GenerateItineraryRequest(
        query=refined_query,
        lat=session.lat,
        lon=session.lon,
        radius=session.radius or 5000,
        start_date=start_date,
        end_date=end_date,
    )

    query_embedding = await embedding_service.get_embedding(refined_query)
    trip_days = _trip_days(generation_payload)
    retrieval_limit = min(35, max(8, trip_days * 6))

    context_pois = []
    if session.candidate_poi_ids:
        context_pois = await poi_repository.get_pois_by_ids(db, [UUID(poi_id) for poi_id in session.candidate_poi_ids])
    if len(context_pois) < 5:
        context_pois = await poi_repository.search_hybrid(
            db,
            lat=generation_payload.lat,
            lon=generation_payload.lon,
            radius_meters=generation_payload.radius,
            query_embedding=query_embedding,
            user_interests_embedding=current_user.tourist_profile.interests_embedding,
            limit=retrieval_limit,
        )

    context_pois = _prepare_context_pois(refined_query, context_pois, retrieval_limit)
    if not context_pois:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No relevant POIs were found for Ara.")

    enriched_query = (
        f"Solicitud refinada por conversación con Ara: {refined_query}\n"
        f"Fechas del viaje: desde {start_date.isoformat()} hasta {end_date.isoformat()}\n"
        f"Ubicación de referencia: lat={generation_payload.lat}, lon={generation_payload.lon}\n"
        f"Radio máximo: {generation_payload.radius} metros\n"
        f"Duración: {trip_days} día(s)"
    )
    schedule_guidance = _build_schedule_guidance(generation_payload)

    try:
        weather_forecast = await get_forecast(
            generation_payload.lat,
            generation_payload.lon,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather forecast provider failed while generating the itinerary.",
        ) from exc

    await ara_repository.update_session_context(db, session, status="generating")
    await ara_repository.commit_or_rollback(db)

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
    )
    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)

    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The LLM returned POIs outside Ara context.")
    if not generated_itinerary.steps:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ara did not return itinerary steps.")

    _validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)

    itinerary = await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        generated_itinerary=generated_itinerary,
    )

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is not None:
        await ara_repository.update_session_context(
            db,
            session,
            status="completed",
            generated_itinerary_id=itinerary.id,
        )
        await ara_repository.add_message(
            db,
            session.id,
            "assistant",
            "Listo, armé un itinerario personalizado con lo que conversamos.",
            metadata={"generated_itinerary_id": str(itinerary.id)},
        )
        await ara_repository.commit_or_rollback(db)

    return AraGenerateItineraryResponse(session_id=session_id, status="completed", itinerary=itinerary)
