from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.itinerary_constants import (
    BLACKLIST_TERMS_BY_REASON,
    CHILE_TZ,
    DELEGATED_RECOMMENDATION_TERMS,
    EXPLICIT_CEMETERY_TERMS,
    EXPLICIT_INFORMATION_TERMS,
    EXPLICIT_LODGING_TERMS,
    EXPLICIT_REPEAT_TERMS,
    EXPLICIT_REST_DAY_TERMS,
    EXPLICIT_SERVICE_TERMS,
    EXPLICIT_TRANSPORT_TERMS,
    GASTRONOMY_CATEGORY_ID,
    INFORMATION_CATEGORY_ID,
    LODGING_CATEGORY_ID,
    TRANSPORT_CATEGORY_ID,
)
from app.core.time_utils import to_chile_timezone
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, ItineraryResponse
from app.schemas.poi import POIResponse
from app.services.embedding_service import OpenAIEmbeddingService
from app.services.llm_service import ItineraryGenerator
from app.services.poi_metadata_extractor import WEEKDAY_KEYS, parse_opening_hours_text


NATURE_CATEGORY_IDS_SET = {1, 6, 7, 8, 9, 10, 12}
CULTURE_CATEGORY_IDS_SET = {5, 11, 15}


def trip_days(payload: GenerateItineraryRequest) -> int:
    return (payload.end_date - payload.start_date).days + 1


def asks_for_information(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in EXPLICIT_INFORMATION_TERMS)


def asks_for_lodging(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in EXPLICIT_LODGING_TERMS)


def allows_empty_days(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in EXPLICIT_REST_DAY_TERMS)


def allows_repeated_pois_or_patterns(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in EXPLICIT_REPEAT_TERMS)


def allows_blacklisted_reason(query: str, reason: str) -> bool:
    normalized = query.lower()
    if reason == "cemetery":
        return any(term in normalized for term in EXPLICIT_CEMETERY_TERMS)
    if reason == "pure_transport":
        return any(term in normalized for term in EXPLICIT_TRANSPORT_TERMS)
    if reason == "logistic_service":
        return any(term in normalized for term in EXPLICIT_SERVICE_TERMS)
    return False


