from __future__ import annotations

import logging
import time
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ara_messages import AraMessages
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary
from app.services.ara_response_builder import build_refined_query
from app.services.embedding_service import EmbeddingCache, OpenAIEmbeddingService, get_embedding_service
from app.services.itinerary_generation_service import (
    build_schedule_guidance,
    filter_blacklisted_context_pois,
    merge_unique_context_pois,
    normalize_generated_itinerary_times,
    prepare_context_pois,
    repair_duplicate_poi_steps,
    repair_schedule_and_category_issues,
    sanitize_generated_itinerary_context,
    trip_days,
    validate_generated_itinerary_rules,
)
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
from app.services.poi_search_service import (
    filter_pois_to_search_center,
    search_candidate_pois,
    search_generation_context_with_fallbacks,
)
from app.services.weather_service import get_forecast

logger = logging.getLogger(__name__)

ara_repository = AraRepository()
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


def _candidate_uuid_list(candidate_poi_ids: list[UUID] | list[str] | None) -> list[UUID]:
    return [
        poi_id if isinstance(poi_id, UUID) else UUID(str(poi_id))
        for poi_id in (candidate_poi_ids or [])
    ]


def normalize_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    normalized_start = start_date or date.today()
    normalized_end = end_date or normalized_start
    return normalized_start, normalized_end


async def generate_itinerary_from_session(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service,
    llm_service: ItineraryGenerator,
) -> AraGenerateItineraryResponse:
    _phase_start = time.monotonic()
    logger.info("Itinerary generation START session_id=%s user_id=%s", session_id, current_user.id)
    if current_user.tourist_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")

    embedding_cache = EmbeddingCache(embedding_service)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    preferences_data = session.preferences_data or {}
    trip_draft = preferences_data.get("trip_draft") or {}
    search_center = trip_draft.get("search_center") if isinstance(trip_draft, dict) else {}
    effective_lat = session.lat
    effective_lon = session.lon
    if (effective_lat is None or effective_lon is None) and isinstance(search_center, dict):
        effective_lat = search_center.get("lat")
        effective_lon = search_center.get("lon")

    if effective_lat is None or effective_lon is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ara needs a destination/search center before generating an itinerary.",
        )

    final_instruction = payload.final_instruction if payload is not None else None
    user_messages = [message.content for message in session.messages if message.role == "user"]
    if final_instruction:
        user_messages.append(final_instruction)

    refined_query = build_refined_query(
        session.initial_query,
        user_messages,
        session.intent_data,
        session.preferences_data,
    )

    search_query = refined_query
    if preferences_data.get("surprise_route_requested"):
        search_query += (
            "\nRuta sorpresa equilibrada: recuperar un pool diverso, no solo lugares gastronomicos. "
            "Incluir naturaleza, cultura, miradores, descanso, actividades suaves y gastronomia."
        )

    destination_scope = trip_draft.get("destination_scope") if isinstance(trip_draft, dict) else {}
    strict_destination = bool((destination_scope or {}).get("strict"))

    start_date, end_date = normalize_dates(session.start_date, session.end_date)
    generation_payload = GenerateItineraryRequest(
        query=refined_query,
        lat=float(effective_lat),
        lon=float(effective_lon),
        radius=session.radius or 5000,
        start_date=start_date,
        end_date=end_date,
    )

    num_days = trip_days(generation_payload)
    retrieval_limit = min(80, max(20, num_days * 12))
    logger.info(
        "Phase: query built session_id=%s days=%d retrieval_limit=%d lat=%s lon=%s",
        session_id, num_days, retrieval_limit, generation_payload.lat, generation_payload.lon,
    )

    session_context_pois = []
    if session.candidate_poi_ids:
        session_context_pois = await poi_repository.get_pois_by_ids(
            db,
            _candidate_uuid_list(session.candidate_poi_ids),
        )
        if strict_destination:
            session_context_pois = filter_pois_to_search_center(
                session_context_pois,
                lat=generation_payload.lat,
                lon=generation_payload.lon,
                radius=generation_payload.radius,
            )

    searched_context_pois = await search_generation_context_with_fallbacks(
        db,
        poi_repository,
        current_user,
        embedding_service,
        query=search_query,
        lat=generation_payload.lat,
        lon=generation_payload.lon,
        radius=generation_payload.radius,
        limit=retrieval_limit,
        strict_destination=strict_destination,
        embedding_cache=embedding_cache,
    )

    context_pois = merge_unique_context_pois(
        session_context_pois,
        searched_context_pois,
        max_pois=retrieval_limit,
    )
    if strict_destination:
        context_pois = filter_pois_to_search_center(
            context_pois,
            lat=generation_payload.lat,
            lon=generation_payload.lon,
            radius=generation_payload.radius,
        )
    context_pois = prepare_context_pois(refined_query, context_pois, retrieval_limit)
    logger.info("Phase: POI search complete session_id=%s total_pois=%d", session_id, len(context_pois))

    if not context_pois:
        scope_label = (destination_scope or {}).get("label")
        detail = (
            f"No encontre datos suficientes directamente en {scope_label}. "
            "Puedes ampliar la busqueda a comunas cercanas o ajustar el tipo de lugares."
            if strict_destination and scope_label
            else (
                "No encontre suficientes lugares para generar una ruta segura con esos datos. "
                "Prueba ampliando el radio o ajustando la ubicacion."
            )
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

    enriched_query = (
        f"Solicitud refinada por conversacion con Ara: {refined_query}\n"
        f"Fechas del viaje: desde {start_date.isoformat()} hasta {end_date.isoformat()}\n"
        f"Ubicacion de referencia: lat={generation_payload.lat}, lon={generation_payload.lon}\n"
        f"Radio maximo: {generation_payload.radius} metros\n"
        f"Duracion: {num_days} dia(s)"
    )
    schedule_guidance = build_schedule_guidance(generation_payload)

    logger.info("Phase: fetching weather session_id=%s", session_id)
    try:
        weather_forecast = await get_forecast(
            generation_payload.lat,
            generation_payload.lon,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather forecast provider failed while generating the itinerary.",
        ) from exc

    _phase_weather = time.monotonic()
    logger.info("Phase: weather ready session_id=%s elapsed=%.2fs", session_id, _phase_weather - _phase_start)

    logger.info("Phase: calling LLM for itinerary generation session_id=%s", session_id)
    await ara_repository.update_session_context(db, session, status="generating")
    await ara_repository.commit_or_rollback(db)

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
    )
    _phase_llm = time.monotonic()
    logger.info("Phase: LLM response received session_id=%s elapsed=%.2fs", session_id, _phase_llm - _phase_weather)

    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)
    generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, generation_payload)
    generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

    logger.info("Phase: validating LLM output session_id=%s steps=%d", session_id, len(generated_itinerary.steps))
    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The LLM returned POIs outside Ara context.")
    if not generated_itinerary.steps:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ara did not return itinerary steps.")

    validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = sanitize_generated_itinerary_context(generated_itinerary)

    logger.info("Phase: saving itinerary session_id=%s", session_id)
    itinerary = await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        generated_itinerary=generated_itinerary,
    )
    logger.info("Itinerary created session_id=%s itinerary_id=%s", session_id, itinerary.id)

    await db.refresh(session, ["preferences_data", "status", "candidate_poi_ids", "generated_itinerary_id"])
    preferences = dict(session.preferences_data or {})
    preferences["conversation_mode"] = "post_generation"
    preferences["active_itinerary_id"] = str(itinerary.id)
    preferences["active_itinerary_poi_ids"] = [str(step.poi_id) for step in itinerary.steps]
    await ara_repository.update_session_context(
        db,
        session,
        status="completed",
        preferences_data=preferences,
        candidate_poi_ids=[],
        generated_itinerary_id=itinerary.id,
    )
    await ara_repository.add_message(
        db,
        session.id,
        "assistant",
        AraMessages.get("session_generation_complete"),
        metadata={"generated_itinerary_id": str(itinerary.id)},
    )
    await ara_repository.commit_or_rollback(db)

    _phase_end = time.monotonic()
    logger.info(
        "Itinerary generation COMPLETE session_id=%s itinerary_id=%s total_elapsed=%.2fs",
        session_id, itinerary.id, _phase_end - _phase_start,
    )

    return AraGenerateItineraryResponse(session_id=session_id, status="completed", itinerary=itinerary)


