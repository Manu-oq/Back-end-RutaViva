from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date as date_type
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary
from app.schemas.poi import POIResponse
from app.services.ara_response_builder import build_refined_query
from app.services.embedding_service import EmbeddingCache, OpenAIEmbeddingService
from app.services.itinerary_generation_service import (
    build_schedule_guidance,
    filter_blacklisted_context_pois,
    merge_unique_context_pois,
    normalize_generated_itinerary_times,
    prepare_context_pois,
    repair_duplicate_poi_steps,
    repair_invalid_poi_ids,
    repair_latest_start_times,
    repair_lodging_duplicates,
    repair_schedule_and_category_issues,
    sanitize_generated_itinerary_context,
    trip_days,
    validate_generated_itinerary_rules,
)
from app.services.llm_service import ItineraryGenerator
from app.services.poi_search_service import (
    filter_pois_to_search_center,
    search_generation_context_with_fallbacks,
)
from app.services.weather_service import get_forecast

logger = logging.getLogger(__name__)

ara_repository = AraRepository()
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


def _candidate_uuid_list(ids: Any) -> list[UUID]:
    if not ids:
        return []
    return [UUID(str(i)) for i in ids]


def normalize_dates(start: date_type | None, end: date_type | None) -> tuple[date_type, date_type]:
    today = date_type.today()
    if start is None or end is None:
        return today, today
    return start, end


async def generate_itinerary_core(
    session: Any,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
    candidate_pois: list | None = None,
    weather_forecast: str | None = None,
    *,
    on_phase: Callable[[str, dict[str, Any] | None], Awaitable[None]] | None = None,
) -> tuple[Any, list[POIResponse], GenerateItineraryRequest]:
    """
    Core compartido de generacion de itinerarios.

    on_phase(phase_name, extra_data) permite que los wrappers emitan eventos SSE,
    logueen progreso, etc.
    """

    async def _phase(name: str, extra: dict[str, Any] | None = None) -> None:
        if on_phase is not None:
            await on_phase(name, extra)

    # 1. Validar
    await _phase("validating")
    if current_user.tourist_profile is None:
        raise ValueError("Only tourist users can use Ara.")

    embedding_cache = EmbeddingCache(embedding_service)

    preferences_data = session.preferences_data or {}
    trip_draft = preferences_data.get("trip_draft") or {}
    search_center = trip_draft.get("search_center") if isinstance(trip_draft, dict) else {}
    effective_lat = session.lat
    effective_lon = session.lon
    if (effective_lat is None or effective_lon is None) and isinstance(search_center, dict):
        effective_lat = search_center.get("lat")
        effective_lon = search_center.get("lon")

    if effective_lat is None or effective_lon is None:
        raise ValueError(
            "Ara needs a destination/search center before generating an itinerary."
        )

    # 2. Build query
    await _phase("query")
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

    # 3. Search POIs (or use provided candidate_pois)
    await _phase("searching")
    if candidate_pois is not None:
        # Use pre-fetched candidate_pois from conversation flow
        context_pois: list[POIResponse] = []
        existing_ids: set[UUID] = set()
        for cp in candidate_pois:
            if isinstance(cp, POIResponse):
                if cp.id not in existing_ids:
                    context_pois.append(cp)
                    existing_ids.add(cp.id)
            elif isinstance(cp, dict):
                poi_obj = POIResponse(**cp)
                if poi_obj.id not in existing_ids:
                    context_pois.append(poi_obj)
                    existing_ids.add(poi_obj.id)
    else:
        # Full POI search (SSE flow)
        session_context_pois: list[POIResponse] = []
        if session.candidate_poi_ids:
            session_context_pois = await poi_repository.get_pois_by_ids(
                db, _candidate_uuid_list(session.candidate_poi_ids)
            )
            if strict_destination:
                session_context_pois = filter_pois_to_search_center(
                    session_context_pois,
                    lat=generation_payload.lat,
                    lon=generation_payload.lon,
                    radius=generation_payload.radius,
                )

        # Cargar POIs seleccionados por el usuario
        selected_poi_ids = (session.preferences_data or {}).get("selected_poi_ids", [])
        if selected_poi_ids:
            selected_pois = await poi_repository.get_pois_by_ids(
                db, [UUID(str(sid)) for sid in selected_poi_ids]
            )
            selected_ids = {p.id for p in selected_pois}
            session_context_pois = [p for p in selected_pois] + [
                p for p in session_context_pois if p.id not in selected_ids
            ]

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
    await _phase("searching", {"poi_count": len(context_pois)})

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
        raise ValueError(detail)

    # 4. Weather
    await _phase("weather")
    if weather_forecast is None:
        weather_forecast = await get_forecast(
            generation_payload.lat,
            generation_payload.lon,
            start_date=start_date,
            end_date=end_date,
        )

    # 5. Generate
    await _phase("generating")
    enriched_query = (
        f"Solicitud refinada por conversacion con Ara: {refined_query}\n"
        f"Fechas del viaje: desde {start_date.isoformat()} hasta {end_date.isoformat()}\n"
        f"Ubicacion de referencia: lat={generation_payload.lat}, lon={generation_payload.lon}\n"
        f"Radio maximo: {generation_payload.radius} metros\n"
        f"Duracion: {num_days} dia(s)"
    )
    schedule_guidance = build_schedule_guidance(generation_payload)

    await ara_repository.update_session_context(db, session, status="generating")
    await ara_repository.commit_or_rollback(db)

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
    )
    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)

    # 6. Repair
    await _phase("repairing")
    generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, generation_payload)
    generated_itinerary = repair_invalid_poi_ids(generated_itinerary, context_pois)
    generated_itinerary = repair_latest_start_times(generated_itinerary, context_pois)
    generated_itinerary = repair_lodging_duplicates(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

    validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = sanitize_generated_itinerary_context(generated_itinerary)

    # 7. Save
    await _phase("saving")
    itinerary = await itinerary_repository.create_generated_itinerary(
        db,
        current_user.id,
        session.start_date,
        session.end_date,
        generated_itinerary,
    )
    session.generated_itinerary_id = itinerary.id

    return itinerary, context_pois, generation_payload