def poi_searchable_text(poi: POIResponse) -> str:
    parts = [
        poi.name,
        poi.description,
        json.dumps(poi.multimedia_urls or {}, ensure_ascii=False),
        json.dumps(poi.visit_rules or {}, ensure_ascii=False),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def blacklist_reason_for_poi(poi: POIResponse) -> str | None:
    visit_rules = poi.visit_rules or {}
    if visit_rules.get("blocked_for_itinerary"):
        return str(visit_rules.get("block_reason") or "blocked")

    searchable_text = poi_searchable_text(poi)
    for reason, terms in BLACKLIST_TERMS_BY_REASON.items():
        if any(term in searchable_text for term in terms):
            return reason

    if TRANSPORT_CATEGORY_ID in poi.category_ids and not bool(visit_rules.get("is_primary_experience", True)):
        return "pure_transport"
    if INFORMATION_CATEGORY_ID in poi.category_ids and not bool(visit_rules.get("is_primary_experience", True)):
        return "logistic_service"

    return None


def is_blacklisted_poi_for_query(poi: POIResponse, query: str) -> bool:
    reason = blacklist_reason_for_poi(poi)
    if reason is None:
        return False
    return not allows_blacklisted_reason(query, reason)


def filter_blacklisted_context_pois(query: str, context_pois: list[POIResponse]) -> list[POIResponse]:
    return [poi for poi in context_pois if not is_blacklisted_poi_for_query(poi, query)]


def prepare_context_pois(
    query: str,
    context_pois: list[POIResponse],
    max_pois: int,
) -> list[POIResponse]:
    asks_for_info = asks_for_information(query)
    asks_for_lodging_flag = asks_for_lodging(query)
    context_pois = filter_blacklisted_context_pois(query, context_pois)

    primary_pois = [
        poi
        for poi in context_pois
        if (asks_for_info or INFORMATION_CATEGORY_ID not in poi.category_ids)
        and (asks_for_lodging_flag or LODGING_CATEGORY_ID not in poi.category_ids)
    ]
    fallback_information = [
        poi
        for poi in context_pois
        if not asks_for_info and INFORMATION_CATEGORY_ID in poi.category_ids
    ]
    fallback_lodging = [
        poi
        for poi in context_pois
        if asks_for_lodging_flag and LODGING_CATEGORY_ID in poi.category_ids
    ]
    return (primary_pois + fallback_lodging + fallback_information)[:max_pois]


def merge_unique_context_pois(*poi_groups: list[POIResponse], max_pois: int) -> list[POIResponse]:
    merged: list[POIResponse] = []
    seen_ids: set[UUID] = set()

    for poi_group in poi_groups:
        for poi in poi_group:
            if poi.id in seen_ids:
                continue
            seen_ids.add(poi.id)
            merged.append(poi)
            if len(merged) >= max_pois:
                return merged

    return merged


def build_schedule_guidance(payload: GenerateItineraryRequest) -> str:
    days: list[str] = []
    current_date = payload.start_date
    while current_date <= payload.end_date:
        days.append(
            f"{current_date.isoformat()}: mañana 09:00-13:00, almuerzo/descanso 13:00-14:30, "
            "tarde 14:30-18:00, noche opcional 19:00-21:00 solo para gastronomía, cultura urbana, "
            "termas/bienestar o POIs con night_suitable=true."
        )
        current_date += timedelta(days=1)

    total_trip_days = trip_days(payload)
    density_guidance = (
        "Usa densidad variable por día: normalmente 3-5 pasos diarios si hay suficientes POIs; "
        "Día 1 puede ser más liviano si hay llegada/check-in, días intermedios pueden tener más actividad "
        "y el último día puede ser más liviano. No repitas mecánicamente la misma cantidad de pasos, "
        "las mismas horas ni la misma secuencia de categorías todos los días."
    )

    return (
        "Las fechas oficiales son exclusivamente las del payload: "
        f"{payload.start_date.isoformat()} a {payload.end_date.isoformat()}. "
        "Ignora fechas escritas en lenguaje natural dentro de la consulta si contradicen el payload. "
        "Usa horarios de Chile continental y devuelve ISO-8601 con zona America/Santiago, no UTC/Z. "
        f"El viaje dura {total_trip_days} día(s). Genera pasos distribuidos en los días del viaje. "
        f"{density_guidance} "
        "Evita huecos grandes sin explicación. "
        "No programes actividades outdoor con requires_daylight=true en la noche. "
        "Si faltan datos de horario, usa criterio conservador sin inventar prohibiciones absolutas.\n"
        + "\n".join(days)
    )


def repair_duplicate_poi_steps(
    generated_itinerary: GeneratedItinerary,
    context_pois: list[POIResponse],
    payload: GenerateItineraryRequest,
) -> GeneratedItinerary:
    if allows_repeated_pois_or_patterns(payload.query):
        return generated_itinerary

    poi_by_id = {poi.id: poi for poi in context_pois}
    usable_pois = [
        poi
        for poi in context_pois
        if not is_blacklisted_poi_for_query(poi, payload.query)
        and (asks_for_information(payload.query) or INFORMATION_CATEGORY_ID not in poi.category_ids)
        and (asks_for_lodging(payload.query) or LODGING_CATEGORY_ID not in poi.category_ids)
    ]

    used_ids: set[UUID] = set()
    for step in generated_itinerary.steps:
        if step.poi_id not in used_ids:
            used_ids.add(step.poi_id)
            continue

        repeated_poi = poi_by_id.get(step.poi_id)
        repeated_categories = set(repeated_poi.category_ids if repeated_poi is not None else [])
        available = [poi for poi in usable_pois if poi.id not in used_ids]
        if not available:
            continue

        def replacement_score(candidate: POIResponse) -> tuple[int, float, str]:
            candidate_categories = set(candidate.category_ids)
            category_distance = 0 if repeated_categories & candidate_categories else 1
            distance = candidate.distance_meters if candidate.distance_meters is not None else 999_999_999
            return category_distance, float(distance), candidate.name

        replacement = min(available, key=replacement_score)
        original_poi_id = step.poi_id
        step.poi_id = replacement.id
        used_ids.add(replacement.id)

        ai_context = dict(step.ai_context or {})
        reason_suffix = f"{replacement.name}: {replacement.description[:120]}" if replacement.name else "esta parada"
        ai_context["reason"] = f"Te sugiero {reason_suffix} para aprovechar al máximo este momento del día."
        ai_context["system_repair"] = {
            "type": "duplicate_replacement",
            "original_poi_id": str(original_poi_id),
        }
        step.ai_context = ai_context

    return generated_itinerary


async def generate_itinerary_from_request(
    db: AsyncSession,
    payload: GenerateItineraryRequest,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
    poi_repo: POIRepository,
    itinerary_repo: ItineraryRepository,
    weather_service_module: Any,
) -> ItineraryResponse:
    query_embedding = await embedding_service.get_embedding(payload.query)
    total_days = trip_days(payload)
    retrieval_limit = min(80, max(20, total_days * 12))
    context_pois = await poi_repo.search_hybrid(
        db,
        lat=payload.lat,
        lon=payload.lon,
        radius_meters=payload.radius,
        query_embedding=query_embedding,
        user_interests_embedding=current_user.tourist_profile.interests_embedding,
        limit=retrieval_limit,
    )

    if not context_pois:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No relevant POIs were found for itinerary generation.",
        )

    context_pois = prepare_context_pois(
        query=payload.query,
        context_pois=context_pois,
        max_pois=retrieval_limit,
    )
    if not context_pois:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No itinerary-suitable POIs were found after applying tourism safety filters.",
        )

    enriched_query = (
        f"Solicitud del usuario: {payload.query}\n"
        f"Fechas del viaje: desde {payload.start_date.isoformat()} hasta {payload.end_date.isoformat()}\n"
        f"Ubicación de referencia: lat={payload.lat}, lon={payload.lon}\n"
        f"Radio máximo: {payload.radius} metros\n"
        f"Duración: {total_days} día(s)"
    )
    schedule_guidance = build_schedule_guidance(payload)

    try:
        daily_forecasts = await weather_service_module.get_daily_forecast(
            payload.lat,
            payload.lon,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        weather_forecast = weather_service_module.format_forecast_summary(daily_forecasts)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather forecast provider failed while generating the itinerary.",
        ) from exc

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
    )
    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)
    generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, payload)
    generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, payload)
    generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, payload)

    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The LLM returned POIs outside the provided context.",
        )

    if not generated_itinerary.steps:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The LLM did not return any itinerary steps.",
        )

    validate_generated_itinerary_rules(
        generated_itinerary=generated_itinerary,
        context_pois=context_pois,
        payload=payload,
    )
    generated_itinerary = sanitize_generated_itinerary_context(generated_itinerary)

    forecast_by_date = {f.date: f for f in daily_forecasts}
    for step in generated_itinerary.steps:
        if step.arrival_time is not None:
            step_date = step.arrival_time.astimezone(CHILE_TZ).date() if step.arrival_time.tzinfo else step.arrival_time.date()
            day_forecast = forecast_by_date.get(step_date)
            if day_forecast is not None:
                weather_data = {
                    "description": day_forecast.description,
                    "temperature_c": day_forecast.temperature_c,
                    "precipitation_probability": day_forecast.precipitation_probability,
                }
                if step.ai_context is None:
                    step.ai_context = {}
                step.ai_context["weather"] = weather_data

    return await itinerary_repo.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        generated_itinerary=generated_itinerary,
    )


def parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":", maxsplit=1)
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError):
        return None


def opening_windows_for_step(poi: POIResponse, step_datetime: datetime | None) -> list[tuple[time, time]]:
    if step_datetime is None:
        return []

    visit_rules = poi.visit_rules or {}
    structured = visit_rules.get("opening_hours_structured")
    if not isinstance(structured, dict):
        structured = parse_opening_hours_text(poi.opening_hours_text)
    if not structured:
        return []

    weekday_key = WEEKDAY_KEYS[step_datetime.weekday()]
    windows_payload = structured.get(weekday_key) or []
    windows: list[tuple[time, time]] = []
    for window in windows_payload:
        if not isinstance(window, dict):
            continue
        open_time = parse_hhmm(window.get("open"))
        close_time = parse_hhmm(window.get("close"))
        if open_time is not None and close_time is not None and open_time < close_time:
            windows.append((open_time, close_time))
    return windows


def step_fits_opening_windows(step, poi: POIResponse) -> bool:
    if step.arrival_time is None or step.departure_time is None:
        return True
    visit_rules = poi.visit_rules or {}
    structured = visit_rules.get("opening_hours_structured")
    if not isinstance(structured, dict):
        structured = parse_opening_hours_text(poi.opening_hours_text)
    if not structured:
        return True
    weekday_key = WEEKDAY_KEYS[step.arrival_time.weekday()]
    if weekday_key not in structured:
        return True
    windows_payload = structured[weekday_key]
    if not windows_payload:
        return True
    arrival = step.arrival_time.time()
    departure = step.departure_time.time()
    for window in windows_payload:
        if not isinstance(window, dict):
            continue
        open_time = parse_hhmm(window.get("open"))
        close_time = parse_hhmm(window.get("close"))
        if open_time is not None and close_time is not None and open_time < close_time:
            if open_time <= arrival and departure <= close_time:
                return True
    return False