async def _get_user_for_background_job(db: AsyncSession, user_id: UUID) -> User | None:
    stmt = select(User).options(selectinload(User.tourist_profile)).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def run_ara_itinerary_generation_job(
    session_id: UUID,
    tourist_id: UUID,
    payload: AraGenerateItineraryRequest | None,
) -> None:
    _job_start = time.monotonic()
    logger.info("Background job START session_id=%s tourist_id=%s", session_id, tourist_id)
    async with AsyncSessionLocal() as db:
        current_user = await _get_user_for_background_job(db, tourist_id)
        session = await ara_repository.get_session(db, session_id, tourist_id)
        if current_user is None or session is None:
            logger.warning(
                "Background job: user or session not found session_id=%s tourist_id=%s",
                session_id, tourist_id,
            )
            return

        try:
            await generate_itinerary_from_session(
                session_id=session_id,
                payload=payload,
                db=db,
                current_user=current_user,
                embedding_service=get_embedding_service(),
                llm_service=get_itinerary_generator(),
            )
            logger.info(
                "Background job COMPLETE session_id=%s total_elapsed=%.2fs",
                session_id, time.monotonic() - _job_start,
            )
        except Exception:
            await db.rollback()
            logger.exception("Background job FAILED session_id=%s", session_id)
            session = await ara_repository.get_session(db, session_id, tourist_id)
            if session is None:
                return
            await ara_repository.update_session_context(db, session, status="failed")
            await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                AraMessages.get("session_generation_failed"),
                metadata={"generation_error": True},
            )
            await ara_repository.commit_or_rollback(db)


async def build_step_replacement_context(
    db: AsyncSession,
    current_user: User,
    itinerary_id: UUID,
    step_id: UUID,
) -> tuple[str, object, object] | None:
    itinerary = await itinerary_repository.get_itinerary_by_id(db, itinerary_id, current_user.id)
    if itinerary is None:
        return None
    step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
    if step is None:
        return None
    current_poi = await poi_repository.get_poi_by_id(db, step.poi_id)
    if current_poi is None:
        return None
    return itinerary.title, step, current_poi


async def search_step_replacement_alternatives(
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    message: str,
    current_poi,
    lat: float | None,
    lon: float | None,
    radius: float | None,
) -> list:
    search_lat = lat if lat is not None else current_poi.latitude
    search_lon = lon if lon is not None else current_poi.longitude
    search_radius = radius or 8000
    search_query = (
        f"Buscar alternativa turistica real para reemplazar este POI: {current_poi.name}. "
        f"Descripcion actual: {current_poi.description}. Preferencias del usuario: {message}"
    )
    alternatives = await search_candidate_pois(
        db,
        poi_repository,
        search_query,
        current_user,
        embedding_service,
        lat=search_lat,
        lon=search_lon,
        radius=search_radius,
        limit=15,
    )
    alternatives = filter_blacklisted_context_pois(message, alternatives)
    result = [poi for poi in alternatives if poi.id != current_poi.id][:5]
    return result
