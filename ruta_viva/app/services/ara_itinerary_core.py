from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date as date_type, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.itinerary_constants import CHILE_TZ
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, GeneratedItineraryStep
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


MEAL_SLOT_LABELS = {
    "breakfast": "Desayuno",
    "desayuno": "Desayuno",
    "lunch": "Almuerzo",
    "almuerzo": "Almuerzo",
    "once": "Once",
    "dinner": "Cena",
    "cena": "Cena",
}

MEAL_SLOT_DEFAULT_TIMES = {
    "Desayuno": time(hour=9),
    "Almuerzo": time(hour=13),
    "Once": time(hour=17),
    "Cena": time(hour=20),
}


def _meal_slot_label(meal_type: Any) -> str:
    return MEAL_SLOT_LABELS.get(str(meal_type or "").lower(), str(meal_type or "Comida").title())


def _parse_meal_slot_time(value: Any, fallback_label: str) -> time:
    if isinstance(value, str):
        try:
            hour, minute = value.split(":", 1)
            return time(hour=int(hour), minute=int(minute[:2]))
        except (ValueError, TypeError):
            pass
    return MEAL_SLOT_DEFAULT_TIMES.get(fallback_label, time(hour=13))


def _generic_meal_step(step_order: int, meal_slot: dict[str, Any], start_date: date_type) -> GeneratedItineraryStep:
    label = _meal_slot_label(meal_slot.get("meal_type"))
    meal_time = _parse_meal_slot_time(meal_slot.get("time"), label)
    arrival_time = datetime.combine(start_date, meal_time, tzinfo=CHILE_TZ)
    ai_context = {
        "is_generic_meal": True,
        "meal_type": str(meal_slot.get("meal_type") or label).lower(),
        "poi_role": "food",
    }
    return GeneratedItineraryStep(
        step_order=step_order,
        poi_id=None,
        name=label,
        is_generic=True,
        lat=None,
        lon=None,
        arrival_time=arrival_time,
        departure_time=arrival_time + timedelta(minutes=60),
        ai_context=ai_context,
    )


def normalize_generic_meal_steps(
    generated_itinerary: GeneratedItinerary,
    meal_slots: list[dict[str, Any]] | None,
    start_date: date_type,
) -> GeneratedItinerary:
    """Normaliza comidas genéricas para que no dependan de POIs reales."""
    existing_labels: set[str] = set()
    for step in generated_itinerary.steps:
        ai_context = dict(step.ai_context or {})
        is_generic_meal = bool(step.is_generic) or bool(ai_context.get("is_generic_meal")) or (
            step.poi_id is None and (step.name or "").lower() in {"desayuno", "almuerzo", "cena", "once"}
        )
        if not is_generic_meal:
            continue

        label = _meal_slot_label(ai_context.get("meal_type") or step.name)
        step.poi_id = None
        step.name = label
        step.is_generic = True
        step.lat = None
        step.lon = None
        ai_context["is_generic_meal"] = True
        ai_context.setdefault("meal_type", label.lower())
        ai_context.setdefault("poi_role", "food")
        step.ai_context = ai_context
        existing_labels.add(label)

    next_order = max((step.step_order for step in generated_itinerary.steps), default=0) + 1
    for meal_slot in meal_slots or []:
        label = _meal_slot_label(meal_slot.get("meal_type"))
        if label in existing_labels:
            continue
        generated_itinerary.steps.append(_generic_meal_step(next_order, meal_slot, start_date))
        existing_labels.add(label)
        next_order += 1

    generated_itinerary.steps.sort(key=lambda step: (step.arrival_time or datetime.max.replace(tzinfo=CHILE_TZ), step.step_order))
    for index, step in enumerate(generated_itinerary.steps, start=1):
        step.step_order = index
    return generated_itinerary

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
    ara_repository: AraRepository,
    itinerary_repository: ItineraryRepository,
    poi_repository: POIRepository,
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
    has_transport = current_user.tourist_profile.has_own_transport if current_user.tourist_profile else False
    profile = "driving" if has_transport else "foot"
    enriched_query = (
        f"Solicitud refinada por conversacion con Ara: {refined_query}\n"
        f"Fechas del viaje: desde {start_date.isoformat()} hasta {end_date.isoformat()}\n"
        f"Ubicacion de referencia: lat={generation_payload.lat}, lon={generation_payload.lon}\n"
        f"Radio maximo: {generation_payload.radius} metros\n"
        f"Duracion: {num_days} dia(s)"
    )
    travel_matrix = await _build_travel_matrix(context_pois, profile, max_pois=15)
    if travel_matrix:
        enriched_query += f"\n\n{travel_matrix}"
    schedule_guidance = build_schedule_guidance(generation_payload)

    await ara_repository.update_session_context(db, session, status="generating")

    meal_slots = [
        s for s in trip_draft.get("slots", [])
        if s.get("type") == "meal"
    ] if isinstance(trip_draft, dict) else []

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
        has_own_transport=has_transport,
        meal_slots=meal_slots if meal_slots else None,
    )
    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)
    generated_itinerary = normalize_generic_meal_steps(generated_itinerary, meal_slots, start_date)

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