def primary_category_id(poi: POIResponse | None) -> int | None:
    if poi is None or not poi.category_ids:
        return None
    category_ids = set(poi.category_ids)
    if GASTRONOMY_CATEGORY_ID in category_ids:
        return GASTRONOMY_CATEGORY_ID
    if LODGING_CATEGORY_ID in category_ids:
        return LODGING_CATEGORY_ID
    if category_ids & NATURE_CATEGORY_IDS_SET:
        return next(iter(category_ids & NATURE_CATEGORY_IDS_SET))
    if category_ids & CULTURE_CATEGORY_IDS_SET:
        return next(iter(category_ids & CULTURE_CATEGORY_IDS_SET))
    return poi.category_ids[0]


def is_gastronomy(poi: POIResponse | None) -> bool:
    return poi is not None and GASTRONOMY_CATEGORY_ID in poi.category_ids


def preferred_time_for_gastronomy(value: datetime | None) -> bool:
    if value is None:
        return False
    return time(hour=11, minute=30) <= value.time() <= time(hour=15) or time(hour=19) <= value.time() <= time(hour=21)


def candidate_is_usable_for_slot(candidate: POIResponse, step, payload: GenerateItineraryRequest) -> bool:
    if is_blacklisted_poi_for_query(candidate, payload.query):
        return False
    return step_fits_opening_windows(step, candidate)


def replace_step_poi(
    step,
    replacement: POIResponse,
    *,
    repair_type: str,
    original_poi_id: UUID,
) -> None:
    step.poi_id = replacement.id
    ai_context = dict(step.ai_context or {})
    reason_suffix = f"{replacement.name}: {replacement.description[:120]}" if replacement.name else "esta parada"
    ai_context["reason"] = f"Te sugiero {reason_suffix} para aprovechar al máximo este momento del día."
    ai_context["system_repair"] = {
        "type": repair_type,
        "original_poi_id": str(original_poi_id),
    }
    step.ai_context = ai_context


