from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from app.core.ara_constants import (
    ADVENTURE_TERMS,
    CULTURE_TERMS,
    DAY_ORDINAL_ALIASES,
    DESTINATION_DISPLAY_NAMES,
    FOOD_TERMS,
    KNOWN_DESTINATION_NAMES,
    LODGING_TERMS,
    NATURE_TERMS,
    REST_TERMS,
    SPECIFIC_FOOD_TERMS,
    WEEKDAY_ALIASES,
    WEEKDAY_NAMES,
)
from app.schemas.poi import POIResponse
from app.services.ara_message_normalizer import normalize_message
from app.services.ara_preference_merger import estimate_route_ready_score




def _build_trip_days(
    start_date: date,
    end_date: date,
    existing_days: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_by_date = {
        str(day.get("day_date")): day
        for day in existing_days
        if isinstance(day, dict) and day.get("day_date")
    }
    days: list[dict[str, Any]] = []
    current = start_date
    index = 1
    while current <= end_date:
        day_key = current.isoformat()
        existing = dict(existing_by_date.get(day_key) or {})
        existing["day_index"] = index
        existing["day_date"] = day_key
        existing["day_label"] = f"{WEEKDAY_NAMES[current.weekday()].capitalize()} {current.day:02d}"
        existing["status"] = existing.get("status") or ("in_progress" if index == 1 else "pending")
        existing.setdefault("base_area", None)
        existing.setdefault("lodging", None)
        existing.setdefault("meal_preferences", [])
        existing.setdefault("activity_preferences", [])
        days.append(existing)
        current += timedelta(days=1)
        index += 1
    return days


def _destination_display_name(normalized_name: str) -> str:
    return DESTINATION_DISPLAY_NAMES.get(normalized_name, normalized_name.title())


def _zone_has_origin_marker(normalized: str, zone_key: str) -> bool:
    patterns = (
        rf"\bdesde\s+{re.escape(zone_key)}\b",
        rf"\bde\s+{re.escape(zone_key)}\s+(?:a|hacia|para)\b",
        rf"\bsalgo\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
        rf"\bparto\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
        rf"\bvengo\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
        rf"\bestoy\s+en\s+{re.escape(zone_key)}\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _zone_has_destination_marker(normalized: str, zone_key: str) -> bool:
    patterns = (
        rf"\b(?:a|hacia|para)\s+{re.escape(zone_key)}\b",
        rf"\b(?:ir|viajar|visitar|llegar|quedarme|quedarnos)\s+(?:a|en|por)\s+{re.escape(zone_key)}\b",
        rf"\b(?:zona de|cerca de|en)\s+{re.escape(zone_key)}\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _first_destination_in_text(normalized: str) -> str | None:
    for name in KNOWN_DESTINATION_NAMES:
        normalized_name = normalize_message(name)
        if re.search(rf"\b{re.escape(normalized_name)}\b", normalized):
            return _destination_display_name(normalized_name)
    return None


def detect_destination_zones(message: str) -> list[str]:
    normalized = normalize_message(message)
    found: list[str] = []
    for name in KNOWN_DESTINATION_NAMES:
        normalized_name = normalize_message(name)
        if re.search(rf"\b{re.escape(normalized_name)}\b", normalized):
            display_name = _destination_display_name(normalized_name)
            if display_name not in found:
                found.append(display_name)
    return found


def extract_route_locations(message: str) -> dict[str, list[str]]:
    normalized = normalize_message(message)
    all_zones = detect_destination_zones(message)
    origins: list[str] = []
    destinations: list[str] = []

    for zone in all_zones:
        zone_key = normalize_message(zone)
        if _zone_has_origin_marker(normalized, zone_key):
            origins.append(zone)
        if _zone_has_destination_marker(normalized, zone_key):
            destinations.append(zone)

    if not destinations:
        destinations = [zone for zone in all_zones if zone not in origins]
    else:
        destinations = sorted(set(destinations) | {zone for zone in all_zones if zone not in origins})

    destinations = [zone for zone in destinations if zone not in origins]
    return {"origins": origins, "destinations": destinations}


def _detect_day_index(normalized: str, start_date: date, end_date: date) -> int | None:
    for alias, index in DAY_ORDINAL_ALIASES.items():
        if alias in normalized and 1 <= index <= ((end_date - start_date).days + 1):
            return index

    for weekday_name, weekday_index in WEEKDAY_ALIASES.items():
        if weekday_name not in normalized:
            continue
        current = start_date
        while current <= end_date:
            if current.weekday() == weekday_index:
                return (current - start_date).days + 1
            current += timedelta(days=1)
    return None


def _extract_day_segments(normalized: str, start_date: date, end_date: date) -> list[tuple[int, str]]:
    matches: list[tuple[int, int]] = []
    trip_length = (end_date - start_date).days + 1

    for alias, index in DAY_ORDINAL_ALIASES.items():
        normalized_alias = normalize_message(alias)
        if not 1 <= index <= trip_length:
            continue
        for match in re.finditer(rf"\b{re.escape(normalized_alias)}\b", normalized):
            matches.append((match.start(), index))

    for weekday_name, weekday_index in WEEKDAY_ALIASES.items():
        normalized_weekday = normalize_message(weekday_name)
        current = start_date
        while current <= end_date:
            if current.weekday() == weekday_index:
                day_index = (current - start_date).days + 1
                for match in re.finditer(rf"\b{re.escape(normalized_weekday)}\b", normalized):
                    matches.append((match.start(), day_index))
                break
            current += timedelta(days=1)

    deduped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for position, day_index in sorted(matches):
        key = (position, day_index)
        if key not in seen:
            seen.add(key)
            deduped.append(key)

    segments: list[tuple[int, str]] = []
    for offset, (position, day_index) in enumerate(deduped):
        next_position = deduped[offset + 1][0] if offset + 1 < len(deduped) else len(normalized)
        segments.append((day_index, normalized[position:next_position]))
    return segments


def _contains_structured_entry(values: list[dict[str, Any]], entry: dict[str, Any]) -> bool:
    entry_key = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return any(json.dumps(value, sort_keys=True, ensure_ascii=False) == entry_key for value in values)


def _add_preference_to_trip_draft(
    draft: dict[str, Any],
    entry: dict[str, Any],
    *,
    day_index: int | None,
    bucket: str,
) -> dict[str, Any]:
    updated = dict(draft)
    if day_index is not None:
        trip_days = list(updated.get("trip_days") or [])
        for day in trip_days:
            if int(day.get("day_index") or 0) == day_index:
                values = list(day.get(bucket) or [])
                if not _contains_structured_entry(values, entry):
                    values.append(entry)
                day[bucket] = values
                if bucket == "lodging_preferences" and day.get("lodging") is None:
                    day["lodging"] = {"preference": entry["value"], "poi_id": None, "source": "message"}
                break
        updated["trip_days"] = trip_days
        return updated

    global_preferences = dict(
        updated.get("global_preferences")
        or {"meal_preferences": [], "activity_preferences": [], "lodging_preferences": []}
    )
    values = list(global_preferences.get(bucket) or [])
    if not _contains_structured_entry(values, entry):
        values.append(entry)
    global_preferences[bucket] = values
    updated["global_preferences"] = global_preferences
    return updated


def _add_plan_entry(
    draft: dict[str, Any],
    plan_key: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(draft)
    values = list(updated.get(plan_key) or [])
    if not _contains_structured_entry(values, entry):
        values.append(entry)
    updated[plan_key] = values
    return updated


def _extract_food_preference(normalized: str) -> str:
    has_soup = any(term in normalized for term in ("sopa", "sopas", "sopias", "cazuela"))
    has_meat = any(term in normalized for term in ("carne", "carnes", "asado", "parrilla"))
    if has_soup and has_meat:
        return "sopas/cazuelas o carnes"

    food_options = (
        ("pizza", ("pizza", "pizzeria", "pizzería")),
        ("mariscos", ("marisco", "mariscos", "pescado", "ceviche")),
        ("sopas/cazuelas", ("sopa", "sopas", "sopias", "cazuela")),
        ("carnes", ("carne", "carnes", "asado", "parrilla")),
        ("café", ("cafe", "café", "cafeteria", "cafetería")),
        ("sushi", ("sushi",)),
        ("hamburguesa", ("hamburguesa",)),
        ("comida local", ("comida local", "local", "típica", "tipica")),
    )
    for value, terms in food_options:
        if any(term in normalized for term in terms):
            return value
    return "gastronomía"


def _extract_activity_preference(normalized: str, fallback: str) -> str:
    activity_options = (
        ("playa", ("playa",)),
        ("sendero", ("sendero", "trekking", "caminar")),
        ("mirador", ("mirador", "vista")),
        ("lago", ("lago",)),
        ("volcán", ("volcan", "volcán")),
        ("termas", ("terma", "termas")),
        ("cultura", ("museo", "mapuche", "cultura", "artesania", "artesanía")),
        ("tranquilo", ("tranquilo", "tranquila", "relajo", "descanso")),
    )
    for value, terms in activity_options:
        if any(term in normalized for term in terms):
            return value
    return fallback or "actividad"


def _extract_lodging_preference(normalized: str) -> str:
    lodging_options = (
        ("hostel", ("hostel", "hostal")),
        ("hotel", ("hotel",)),
        ("cabaña", ("cabaña", "cabana")),
        ("camping", ("camping",)),
        ("hospedaje", ("hospedaje", "alojamiento", "dormir")),
    )
    for value, terms in lodging_options:
        if any(term in normalized for term in terms):
            return value
    return "alojamiento"


def _has_weather_override(normalized: str) -> bool:
    has_bad_weather = any(term in normalized for term in ("llueva", "lloviendo", "lluvia", "mal clima", "mal tiempo"))
    has_override = any(term in normalized for term in ("aunque", "igual", "de todas formas", "no importa"))
    return has_bad_weather and has_override


def _apply_base_areas_from_message(
    draft: dict[str, Any],
    normalized: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    updated = dict(draft)
    trip_days = list(updated.get("trip_days") or [])
    day_segments = _extract_day_segments(normalized, start_date, end_date)

    for day_index, segment in day_segments:
        segment_zones = extract_route_locations(segment)["destinations"]
        if not segment_zones:
            continue
        for day in trip_days:
            if int(day.get("day_index") or 0) == day_index:
                day["base_area"] = segment_zones[0]
                break

    updated["trip_days"] = trip_days
    return updated


def _poi_role_from_categories(category_ids: set[int]) -> str:
    if 2 in category_ids:
        return "meal"
    if 4 in category_ids:
        return "lodging"
    if category_ids & {1, 6, 7, 8, 9, 10, 12}:
        return "activity"
    if category_ids & {5, 11, 15}:
        return "activity"
    return "unknown"


def ensure_trip_draft(
    preferences: dict[str, Any],
    *,
    start_date: date,
    end_date: date,
    payload_lat: float | None = None,
    payload_lon: float | None = None,
) -> dict[str, Any]:
    updated = dict(preferences)
    existing = dict(updated.get("trip_draft") or {})
    existing["schema_version"] = 2
    trip_days = _build_trip_days(start_date, end_date, existing.get("trip_days") or [])
    existing["trip_days"] = trip_days
    existing.setdefault("origin_zones", [])
    existing.setdefault("destination_zones", [])
    existing.setdefault(
        "search_center",
        {
            "lat": payload_lat,
            "lon": payload_lon,
            "source": "payload" if payload_lat is not None and payload_lon is not None else "unknown",
            "label": None,
        },
    )
    existing.setdefault(
        "user_current_location",
        {
            "lat": payload_lat,
            "lon": payload_lon,
            "source": "payload" if payload_lat is not None and payload_lon is not None else "unknown",
        },
    )
    existing.setdefault(
        "global_preferences",
        {
            "meal_preferences": [],
            "activity_preferences": [],
            "lodging_preferences": [],
        },
    )
    existing.setdefault("lodging_plan", [])
    existing.setdefault("meal_plan", [])
    existing.setdefault("activity_plan", [])
    existing.setdefault("selected_pois", [])
    existing.setdefault("weather_policy", {"default": "adapt_to_weather", "overrides": []})
    existing.setdefault("current_day_focus", 0)
    existing.setdefault("lodging", None)
    existing.setdefault("lodging_disclaimer_shown", False)
    updated["trip_draft"] = existing
    return updated


def get_current_day(preferences: dict[str, Any]) -> dict[str, Any] | None:
    draft = (preferences.get("trip_draft") or {}) if preferences else {}
    trip_days: list[dict[str, Any]] = draft.get("trip_days") or []
    index = draft.get("current_day_focus", 0)
    if 0 <= index < len(trip_days):
        return trip_days[index]
    return None


def has_lodging(preferences: dict[str, Any]) -> bool:
    draft = (preferences.get("trip_draft") or {}) if preferences else {}
    return bool(draft.get("lodging"))