async def _build_travel_matrix(
    pois: list[POIResponse],
    profile: str = "driving",
    max_pois: int = 15,
) -> str | None:
    """Calcula y formatea una matriz de tiempos de traslado entre POIs candidatos."""
    if len(pois) < 2:
        return None

    limited = pois[:max_pois]
    coords: list[tuple[float, float]] = []
    names: list[str] = []
    for poi in limited:
        lat = getattr(poi, "latitude", None)
        lon = getattr(poi, "longitude", None)
        if lat is None or lon is None:
            continue
        coords.append((lat, lon))
        names.append(getattr(poi, "name", "Lugar"))

    if len(coords) < 2:
        return None

    try:
        from app.services.osrm_client import get_osrm_client
        client = get_osrm_client()
    except Exception:
        return _haversine_travel_matrix(coords, names, profile)

    matrix = await client.get_table(coords, coords, profile=profile)
    if matrix is None:
        return _haversine_travel_matrix(coords, names, profile)

    lines: list[str] = []
    trip_label = "auto" if profile == "driving" else "pie"
    for i in range(len(names)):
        for j in range(len(names)):
            if i >= j:
                continue
            entry = matrix[i][j]
            km = entry["distance_meters"] / 1000.0
            mins = entry["duration_seconds"] / 60.0
            lines.append(f"  - {names[i]} → {names[j]}: {km:.1f}km, {mins:.0f}min ({trip_label})")

    if not lines:
        return None

    lines.insert(0, "Tiempos de traslado entre POIs sugeridos:")
    return "\n".join(lines)


def _haversine_travel_matrix(
    coords: list[tuple[float, float]],
    names: list[str],
    profile: str = "foot",
) -> str:
    from app.services.geo_service import distance_meters

    speeds = {"driving": 40.0, "foot": 5.0}
    speed_kmh = speeds.get(profile, 5.0)
    trip_label = "auto (estimado)" if profile == "driving" else "pie (estimado)"

    lines: list[str] = []
    for i in range(len(names)):
        for j in range(len(names)):
            if i >= j:
                continue
            lat_a, lon_a = coords[i]
            lat_b, lon_b = coords[j]
            mt = distance_meters(lat_a, lon_a, lat_b, lon_b)
            km = mt / 1000.0
            mins = (km / speed_kmh) * 60.0
            lines.append(f"  - {names[i]} → {names[j]}: {km:.1f}km, {mins:.0f}min ({trip_label})")

    if not lines:
        return ""

    lines.insert(0, "Tiempos de traslado estimados entre POIs sugeridos (Haversine):")
    return "\n".join(lines)