def repair_schedule_and_category_issues(
    generated_itinerary: GeneratedItinerary,
    context_pois: list[POIResponse],
    payload: GenerateItineraryRequest,
) -> GeneratedItinerary:
    poi_by_id = {poi.id: poi for poi in context_pois}
    used_ids = {step.poi_id for step in generated_itinerary.steps}
    repaired_steps = list(generated_itinerary.steps)

    for step in repaired_steps:
        poi = poi_by_id.get(step.poi_id)
        if poi is None or step_fits_opening_windows(step, poi):
            continue

        original_poi_id = step.poi_id
        replacement = next(
            (
                candidate
                for candidate in context_pois
                if candidate.id not in used_ids
                and candidate_is_usable_for_slot(candidate, step, payload)
            ),
            None,
        )
        if replacement is not None:
            replace_step_poi(step, replacement, repair_type="closed_poi_replacement", original_poi_id=original_poi_id)
            used_ids.add(replacement.id)
            continue

        windows = opening_windows_for_step(poi, step.arrival_time)
        if windows and step.arrival_time is not None and step.departure_time is not None:
            duration = step.departure_time - step.arrival_time
            for open_time, close_time in windows:
                candidate_start = datetime.combine(step.arrival_time.date(), open_time, tzinfo=step.arrival_time.tzinfo)
                candidate_end = candidate_start + duration
                close_dt = datetime.combine(step.arrival_time.date(), close_time, tzinfo=step.arrival_time.tzinfo)
                if candidate_end <= close_dt:
                    step.arrival_time = candidate_start
                    step.departure_time = candidate_end
                    ai_context = dict(step.ai_context or {})
                    ai_context["reason"] = "Ajusté esta parada para respetar el horario informado del lugar."
                    ai_context["system_repair"] = {"type": "opening_hours_shift"}
                    step.ai_context = ai_context
                    break

    steps_by_date: dict[date, list] = {}
    for step in repaired_steps:
        if step.arrival_time is not None:
            steps_by_date.setdefault(step.arrival_time.date(), []).append(step)

    for day_steps in steps_by_date.values():
        ordered = sorted(day_steps, key=lambda item: item.arrival_time)
        gastronomy_seen = 0
        consecutive_category_counts: Counter[int] = Counter()
        previous_primary_category: int | None = None
        for step in ordered:
            poi = poi_by_id.get(step.poi_id)
            primary_category = primary_category_id(poi)
            if primary_category == previous_primary_category and primary_category is not None:
                consecutive_category_counts[primary_category] += 1
            else:
                consecutive_category_counts = Counter()
                if primary_category is not None:
                    consecutive_category_counts[primary_category] = 1
            previous_primary_category = primary_category

            should_replace_gastro = is_gastronomy(poi) and (
                not preferred_time_for_gastronomy(step.arrival_time) or gastronomy_seen >= 2
            )
            should_replace_repeated_category = (
                primary_category is not None and consecutive_category_counts[primary_category] > 2
            )
            if not should_replace_gastro and not should_replace_repeated_category:
                if is_gastronomy(poi):
                    gastronomy_seen += 1
                continue

            original_poi_id = step.poi_id
            replacement = next(
                (
                    candidate
                    for candidate in context_pois
                    if candidate.id not in used_ids
                    and not is_gastronomy(candidate)
                    and (primary_category is None or primary_category not in candidate.category_ids)
                    and candidate_is_usable_for_slot(candidate, step, payload)
                ),
                None,
            )
            if replacement is not None:
                replace_step_poi(
                    step,
                    replacement,
                    repair_type="category_saturation_replacement",
                    original_poi_id=original_poi_id,
                )
                used_ids.add(replacement.id)
            elif should_replace_gastro and gastronomy_seen >= 2:
                fallback_replacement = next(
                    (
                        candidate
                        for candidate in context_pois
                        if candidate.id not in used_ids
                        and candidate.id != step.poi_id
                        and candidate_is_usable_for_slot(candidate, step, payload)
                    ),
                    None,
                )
                if fallback_replacement is not None:
                    replace_step_poi(
                        step,
                        fallback_replacement,
                        repair_type="category_saturation_fallback",
                        original_poi_id=original_poi_id,
                    )
                    used_ids.add(fallback_replacement.id)
                else:
                    generated_itinerary.steps = [candidate for candidate in generated_itinerary.steps if candidate is not step]

    return generated_itinerary


