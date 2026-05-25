from __future__ import annotations

import copy
from typing import Any

import httpx

from app.core.ara_constants import (
    DESTINATION_REQUEST_PATTERN,
    EXPAND_DESTINATION_TERMS,
    GASTRONOMY_CATEGORY_IDS,
    GASTRONOMY_TEXT_TERMS,
    KNOWN_DESTINATION_CENTERS,
    LODGING_CATEGORY_IDS,
    LODGING_TEXT_TERMS,
    LOCAL_RESULT_WARNING_THRESHOLD,
    MIN_ITINERARY_CONTEXT_POIS,
    NATURE_CATEGORY_IDS,
    NATURE_TEXT_TERMS,
    SERVICE_IN_LOCATION_PATTERN,
    STRICT_DESTINATION_SOURCES,
    CULTURE_CATEGORY_IDS,
    CULTURE_TEXT_TERMS,
)
from app.schemas.ara import AraQuickReply
from app.services.ara_message_normalizer import normalize_message
from app.services.ara_trip_draft_builder import extract_route_locations
from app.services.geo_service import distance_meters
from app.services.geocoding_service import search_places
from app.repositories.poi_repository import POIRepository
from app.services.embedding_service import EmbeddingCache, OpenAIEmbeddingService
from app.services.itinerary_generation_service import merge_unique_context_pois


def wants_expanded_destination_scope(message: str) -> bool:
    normalized = normalize_message(message)
    return any(term in normalized for term in EXPAND_DESTINATION_TERMS)


def is_strict_destination_context(
    search_center_metadata: dict[str, Any],
    message: str,
) -> bool:
    return (
        search_center_metadata.get("source") in STRICT_DESTINATION_SOURCES
        and not wants_expanded_destination_scope(message)
    )


def inherits_strict_destination_context(
    preferences: dict[str, Any],
    search_center_metadata: dict[str, Any],
    message: str,
) -> tuple[bool, dict[str, Any]]:
    if wants_expanded_destination_scope(message):
        return False, search_center_metadata
    if search_center_metadata.get("source") != "payload":
        return False, search_center_metadata

    draft = preferences.get("trip_draft") or {}
    destination_scope = draft.get("destination_scope") or {}
    search_center = draft.get("search_center") or {}
    if not destination_scope.get("strict") or not search_center.get("label"):
        return False, search_center_metadata

    inherited_metadata = {
        **search_center_metadata,
        "source": "inherited_destination",
        "label": search_center.get("label"),
        "detected_zones": [destination_scope.get("label") or search_center.get("label")],
    }
    return True, inherited_metadata