def validate_generated_itinerary_rules(
    generated_itinerary: GeneratedItinerary,
    context_pois: list,
    payload: GenerateItineraryRequest,
) -> None:
    poi_by_id = {poi.id: poi for poi in context_pois}
    explicit_information_request = asks_for_information(payload.query)
    explicit_lodging_request = asks_for_lodging(payload.query)
    allow_repetition = allows_repeated_pois_or_patterns(payload.query)

    steps_by_date: dict[date, list] = {}
    lodging_steps_by_date: dict[date, list] = {}
    poi_counts: Counter[UUID] = Counter()
    for step in generated_itinerary.steps:
        poi = poi_by_id.get(step.poi_id)
        if poi is None:
            continue
        poi_counts[step.poi_id] += 1

        blacklist_reason = blacklist_reason_for_poi(poi)
        if blacklist_reason is not None and not allows_blacklisted_reason(payload.query, blacklist_reason):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"The LLM selected a blacklisted POI for itinerary generation: {blacklist_reason}.",
            )

        if INFORMATION_CATEGORY_ID in poi.category_ids and not explicit_information_request:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM selected an information/office POI as a main stop without explicit user intent.",
            )

        if LODGING_CATEGORY_ID in poi.category_ids:
            if not explicit_lodging_request:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The LLM selected a lodging POI as a tourist stop without explicit lodging intent.",
                )
            if step.arrival_time is not None:
                lodging_steps_by_date.setdefault(step.arrival_time.date(), []).append(step)

        if step.arrival_time is None or step.departure_time is None:
            continue

        if step.arrival_time.date() < payload.start_date or step.arrival_time.date() > payload.end_date:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary step outside the requested date range.",
            )
        if step.departure_time.date() < payload.start_date or step.departure_time.date() > payload.end_date:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary departure_time outside the requested date range.",
            )
        steps_by_date.setdefault(step.arrival_time.date(), []).append(step)

        if step.departure_time <= step.arrival_time:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary step with invalid time ordering.",
            )

        visit_rules = poi.visit_rules or {}
        night_suitable = bool(visit_rules.get("night_suitable"))
        latest_start = parse_hhmm(visit_rules.get("latest_recommended_start_time"))
        requires_daylight = bool(visit_rules.get("requires_daylight"))

        if not step_fits_opening_windows(step, poi):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM scheduled a POI outside its confirmed opening hours.",
            )

        if latest_start is not None and not night_suitable:
            if step.arrival_time.time() > latest_start:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The LLM scheduled a POI after its latest recommended start time.",
                )

        if requires_daylight and not night_suitable:
            if step.arrival_time.time() >= time(hour=18):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The LLM scheduled a daylight-only outdoor POI too late in the day.",
                )

    max_unexplained_gap = timedelta(hours=2, minutes=30)
    for day_steps in steps_by_date.values():
        ordered_steps = sorted(
            [step for step in day_steps if step.arrival_time is not None and step.departure_time is not None],
            key=lambda step: step.arrival_time,
        )
        for previous, current in zip(ordered_steps, ordered_steps[1:], strict=False):
            gap = current.arrival_time - previous.departure_time
            if gap > max_unexplained_gap and previous.departure_time.time() < time(hour=18):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The LLM returned an itinerary with a large unexplained daytime gap.",
                )

    for lodging_steps in lodging_steps_by_date.values():
        if len(lodging_steps) > 1:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned more than one lodging stop in the same day.",
            )

    for day_steps in steps_by_date.values():
        ordered_steps = sorted(day_steps, key=lambda item: item.arrival_time)
        consecutive_same_category = 0
        previous_category: int | None = None
        gastronomy_count = 0
        for step in ordered_steps:
            poi = poi_by_id.get(step.poi_id)
            primary_category = primary_category_id(poi)
            if primary_category == previous_category and primary_category is not None:
                consecutive_same_category += 1
            else:
                consecutive_same_category = 1
            previous_category = primary_category

            if consecutive_same_category > 2:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The LLM saturated a day with too many consecutive POIs from the same category.",
                )

            if is_gastronomy(poi):
                gastronomy_count += 1
                if gastronomy_count > 2 and not allows_repeated_pois_or_patterns(payload.query):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="The LLM saturated a day with too many gastronomy stops.",
                    )

    if not allow_repetition:
        repeated_poi_ids = [str(poi_id) for poi_id, count in poi_counts.items() if count > 1]
        if repeated_poi_ids:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM repeated the same POI across itinerary steps: " + ", ".join(repeated_poi_ids),
            )

        day_category_sequences: dict[date, tuple[tuple[int, ...], ...]] = {}
        day_schedule_signatures: dict[date, tuple[tuple[str, str, tuple[int, ...]], ...]] = {}
        for day, day_steps in steps_by_date.items():
            ordered_steps = sorted(day_steps, key=lambda item: item.arrival_time)
            category_sequence: list[tuple[int, ...]] = []
            schedule_signature: list[tuple[str, str, tuple[int, ...]]] = []
            for step in ordered_steps:
                poi = poi_by_id.get(step.poi_id)
                if poi is None:
                    continue
                category_signature = tuple(sorted(poi.category_ids))
                category_sequence.append(category_signature)
                schedule_signature.append(
                    (
                        step.arrival_time.strftime("%H:%M"),
                        step.departure_time.strftime("%H:%M"),
                        category_signature,
                    )
                )

            if category_sequence:
                day_category_sequences[day] = tuple(category_sequence)
            if schedule_signature:
                day_schedule_signatures[day] = tuple(schedule_signature)

    total_trip_days = trip_days(payload)
    if total_trip_days > 1 and len(generated_itinerary.steps) >= total_trip_days and not allows_empty_days(payload.query):
        expected_dates = {payload.start_date + timedelta(days=offset) for offset in range(total_trip_days)}
        missing_dates = sorted(expected_dates - set(steps_by_date.keys()))
        if missing_dates:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "The LLM left one or more requested trip days without itinerary steps: "
                    + ", ".join(day.isoformat() for day in missing_dates)
                ),
            )


def normalize_generated_itinerary_times(
    generated_itinerary: GeneratedItinerary,
    payload: GenerateItineraryRequest,
) -> GeneratedItinerary:
    for step in generated_itinerary.steps:
        step.arrival_time = to_chile_timezone(step.arrival_time)
        step.departure_time = to_chile_timezone(step.departure_time)

    return generated_itinerary


def sanitize_generated_itinerary_context(generated_itinerary: GeneratedItinerary) -> GeneratedItinerary:
    for step in generated_itinerary.steps:
        if not step.ai_context:
            continue

        for field in ("reason", "tips"):
            value = step.ai_context.get(field)
            if not isinstance(value, str):
                continue
            normalized = value.lower()
            if any(term in normalized for term in DELEGATED_RECOMMENDATION_TERMS):
                step.ai_context[field] = (
                    "Planifica esta parada con anticipación, revisa horarios disponibles y considera el traslado "
                    "desde la parada anterior."
                )
            elif "system_repair" in (step.ai_context or {}) and field == "reason":
                original = step.ai_context.get(field, "")
                if isinstance(original, str) and len(original) < 60:
                    step.ai_context[field] = (
                        "Planifica esta parada con anticipación, revisa horarios disponibles y considera el traslado "
                        "desde la parada anterior."
                    )

    return generated_itinerary