def remember_destination_scope(
    preferences: dict[str, Any],
    *,
    strict_destination: bool,
    search_center_metadata: dict[str, Any],
    local_result_count: int | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(preferences)
    draft = dict(updated.get("trip_draft") or {})
    draft["destination_scope"] = {
        "strict": strict_destination,
        "results_scope": "destination_only" if strict_destination else "expanded_or_payload",
        "source": search_center_metadata.get("source"),
        "label": search_center_metadata.get("label"),
        "local_result_count": local_result_count,
    }
    updated["trip_draft"] = draft
    return updated


def destination_scope_quick_replies(
    search_center_metadata: dict[str, Any],
    *,
    local_result_count: int,
) -> list[AraQuickReply]:
    if search_center_metadata.get("source") not in STRICT_DESTINATION_SOURCES:
        return []
    label = str(search_center_metadata.get("label") or "esta zona")
    if local_result_count >= LOCAL_RESULT_WARNING_THRESHOLD:
        return []
    return [
        AraQuickReply(
            id="ampliar_busqueda_destino",
            label="Ampliar búsqueda",
            value=f"Amplía la búsqueda a comunas cercanas a {label}",
            type="refinement",
        ),
        AraQuickReply(
            id="mantener_destino",
            label=f"Solo {label[:18]}",
            value=f"Mantén la búsqueda solo en {label}",
            type="refinement",
        ),
    ]


def destination_scope_message_suffix(
    search_center_metadata: dict[str, Any],
    *,
    local_result_count: int,
) -> str:
    label = search_center_metadata.get("label")
    if not label or local_result_count >= LOCAL_RESULT_WARNING_THRESHOLD:
        return ""
    if local_result_count == 0:
        return (
            f" No encontré opciones claras directamente en {label} con estos criterios. "
            "Si quieres, puedo ampliar a comunas cercanas."
        )
    return (
        f" Encontré pocas opciones directamente en {label}; las priorizo porque ese fue tu destino. "
        "Si quieres más variedad, puedo ampliar a comunas cercanas."
    )


def filter_pois_to_search_center(
    pois: list,
    *,
    lat: float | None,
    lon: float | None,
    radius: float | None,
) -> list:
    if lat is None or lon is None or radius is None:
        return pois

    filtered = []
    for poi in pois:
        poi_lat = getattr(poi, "latitude", None)
        poi_lon = getattr(poi, "longitude", None)
        if poi_lat is None or poi_lon is None:
            continue
        try:
            distance = distance_meters(float(lat), float(lon), float(poi_lat), float(poi_lon))
        except (TypeError, ValueError):
            continue
        if distance <= float(radius):
            filtered.append(poi)
    return filtered


def looks_like_unknown_destination_request(normalized_message: str) -> bool:
    return (
        bool(DESTINATION_REQUEST_PATTERN.search(normalized_message))
        or bool(SERVICE_IN_LOCATION_PATTERN.search(normalized_message))
        or " cerca de " in normalized_message
        or " zona de " in normalized_message
    )


async def resolve_effective_search_context(
    message: str,
    *,
    fallback_lat: float | None,
    fallback_lon: float | None,
    fallback_radius: float | None,
) -> tuple[float | None, float | None, float | None, dict[str, Any]]:
    route_locations = extract_route_locations(message)
    zones = route_locations["destinations"]
    specific_zones = [zone for zone in zones if zone != "Región de La Araucanía"]
    zones_for_center = specific_zones or zones

    known_centers = [
        (zone, KNOWN_DESTINATION_CENTERS[zone])
        for zone in zones_for_center
        if zone in KNOWN_DESTINATION_CENTERS
    ]
    if known_centers:
        lat = sum(center[0] for _zone, center in known_centers) / len(known_centers)
        lon = sum(center[1] for _zone, center in known_centers) / len(known_centers)
        label = " / ".join(zone for zone, _center in known_centers)
        wants_expansion = wants_expanded_destination_scope(message)
        if len(known_centers) > 1:
            radius = max(fallback_radius or 0, 80_000 if wants_expansion else 35_000)
            source = "expanded_destination_group" if wants_expansion else "detected_destination_group"
        elif known_centers[0][0] == "Región de La Araucanía":
            radius = max(fallback_radius or 0, 120_000)
            source = "detected_region"
        else:
            radius = max(fallback_radius or 0, 60_000 if wants_expansion else 15_000)
            source = "expanded_destination" if wants_expansion else "detected_destination"
        return lat, lon, radius, {"source": source, "label": label, "detected_zones": zones}

    normalized_message = normalize_message(message)
    if looks_like_unknown_destination_request(normalized_message):
        try:
            results = await search_places(query=f"{message}, Región de La Araucanía, Chile", limit=1)
        except httpx.HTTPError:
            results = []
        if results:
            place = results[0]
            return (
                place.latitude,
                place.longitude,
                max(fallback_radius or 0, 15_000),
                {
                    "source": "geocoded_destination",
                    "label": place.display_name,
                    "detected_zones": zones,
                },
            )

    return fallback_lat, fallback_lon, fallback_radius, {
        "source": "payload" if fallback_lat is not None and fallback_lon is not None else "unknown",
        "label": None,
        "detected_zones": zones,
    }


def poi_text(poi: Any) -> str:
    parts = [
        str(getattr(poi, "name", "") or ""),
        str(getattr(poi, "description", "") or ""),
        str(getattr(poi, "opening_hours_text", "") or ""),
    ]
    visit_rules = getattr(poi, "visit_rules", None)
    if isinstance(visit_rules, dict):
        parts.append(str(visit_rules.get("place_type") or ""))
        parts.append(str(visit_rules.get("osm_tags") or ""))
    return " ".join(parts).lower()


def candidate_matches_intent(poi: Any, primary_intent: str, query: str, *, poi_text_cache: dict[int, str] | None = None) -> bool:
    category_ids = set(getattr(poi, "category_ids", []) or [])
    text = poi_text_cache[id(poi)] if poi_text_cache and id(poi) in poi_text_cache else poi_text(poi)
    if primary_intent == "gastronomia":
        return bool(category_ids & GASTRONOMY_CATEGORY_IDS) or any(term in text for term in GASTRONOMY_TEXT_TERMS)
    if primary_intent == "alojamiento":
        return bool(category_ids & LODGING_CATEGORY_IDS) or any(term in text for term in LODGING_TEXT_TERMS)
    if primary_intent == "naturaleza":
        return bool(category_ids & NATURE_CATEGORY_IDS) or any(term in text for term in NATURE_TEXT_TERMS)
    if primary_intent == "cultura":
        return bool(category_ids & CULTURE_CATEGORY_IDS) or any(term in text for term in CULTURE_TEXT_TERMS)
    return True


async def search_candidate_pois(
    db: Any,
    poi_repository: POIRepository,
    payload_query: str,
    current_user: Any,
    embedding_service: OpenAIEmbeddingService | None,
    *,
    lat: float | None,
    lon: float | None,
    radius: float | None = None,
    limit: int = 12,
    embedding_cache: EmbeddingCache | None = None,
) -> list:
    if lat is None or lon is None:
        return []

    if embedding_service is None:
        from app.services.embedding_service import get_embedding_service
        embedding_service = get_embedding_service()

    if embedding_cache is not None:
        query_embedding = await embedding_cache.get_embedding(payload_query)
    else:
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


async def search_generation_context_with_fallbacks(
    db: Any,
    poi_repository: POIRepository,
    current_user: Any,
    embedding_service: OpenAIEmbeddingService,
    *,
    query: str,
    lat: float,
    lon: float,
    radius: float,
    limit: int,
    strict_destination: bool = False,
    embedding_cache: EmbeddingCache | None = None,
) -> list:
    radius_sequence = (radius,) if strict_destination else (radius, 30_000, 60_000, 100_000)
    radii = []
    for candidate_radius in radius_sequence:
        if candidate_radius not in radii:
            radii.append(candidate_radius)

    if embedding_cache is not None:
        query_embedding = await embedding_cache.get_embedding(query)
    else:
        query_embedding = await embedding_service.get_embedding(query)
    gathered = []
    for candidate_radius in radii:
        gathered = merge_unique_context_pois(
            gathered,
            await poi_repository.search_hybrid(
                db,
                lat=lat,
                lon=lon,
                radius_meters=candidate_radius,
                query_embedding=query_embedding,
                user_interests_embedding=current_user.tourist_profile.interests_embedding
                if current_user.tourist_profile
                else None,
                profile_weight=0.1,
                limit=limit,
            ),
            max_pois=limit,
        )
        if len(gathered) >= min(MIN_ITINERARY_CONTEXT_POIS, limit):
            return gathered

    if not strict_destination and len(gathered) < 5:
        fallback_text = "turismo general naturaleza gastronomía cultura descanso La Araucanía"
        if embedding_cache is not None:
            generic_embedding = await embedding_cache.get_embedding(fallback_text)
        else:
            generic_embedding = await embedding_service.get_embedding(fallback_text)
        for candidate_radius in radii:
            gathered = merge_unique_context_pois(
                gathered,
                await poi_repository.search_hybrid(
                    db,
                    lat=lat,
                    lon=lon,
                    radius_meters=candidate_radius,
                    query_embedding=generic_embedding,
                    user_interests_embedding=current_user.tourist_profile.interests_embedding
                    if current_user.tourist_profile
                    else None,
                    profile_weight=0.1,
                    limit=limit,
                ),
                max_pois=limit,
            )
            if len(gathered) >= min(8, limit):
                break

    return gathered
