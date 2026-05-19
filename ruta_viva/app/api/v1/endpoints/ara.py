from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.api.v1.endpoints.itineraries import (
    _build_schedule_guidance,
    _filter_blacklisted_context_pois,
    _merge_unique_context_pois,
    _normalize_generated_itinerary_times,
    _prepare_context_pois,
    _repair_duplicate_poi_steps,
    _repair_schedule_and_category_issues,
    _sanitize_generated_itinerary_context,
    _trip_days,
    _validate_generated_itinerary_rules,
)
from app.db.session import AsyncSessionLocal, get_db
from app.models.ara_message import AraMessage
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import (
    AraGenerateItineraryAcceptedResponse,
    AraGenerateItineraryRequest,
    AraGenerateItineraryResponse,
    AraGenerationStatusResponse,
    AraMessageCreate,
    AraMessageResponse,
    AraMessagesResponse,
    AraQuickReply,
    AraSessionCreate,
    AraSessionResponse,
)
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, ItineraryStepUpdate
from app.services.ara_chat_service import AraChatService, get_ara_chat_service
from app.services.ara_service import AraConversationService, get_ara_conversation_service
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.geocoding_service import search_places
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
from app.services.weather_service import get_forecast

router = APIRouter(tags=["ara"])
ara_repository = AraRepository()
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()

GASTRONOMY_CATEGORY_IDS = {2}
LODGING_CATEGORY_IDS = {4}
NATURE_CATEGORY_IDS = {1, 6, 7, 8, 9, 10, 12}
CULTURE_CATEGORY_IDS = {5, 11, 15}

GASTRONOMY_TEXT_TERMS = {
    "restaurant",
    "restaurante",
    "pizzeria",
    "pizzería",
    "pizza",
    "cafe",
    "café",
    "comida",
    "cocina",
    "bar",
    "pub",
    "empanada",
    "sushi",
    "marisco",
    "sopa",
    "sopas",
    "cazuela",
    "carne",
    "carnes",
    "picada",
    "pasteleria",
    "pastelería",
}
LODGING_TEXT_TERMS = {"hotel", "hostal", "hostel", "cabaña", "cabana", "alojamiento", "hospedaje", "camping"}
NATURE_TEXT_TERMS = {"sendero", "trekking", "mirador", "lago", "volcan", "volcán", "parque", "cascada", "terma"}
CULTURE_TEXT_TERMS = {"museo", "patrimonio", "mapuche", "artesania", "artesanía", "historia", "feria"}
KNOWN_DESTINATION_CENTERS = {
    "Pucón": (-39.2820, -71.9545),
    "Villarrica": (-39.2857, -72.2279),
    "Lican Ray": (-39.4889, -72.1558),
    "Caburgua": (-39.1669, -71.7817),
    "Curarrehue": (-39.3581, -71.5887),
    "Temuco": (-38.7359, -72.5904),
    "Melipeuco": (-38.8519, -71.6913),
    "Parque Nacional Conguillío": (-38.6500, -71.6500),
    "Malalcahuello": (-38.4702, -71.5700),
    "Lonquimay": (-38.4333, -71.2333),
    "Angol": (-37.7952, -72.7164),
    "Freire": (-38.9525, -72.6265),
    "Padre Las Casas": (-38.7667, -72.6000),
    "Nueva Imperial": (-38.7445, -72.9507),
    "Carahue": (-38.7118, -73.1610),
    "Saavedra": (-38.7833, -73.4000),
    "Puerto Saavedra": (-38.7833, -73.4000),
    "Teodoro Schmidt": (-38.9961, -73.0892),
    "Toltén": (-39.2167, -73.2167),
    "Gorbea": (-39.1010, -72.6741),
    "Pitrufquén": (-38.9864, -72.6372),
    "Loncoche": (-39.3671, -72.6303),
    "Lautaro": (-38.5307, -72.4365),
    "Perquenco": (-38.4167, -72.3833),
    "Galvarino": (-38.4088, -72.7827),
    "Cholchol": (-38.6018, -72.8457),
    "Vilcún": (-38.6689, -72.2244),
    "Cunco": (-38.9329, -72.0270),
    "Curacautín": (-38.4390, -71.8891),
    "Victoria": (-38.2329, -72.3329),
    "Traiguén": (-38.2500, -72.6833),
    "Lumaco": (-38.1500, -72.9167),
    "Purén": (-38.0314, -73.0711),
    "Renaico": (-37.6727, -72.5888),
    "Ercilla": (-38.0583, -72.3769),
    "Collipulli": (-37.9545, -72.4344),
    "Los Sauces": (-37.9776, -72.8353),
    "Región de La Araucanía": (-38.7400, -72.1000),
}
STRICT_DESTINATION_SOURCES = {
    "detected_destination",
    "detected_destination_group",
    "geocoded_destination",
    "inherited_destination",
}
EXPAND_DESTINATION_TERMS = (
    "ampliar",
    "amplia",
    "amplía",
    "alrededores",
    "cerca de",
    "comunas cercanas",
    "zonas cercanas",
    "me puedo mover",
    "puedo moverme",
    "no importa moverme",
    "fuera de",
)
LOCAL_RESULT_WARNING_THRESHOLD = 3
MIN_ITINERARY_CONTEXT_POIS = 5

DESTINATION_REQUEST_PATTERN = re.compile(
    r"\b(?:voy|vamos|viajo|viajar|ir|iremos|quedarme|alojarme|estar[eé]?|estoy)\s+(?:a|en)\s+"
)
SERVICE_IN_LOCATION_PATTERN = re.compile(
    r"\b(?:restaurantes?|hoteles?|hostales?|alojamientos?|lugares|panoramas|comida|caf[eé]s?)\s+en\s+"
)


def _ensure_tourist(current_user: User) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")


def _normalize_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    normalized_start = start_date or date.today()
    normalized_end = end_date or normalized_start
    return normalized_start, normalized_end


def _wants_expanded_destination_scope(message: str, ara_service: AraConversationService) -> bool:
    normalized = ara_service.normalize_message(message)
    return any(term in normalized for term in EXPAND_DESTINATION_TERMS)


def _is_strict_destination_context(
    search_center_metadata: dict[str, Any],
    message: str,
    ara_service: AraConversationService,
) -> bool:
    return (
        search_center_metadata.get("source") in STRICT_DESTINATION_SOURCES
        and not _wants_expanded_destination_scope(message, ara_service)
    )


def _inherits_strict_destination_context(
    preferences: dict[str, Any],
    search_center_metadata: dict[str, Any],
    message: str,
    ara_service: AraConversationService,
) -> tuple[bool, dict[str, Any]]:
    if _wants_expanded_destination_scope(message, ara_service):
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


def _remember_destination_scope(
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


def _destination_scope_quick_replies(
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


def _destination_scope_message_suffix(
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


def _distance_meters(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Return approximate haversine distance in meters between two WGS84 points."""
    earth_radius_m = 6_371_000
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lon_b - lon_a)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _filter_pois_to_search_center(
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
            distance = _distance_meters(float(lat), float(lon), float(poi_lat), float(poi_lon))
        except (TypeError, ValueError):
            continue
        if distance <= float(radius):
            filtered.append(poi)
    return filtered


def _looks_like_unknown_destination_request(normalized_message: str) -> bool:
    return (
        bool(DESTINATION_REQUEST_PATTERN.search(normalized_message))
        or bool(SERVICE_IN_LOCATION_PATTERN.search(normalized_message))
        or " cerca de " in normalized_message
        or " zona de " in normalized_message
    )


async def _resolve_effective_search_context(
    message: str,
    ara_service: AraConversationService,
    *,
    fallback_lat: float | None,
    fallback_lon: float | None,
    fallback_radius: float | None,
) -> tuple[float | None, float | None, float | None, dict[str, Any]]:
    route_locations = ara_service.extract_route_locations(message)
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
        wants_expansion = _wants_expanded_destination_scope(message, ara_service)
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

    # Fallback controlado: solo intentar geocoding si el mensaje parece hablar
    # explícitamente de destino. Si falla, mantenemos payload/session.
    normalized_message = ara_service.normalize_message(message)
    if _looks_like_unknown_destination_request(normalized_message):
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


def _poi_text(poi: Any) -> str:
    parts = [
        str(getattr(poi, "nombre", "") or ""),
        str(getattr(poi, "descripcion", "") or ""),
        str(getattr(poi, "opening_hours_text", "") or ""),
    ]
    visit_rules = getattr(poi, "visit_rules", None)
    if isinstance(visit_rules, dict):
        parts.append(str(visit_rules.get("place_type") or ""))
        parts.append(str(visit_rules.get("osm_tags") or ""))
    return " ".join(parts).lower()


def _candidate_matches_intent(poi: Any, primary_intent: str, query: str) -> bool:
    category_ids = set(getattr(poi, "category_ids", []) or [])
    text = _poi_text(poi)
    if primary_intent == "gastronomia":
        return bool(category_ids & GASTRONOMY_CATEGORY_IDS) or any(term in text for term in GASTRONOMY_TEXT_TERMS)
    if primary_intent == "alojamiento":
        return bool(category_ids & LODGING_CATEGORY_IDS) or any(term in text for term in LODGING_TEXT_TERMS)
    if primary_intent == "naturaleza":
        return bool(category_ids & NATURE_CATEGORY_IDS) or any(term in text for term in NATURE_TEXT_TERMS)
    if primary_intent == "cultura":
        return bool(category_ids & CULTURE_CATEGORY_IDS) or any(term in text for term in CULTURE_TEXT_TERMS)
    return True


def _align_candidate_pois_with_intent(
    candidate_pois: list, intent: dict[str, Any], query: str, *, completed_dimensions: set | None = None
) -> list:
    primary_intent = str(intent.get("primary_intent") or "exploracion")
    completed = completed_dimensions or set()
    normalized_query = query.lower()

    explicit_current_intent = (
        primary_intent == "gastronomia"
        and any(term in normalized_query for term in GASTRONOMY_TEXT_TERMS | {"almorzar", "cenar", "restaurantes"})
    ) or (
        primary_intent == "alojamiento"
        and any(term in normalized_query for term in LODGING_TEXT_TERMS)
    ) or (
        primary_intent == "naturaleza"
        and any(term in normalized_query for term in NATURE_TEXT_TERMS)
    ) or (
        primary_intent == "cultura"
        and any(term in normalized_query for term in CULTURE_TEXT_TERMS)
    )

    if primary_intent in completed and not explicit_current_intent:
        return candidate_pois
    if primary_intent not in {"gastronomia", "alojamiento", "naturaleza", "cultura"}:
        return candidate_pois

    if primary_intent == "gastronomia":
        specific_food_terms = {
            "pizza": {"pizza", "pizzeria", "pizzería"},
            "cafe": {"cafe", "café", "cafeteria", "cafetería"},
            "marisco": {"marisco", "pescado", "ceviche"},
            "sopa": {"sopa", "sopas", "sopias", "cazuela"},
            "carne": {"carne", "carnes", "asado", "parrilla"},
            "sushi": {"sushi"},
        }
        for _label, terms in specific_food_terms.items():
            if any(term in normalized_query for term in terms):
                specific_matches = [poi for poi in candidate_pois if any(term in _poi_text(poi) for term in terms)]
                if specific_matches:
                    return specific_matches

    aligned = [poi for poi in candidate_pois if _candidate_matches_intent(poi, primary_intent, query)]
    if aligned:
        return aligned

    # Para comida/alojamiento es preferible mostrar cero tarjetas antes que
    # mezclar senderos o miradores como candidato principal de un turno
    # semánticamente incompatible.
    if primary_intent in {"gastronomia", "alojamiento"}:
        return []
    return candidate_pois


def _exclude_selected_candidate_pois(candidate_pois: list, preferences: dict[str, Any]) -> list:
    excluded_ids = {str(value) for value in preferences.get("selected_poi_ids", [])}
    if preferences.get("last_selected_poi_id"):
        excluded_ids.add(str(preferences["last_selected_poi_id"]))
    if preferences.get("active_itinerary_poi_ids"):
        excluded_ids.update(str(value) for value in preferences.get("active_itinerary_poi_ids", []))
    if not excluded_ids:
        return candidate_pois
    return [poi for poi in candidate_pois if str(getattr(poi, "id", "")) not in excluded_ids]


def _finalize_candidate_pois(candidate_pois: list, *, intent: dict[str, Any], preferences: dict[str, Any], query: str) -> list:
    if preferences.get("surprise_route_requested"):
        return _exclude_selected_candidate_pois(candidate_pois, preferences)[:8]
    completed = set(preferences.get("completed_dimensions") or [])
    aligned = _align_candidate_pois_with_intent(candidate_pois, intent, query, completed_dimensions=completed)
    return _exclude_selected_candidate_pois(aligned, preferences)[:8]


async def _maybe_diversify_candidate_pois(
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    base_query: str,
    candidate_pois: list,
    preferences: dict,
    intent: dict[str, Any] | None = None,
    lat: float | None,
    lon: float | None,
    radius: float | None,
):
    primary_intent = str((intent or {}).get("primary_intent") or "exploracion")
    completed_dimensions = set(preferences.get("completed_dimensions") or [])
    category_already_covered = primary_intent in completed_dimensions
    surprise = preferences.get("surprise_route_requested")

    if primary_intent in {"gastronomia", "alojamiento"} and not surprise and not category_already_covered:
        return candidate_pois
    if not surprise and primary_intent not in {"exploracion", "general"} and not category_already_covered:
        return candidate_pois

    if "gastronomia" not in completed_dimensions and not surprise and not category_already_covered:
        return candidate_pois
    diversification_query = (
        f"{base_query}. Para equilibrar el viaje, buscar también naturaleza, miradores, cultura, "
        "actividades suaves y descanso. No limitar la conversación solo a restaurantes o comida."
    )
    diversified = await _search_candidate_pois(
        db,
        diversification_query,
        current_user,
        embedding_service,
        lat=lat,
        lon=lon,
        radius=radius,
        limit=12,
    )
    diversified = _filter_blacklisted_context_pois(diversification_query, diversified)
    return _merge_unique_context_pois(candidate_pois, diversified, max_pois=12)


async def _build_step_replacement_context(
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

    itinerary_pois = await itinerary_repository.list_pois_for_itinerary(db, itinerary_id, current_user.id)
    if itinerary_pois is None:
        return None

    current_poi = next((poi for poi in itinerary_pois if poi.id == step.poi_id), None)
    if current_poi is None:
        current_poi = await poi_repository.get_poi_by_id(db, step.poi_id)
    if current_poi is None:
        return None

    return itinerary.title, step, current_poi


async def _search_step_replacement_alternatives(
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    message: str,
    current_poi,
    lat: float | None,
    lon: float | None,
    radius: float | None,
):
    search_lat = lat if lat is not None else current_poi.latitude
    search_lon = lon if lon is not None else current_poi.longitude
    search_radius = radius or 8000
    search_query = (
        f"Buscar alternativa turística real para reemplazar este POI: {current_poi.nombre}. "
        f"Descripción actual: {current_poi.descripcion}. Preferencias del usuario: {message}"
    )
    alternatives = await _search_candidate_pois(
        db,
        search_query,
        current_user,
        embedding_service,
        lat=search_lat,
        lon=search_lon,
        radius=search_radius,
        limit=15,
    )
    alternatives = _filter_blacklisted_context_pois(message, alternatives)
    return [poi for poi in alternatives if poi.id != current_poi.id][:5]


def _extract_replacement_request_from_metadata(metadata: dict | None) -> dict[str, UUID] | None:
    if not metadata or metadata.get("intent") != "change_itinerary_step":
        return None

    try:
        return {
            "itinerary_id": UUID(str(metadata["itinerary_id"])),
            "step_id": UUID(str(metadata["step_id"])),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="metadata.itinerary_id and metadata.step_id must be valid UUIDs for change_itinerary_step.",
        ) from exc


def _session_message_response(message: AraMessage) -> AraMessageResponse:
    return ara_repository.to_message_response(message)


async def _load_active_itinerary_from_preferences(
    db: AsyncSession,
    current_user: User,
    preferences: dict,
):
    itinerary_id_value = preferences.get("active_itinerary_id") or preferences.get("generated_itinerary_id")
    if itinerary_id_value is None:
        return None
    try:
        itinerary_id = UUID(str(itinerary_id_value))
    except (TypeError, ValueError):
        return None
    return await itinerary_repository.get_itinerary_by_id(db, itinerary_id, current_user.id)


async def _search_generation_context_with_fallbacks(
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    query: str,
    lat: float,
    lon: float,
    radius: float,
    limit: int,
    strict_destination: bool = False,
):
    radius_sequence = (radius,) if strict_destination else (radius, 30_000, 60_000, 100_000)
    radii = []
    for candidate_radius in radius_sequence:
        if candidate_radius not in radii:
            radii.append(candidate_radius)

    query_embedding = await embedding_service.get_embedding(query)
    gathered = []
    for candidate_radius in radii:
        gathered = _merge_unique_context_pois(
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
        generic_embedding = await embedding_service.get_embedding(
            "turismo general naturaleza gastronomía cultura descanso La Araucanía"
        )
        for candidate_radius in radii:
            gathered = _merge_unique_context_pois(
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


def _quick_replies_from_payload(payload: list[dict]) -> list[AraQuickReply]:
    replies: list[AraQuickReply] = []
    for item in payload:
        try:
            replies.append(AraQuickReply.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return replies


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
    start_date, end_date = _normalize_dates(payload.start_date, payload.end_date)
    preferences = ara_service.update_trip_draft_from_message(
        payload.initial_message,
        preferences,
        intent,
        start_date=start_date,
        end_date=end_date,
        payload_lat=payload.lat,
        payload_lon=payload.lon,
    )
    effective_lat, effective_lon, effective_radius, search_center_metadata = await _resolve_effective_search_context(
        payload.initial_message,
        ara_service,
        fallback_lat=payload.lat,
        fallback_lon=payload.lon,
        fallback_radius=payload.radius,
    )
    strict_destination = _is_strict_destination_context(search_center_metadata, payload.initial_message, ara_service)
    existing_search_center = (preferences.get("trip_draft") or {}).get("search_center") or {}
    if search_center_metadata.get("source") != "payload" or not existing_search_center.get("label"):
        preferences = ara_service.apply_search_center(
            preferences,
            lat=effective_lat,
            lon=effective_lon,
            source=str(search_center_metadata.get("source") or "payload"),
            label=search_center_metadata.get("label"),
        )
    replacement_request = (
        _extract_replacement_request_from_metadata(payload.metadata)
        or ara_service.extract_itinerary_step_context(payload.initial_message)
    )
    if replacement_request is not None:
        context = await _build_step_replacement_context(
            db,
            current_user,
            itinerary_id=replacement_request["itinerary_id"],
            step_id=replacement_request["step_id"],
        )
        if context is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        _itinerary_title, _step, current_poi = context
        candidate_pois = await _search_step_replacement_alternatives(
            db,
            current_user,
            embedding_service,
            message=payload.initial_message,
            current_poi=current_poi,
            lat=effective_lat,
            lon=effective_lon,
            radius=effective_radius,
        )
        preferences["replacement_context"] = {
            "itinerary_id": str(replacement_request["itinerary_id"]),
            "step_id": str(replacement_request["step_id"]),
            "current_poi_id": str(current_poi.id),
            "current_poi_name": str((payload.metadata or {}).get("poi_name") or current_poi.nombre),
            "frontend_metadata": payload.metadata or {},
        }
        quick_replies = ara_service.build_replacement_quick_replies(candidate_pois, replacement_request["step_id"])
        assistant_text = ara_service.build_replacement_message(current_poi.nombre, candidate_pois)

        try:
            session = await ara_repository.create_session(
                db,
                tourist_id=current_user.id,
                initial_query=payload.initial_message,
                lat=effective_lat or current_poi.latitude,
                lon=effective_lon or current_poi.longitude,
                radius=effective_radius or payload.radius,
                start_date=start_date,
                end_date=end_date,
                intent_data=intent,
                preferences_data=preferences,
                candidate_poi_ids=[poi.id for poi in candidate_pois],
            )
            await ara_repository.update_session_context(db, session, status="suggesting_step_replacement")
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
                metadata={
                    "replacement_context": preferences["replacement_context"],
                    "candidate_poi_count": len(candidate_pois),
                },
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
            candidate_pois=ara_service.compact_candidate_pois(
                candidate_pois,
                replacement_step_id=replacement_request["step_id"],
            ),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    candidate_pois = await _search_candidate_pois(
        db,
        payload.initial_message,
        current_user,
        embedding_service,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
    )
    candidate_pois = _filter_blacklisted_context_pois(payload.initial_message, candidate_pois)
    candidate_pois = await _maybe_diversify_candidate_pois(
        db,
        current_user,
        embedding_service,
        base_query=payload.initial_message,
        candidate_pois=candidate_pois,
        preferences=preferences,
        intent=intent,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
    )
    candidate_pois = _finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=payload.initial_message,
    )
    preferences = _remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )
    quick_replies = ara_service.build_quick_replies(intent, preferences)
    quick_replies = (
        _destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
        + quick_replies
    )
    assistant_text = ara_service.build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=True,
    )
    if strict_destination:
        assistant_text += _destination_scope_message_suffix(
            search_center_metadata,
            local_result_count=len(candidate_pois),
        )

    try:
        session = await ara_repository.create_session(
            db,
            tourist_id=current_user.id,
            initial_query=payload.initial_message,
            lat=effective_lat,
            lon=effective_lon,
            radius=effective_radius,
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
            metadata={
                "intent": intent,
                "candidate_poi_count": len(candidate_pois),
                "search_center": search_center_metadata,
                "strict_destination": strict_destination,
                "results_scope": "destination_only" if strict_destination else "expanded_or_payload",
            },
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
    ara_chat_service: AraChatService = Depends(get_ara_chat_service),
) -> AraSessionResponse:
    _ensure_tourist(current_user)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    previous_intent = session.intent_data or {}
    previous_preferences = session.preferences_data or {}

    replace_selection = ara_service.extract_replace_selection(payload.message, previous_preferences)
    if replace_selection is not None:
        replacement_context = previous_preferences.get("replacement_context") or {}
        itinerary_id_value = replacement_context.get("itinerary_id")
        if itinerary_id_value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Ara needs itinerary_id context before replacing a step.",
            )

        chosen_poi = await poi_repository.get_poi_by_id(db, replace_selection["poi_id"])
        if chosen_poi is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replacement POI not found.")

        updated_itinerary = await itinerary_repository.update_step(
            db,
            itinerary_id=UUID(itinerary_id_value),
            tourist_id=current_user.id,
            step_id=replace_selection["step_id"],
            step_in=ItineraryStepUpdate(
                poi_id=replace_selection["poi_id"],
                ai_context={
                    "reason": "Parada reemplazada desde conversación con Ara.",
                    "source": "ara_step_replacement",
                },
            ),
        )
        if updated_itinerary is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        assistant_text = (
            f"Listo, reemplacé esa parada por {chosen_poi.nombre}. "
            "El itinerario quedó actualizado y puedes revisarlo en el mapa o en el detalle."
        )
        try:
            previous_preferences.pop("replacement_context", None)
            await ara_repository.update_session_context(db, session, status="step_replaced", preferences_data=previous_preferences)
            user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
            assistant_message = await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                assistant_text,
                quick_replies=[
                    {
                        "id": "ver_itinerario_actualizado",
                        "label": "Ver itinerario",
                        "value": f"Ver itinerario {itinerary_id_value}",
                        "type": "navigation",
                    }
                ],
                metadata={
                    "itinerary_id": itinerary_id_value,
                    "step_id": str(replace_selection["step_id"]),
                    "replacement_poi_id": str(chosen_poi.id),
                    "updated_itinerary": updated_itinerary.model_dump(mode="json"),
                },
            )
            await ara_repository.commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        assistant_response = _session_message_response(assistant_message)
        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=_session_message_response(user_message),
            assistant_message=assistant_response,
            quick_replies=assistant_response.quick_replies,
            intent=previous_intent,
            preferences=previous_preferences,
            candidate_pois=ara_service.compact_candidate_pois([chosen_poi]),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    turn_classification = ara_service.classify_turn(payload.message, previous_intent, previous_preferences)

    if turn_classification["turn_type"] == "candidate_selection":
        selected_poi_id = ara_service.extract_candidate_selection(payload.message)
        if selected_poi_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid candidate selection.")
        selected_poi = await poi_repository.get_poi_by_id(db, selected_poi_id)
        if selected_poi is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected POI not found.")

        intent = ara_service.analyze_message(f"Quiero ir a {selected_poi.nombre}", previous_intent)
        preferences = ara_service.merge_preferences(
            f"Quiero ir a {selected_poi.nombre}",
            previous_preferences,
            turn_classification=turn_classification,
        )
        start_date, end_date = _normalize_dates(session.start_date, session.end_date)
        preferences = ara_service.ensure_trip_draft(
            preferences,
            start_date=start_date,
            end_date=end_date,
            payload_lat=session.lat,
            payload_lon=session.lon,
        )
        preferences = ara_service.mark_selected_poi(preferences, selected_poi)
        remaining_candidate_ids = [
            UUID(str(poi_id))
            for poi_id in (session.candidate_poi_ids or [])
            if str(poi_id) != str(selected_poi.id)
        ]

        quick_replies = ara_service.build_quick_replies(intent, preferences)
        selected_role = ((preferences.get("trip_draft") or {}).get("selected_pois") or [{}])[-1].get("role")
        if selected_role == "lodging":
            assistant_text = (
                f"Perfecto, guardaré {selected_poi.nombre} como alojamiento base probable del viaje. "
                "Si después quieres dormir en otra zona, dime el día o la noche y lo ajusto."
            )
        elif selected_role == "meal":
            assistant_text = (
                f"Perfecto, guardaré {selected_poi.nombre} como opción gastronómica y la ubicaré donde mejor calce. "
                "Si la quieres para un día específico, dime por ejemplo: lunes almuerzo o última noche."
            )
        else:
            assistant_text = (
                f"Perfecto, consideraré {selected_poi.nombre} dentro de la ruta. "
                "Si no me indicas un día específico, lo ubicaré automáticamente en el mejor momento."
            )

        try:
            await ara_repository.update_session_context(
                db,
                session,
                status="clarifying",
                intent_data=intent,
                preferences_data=preferences,
                candidate_poi_ids=remaining_candidate_ids,
            )
            user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
            assistant_message = await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                assistant_text,
                quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
                metadata={
                    **turn_classification,
                    "selected_poi_id": str(selected_poi.id),
                    "selected_poi_name": selected_poi.nombre,
                },
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
            candidate_pois=[],
            generated_itinerary_id=session.generated_itinerary_id,
        )

    if turn_classification["turn_type"] == "reset_or_new_trip":
        intent = ara_service.analyze_message(payload.message)
        preferences = ara_service.reset_trip_preferences(payload.message)
        start_date, end_date = _normalize_dates(session.start_date, session.end_date)
        preferences = ara_service.update_trip_draft_from_message(
            payload.message,
            preferences,
            intent,
            start_date=start_date,
            end_date=end_date,
            payload_lat=session.lat,
            payload_lon=session.lon,
        )
        effective_lat, effective_lon, effective_radius, search_center_metadata = await _resolve_effective_search_context(
            payload.message,
            ara_service,
            fallback_lat=session.lat,
            fallback_lon=session.lon,
            fallback_radius=session.radius,
        )
        strict_destination = _is_strict_destination_context(search_center_metadata, payload.message, ara_service)
        preferences = ara_service.apply_search_center(
            preferences,
            lat=effective_lat,
            lon=effective_lon,
            source=str(search_center_metadata.get("source") or "payload"),
            label=search_center_metadata.get("label"),
        )
        session.lat = effective_lat
        session.lon = effective_lon
        session.radius = effective_radius
        candidate_pois = await _search_candidate_pois(
            db,
            payload.message,
            current_user,
            embedding_service,
            lat=effective_lat,
            lon=effective_lon,
            radius=effective_radius,
            limit=12,
        )
        candidate_pois = _filter_blacklisted_context_pois(payload.message, candidate_pois)
        candidate_pois = await _maybe_diversify_candidate_pois(
            db,
            current_user,
            embedding_service,
            base_query=payload.message,
            candidate_pois=candidate_pois,
            preferences=preferences,
            intent=intent,
            lat=effective_lat,
            lon=effective_lon,
            radius=effective_radius,
        )
        candidate_pois = _finalize_candidate_pois(
            candidate_pois,
            intent=intent,
            preferences=preferences,
            query=payload.message,
        )
        preferences = _remember_destination_scope(
            preferences,
            strict_destination=strict_destination,
            search_center_metadata=search_center_metadata,
            local_result_count=len(candidate_pois),
        )
        quick_replies = ara_service.build_quick_replies(intent, preferences)
        quick_replies = (
            _destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
            + quick_replies
        )
        assistant_text = (
            "Perfecto, dejamos atrás el plan anterior y partimos con una idea nueva. "
            + ara_service.build_assistant_message(intent, preferences, candidate_pois, is_first_turn=True)
        )
        if strict_destination:
            assistant_text += _destination_scope_message_suffix(
                search_center_metadata,
                local_result_count=len(candidate_pois),
            )

        try:
            await ara_repository.update_session_context(
                db,
                session,
                status="clarifying",
                intent_data=intent,
                preferences_data=preferences,
                candidate_poi_ids=[poi.id for poi in candidate_pois],
                generated_itinerary_id=None,
            )
            user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
            assistant_message = await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                assistant_text,
                quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
                metadata={
                    **turn_classification,
                    "used_context": "new_trip",
                    "search_center": search_center_metadata,
                    "strict_destination": strict_destination,
                    "results_scope": "destination_only" if strict_destination else "expanded_or_payload",
                },
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
            generated_itinerary_id=None,
        )

    if turn_classification["turn_type"] == "generate_request":
        intent = previous_intent or ara_service.analyze_message(session.initial_query)
        preferences = ara_service.merge_preferences(
            payload.message,
            previous_preferences,
            turn_classification=turn_classification,
        )
        start_date, end_date = _normalize_dates(session.start_date, session.end_date)
        preferences = ara_service.update_trip_draft_from_message(
            payload.message,
            preferences,
            intent,
            start_date=start_date,
            end_date=end_date,
            payload_lat=session.lat,
            payload_lon=session.lon,
        )
        preferences["auto_generate_requested"] = True
        preferences["conversation_mode"] = "ready_to_generate"
        quick_replies = [
            AraQuickReply(
                id="generar_itinerario_async",
                label="Generar itinerario",
                value="Crear itinerario con lo acordado",
                type="generate",
            )
        ]
        assistant_text = ara_service.build_generate_request_message(preferences)

        try:
            await ara_repository.update_session_context(
                db,
                session,
                status="ready_to_generate",
                intent_data=intent,
                preferences_data=preferences,
            )
            user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
            assistant_message = await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                assistant_text,
                quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
                metadata=turn_classification,
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
            candidate_pois=[],
            generated_itinerary_id=session.generated_itinerary_id,
        )

    if turn_classification["turn_type"] == "free_question":
        preferences = copy.deepcopy(previous_preferences)
        preferences["turn_count"] = int(preferences.get("turn_count", 0)) + 1
        preferences["last_turn_type"] = "free_question"
        preferences["last_question_topic"] = turn_classification.get("topic")
        preferences["conversation_mode"] = "answering_question"
        if session.generated_itinerary_id is not None and not preferences.get("active_itinerary_id"):
            preferences["active_itinerary_id"] = str(session.generated_itinerary_id)

        active_itinerary = await _load_active_itinerary_from_preferences(db, current_user, preferences)
        if active_itinerary is not None:
            candidate_pois = await itinerary_repository.list_pois_for_itinerary(db, active_itinerary.id, current_user.id) or []
        else:
            candidate_pois = await _search_candidate_pois(
                db,
                f"{session.initial_query}. {payload.message}",
                current_user,
                embedding_service,
                lat=session.lat,
                lon=session.lon,
                radius=session.radius,
                limit=8,
            )
            candidate_pois = _filter_blacklisted_context_pois(payload.message, candidate_pois)

        chat_answer = await ara_chat_service.answer_free_question(
            user_message=payload.message,
            topic=str(turn_classification.get("topic") or "general"),
            preferences=preferences,
            candidate_pois=candidate_pois,
            active_itinerary=active_itinerary,
        )
        preferences = ara_service.apply_memory_patch(preferences, chat_answer.get("memory_patch"))
        quick_replies = _quick_replies_from_payload(chat_answer.get("quick_replies") or [])
        metadata = {
            **turn_classification,
            "used_context": chat_answer.get("used_context"),
            "evidence_level": chat_answer.get("evidence_level"),
        }

        try:
            await ara_repository.update_session_context(
                db,
                session,
                status="clarifying",
                preferences_data=preferences,
                candidate_poi_ids=[poi.id for poi in candidate_pois],
            )
            user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
            assistant_message = await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                str(chat_answer["answer"]),
                quick_replies=[reply.model_dump(mode="json") for reply in quick_replies],
                metadata=metadata,
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
            intent=previous_intent,
            preferences=preferences,
            candidate_pois=ara_service.compact_candidate_pois(candidate_pois),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    replacement_request = ara_service.extract_itinerary_step_context(payload.message)
    intent = ara_service.analyze_message(payload.message, previous_intent)
    preferences = ara_service.merge_preferences(
        payload.message,
        previous_preferences,
        turn_classification=turn_classification,
    )
    start_date, end_date = _normalize_dates(session.start_date, session.end_date)
    preferences = ara_service.update_trip_draft_from_message(
        payload.message,
        preferences,
        intent,
        start_date=start_date,
        end_date=end_date,
        payload_lat=session.lat,
        payload_lon=session.lon,
    )
    effective_lat, effective_lon, effective_radius, search_center_metadata = await _resolve_effective_search_context(
        payload.message,
        ara_service,
        fallback_lat=session.lat,
        fallback_lon=session.lon,
        fallback_radius=session.radius,
    )
    existing_search_center = (preferences.get("trip_draft") or {}).get("search_center") or {}
    if (
        _wants_expanded_destination_scope(payload.message, ara_service)
        and search_center_metadata.get("source") == "payload"
        and existing_search_center.get("label")
    ):
        effective_radius = max(effective_radius or 0, 60_000)
        search_center_metadata = {
            **search_center_metadata,
            "source": "expanded_destination",
            "label": existing_search_center.get("label"),
        }
    inherited_strict, inherited_metadata = _inherits_strict_destination_context(
        preferences,
        search_center_metadata,
        payload.message,
        ara_service,
    )
    if inherited_strict:
        search_center_metadata = inherited_metadata
    strict_destination = inherited_strict or _is_strict_destination_context(
        search_center_metadata,
        payload.message,
        ara_service,
    )
    if search_center_metadata.get("source") != "payload" or not existing_search_center.get("label"):
        preferences = ara_service.apply_search_center(
            preferences,
            lat=effective_lat,
            lon=effective_lon,
            source=str(search_center_metadata.get("source") or "payload"),
            label=search_center_metadata.get("label"),
        )
    session.lat = effective_lat
    session.lon = effective_lon
    session.radius = effective_radius

    if replacement_request is not None:
        context = await _build_step_replacement_context(
            db,
            current_user,
            itinerary_id=replacement_request["itinerary_id"],
            step_id=replacement_request["step_id"],
        )
        if context is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        _itinerary_title, step, current_poi = context
        candidate_pois = await _search_step_replacement_alternatives(
            db,
            current_user,
            embedding_service,
            message=payload.message,
            current_poi=current_poi,
            lat=effective_lat,
            lon=effective_lon,
            radius=effective_radius,
        )
        preferences["replacement_context"] = {
            "itinerary_id": str(replacement_request["itinerary_id"]),
            "step_id": str(replacement_request["step_id"]),
            "current_poi_id": str(current_poi.id),
            "current_poi_name": current_poi.nombre,
        }
        quick_replies = ara_service.build_replacement_quick_replies(candidate_pois, replacement_request["step_id"])
        assistant_text = ara_service.build_replacement_message(current_poi.nombre, candidate_pois)

        try:
            await ara_repository.update_session_context(
                db,
                session,
                status="suggesting_step_replacement",
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
                metadata={
                    "replacement_context": preferences["replacement_context"],
                    "candidate_poi_count": len(candidate_pois),
                },
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

    query_for_search = f"{session.initial_query}. {payload.message}"
    candidate_pois = await _search_candidate_pois(
        db,
        query_for_search,
        current_user,
        embedding_service,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
    )
    candidate_pois = _filter_blacklisted_context_pois(query_for_search, candidate_pois)
    if not candidate_pois and session.candidate_poi_ids:
        candidate_pois = await poi_repository.get_pois_by_ids(db, [UUID(poi_id) for poi_id in session.candidate_poi_ids])
        if strict_destination:
            candidate_pois = _filter_pois_to_search_center(
                candidate_pois,
                lat=effective_lat,
                lon=effective_lon,
                radius=effective_radius,
            )
        candidate_pois = _filter_blacklisted_context_pois(query_for_search, candidate_pois)
    candidate_pois = await _maybe_diversify_candidate_pois(
        db,
        current_user,
        embedding_service,
        base_query=query_for_search,
        candidate_pois=candidate_pois,
        preferences=preferences,
        intent=intent,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
    )
    candidate_pois = _finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=query_for_search,
    )
    preferences = _remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )

    status_value = "ready_to_generate" if preferences.get("auto_generate_requested") else "clarifying"
    quick_replies = ara_service.build_quick_replies(intent, preferences)
    quick_replies = (
        _destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
        + quick_replies
    )
    assistant_text = ara_service.build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=False,
    )
    if strict_destination:
        assistant_text += _destination_scope_message_suffix(
            search_center_metadata,
            local_result_count=len(candidate_pois),
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
            metadata={
                "intent": intent,
                "candidate_poi_count": len(candidate_pois),
                "search_center": search_center_metadata,
                "strict_destination": strict_destination,
                "results_scope": "destination_only" if strict_destination else "expanded_or_payload",
                **turn_classification,
            },
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


async def _generate_itinerary_from_ara_session_core(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
    ara_service: AraConversationService,
) -> AraGenerateItineraryResponse:
    _ensure_tourist(current_user)

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

    refined_query = ara_service.build_refined_query(
        session.initial_query,
        user_messages,
        session.intent_data,
        session.preferences_data,
    )
    search_query = refined_query
    if preferences_data.get("surprise_route_requested"):
        search_query += (
            "\nRuta sorpresa equilibrada: recuperar un pool diverso, no solo lugares gastronómicos. "
            "Incluir naturaleza, cultura, miradores, descanso, actividades suaves y gastronomía."
        )
    destination_scope = trip_draft.get("destination_scope") if isinstance(trip_draft, dict) else {}
    strict_destination = bool((destination_scope or {}).get("strict"))

    start_date, end_date = _normalize_dates(session.start_date, session.end_date)
    generation_payload = GenerateItineraryRequest(
        query=refined_query,
        lat=float(effective_lat),
        lon=float(effective_lon),
        radius=session.radius or 5000,
        start_date=start_date,
        end_date=end_date,
    )

    trip_days = _trip_days(generation_payload)
    retrieval_limit = min(80, max(20, trip_days * 12))

    session_context_pois = []
    if session.candidate_poi_ids:
        session_context_pois = await poi_repository.get_pois_by_ids(
            db,
            [UUID(poi_id) for poi_id in session.candidate_poi_ids],
        )
        if strict_destination:
            session_context_pois = _filter_pois_to_search_center(
                session_context_pois,
                lat=generation_payload.lat,
                lon=generation_payload.lon,
                radius=generation_payload.radius,
            )
    searched_context_pois = await _search_generation_context_with_fallbacks(
        db,
        current_user,
        embedding_service,
        query=search_query,
        lat=generation_payload.lat,
        lon=generation_payload.lon,
        radius=generation_payload.radius,
        limit=retrieval_limit,
        strict_destination=strict_destination,
    )

    context_pois = _merge_unique_context_pois(
        session_context_pois,
        searched_context_pois,
        max_pois=retrieval_limit,
    )
    if strict_destination:
        context_pois = _filter_pois_to_search_center(
            context_pois,
            lat=generation_payload.lat,
            lon=generation_payload.lon,
            radius=generation_payload.radius,
        )
    context_pois = _filter_blacklisted_context_pois(refined_query, context_pois)
    context_pois = _prepare_context_pois(refined_query, context_pois, retrieval_limit)
    if not context_pois:
        scope_label = (destination_scope or {}).get("label")
        detail = (
            f"No encontré datos suficientes directamente en {scope_label}. "
            "Puedes ampliar la búsqueda a comunas cercanas o ajustar el tipo de lugares."
            if strict_destination and scope_label
            else (
                "No encontré suficientes lugares para generar una ruta segura con esos datos. "
                "Prueba ampliando el radio o ajustando la ubicación."
            )
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )

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
    generated_itinerary = _normalize_generated_itinerary_times(generated_itinerary, generation_payload)
    generated_itinerary = _repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = _repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The LLM returned POIs outside Ara context.")
    if not generated_itinerary.steps:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ara did not return itinerary steps.")

    _validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = _sanitize_generated_itinerary_context(generated_itinerary)

    itinerary = await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        generated_itinerary=generated_itinerary,
    )

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is not None:
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
            "Listo, armé un itinerario personalizado con lo que conversamos.",
            metadata={"generated_itinerary_id": str(itinerary.id)},
        )
        await ara_repository.commit_or_rollback(db)

    return AraGenerateItineraryResponse(session_id=session_id, status="completed", itinerary=itinerary)


async def _get_user_for_background_job(db: AsyncSession, user_id: UUID) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.tourist_profile))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _run_ara_itinerary_generation_job(
    session_id: UUID,
    tourist_id: UUID,
    payload: AraGenerateItineraryRequest | None,
) -> None:
    async with AsyncSessionLocal() as db:
        current_user = await _get_user_for_background_job(db, tourist_id)
        session = await ara_repository.get_session(db, session_id, tourist_id)
        if current_user is None or session is None:
            return

        try:
            await _generate_itinerary_from_ara_session_core(
                session_id=session_id,
                payload=payload,
                db=db,
                current_user=current_user,
                embedding_service=get_embedding_service(),
                llm_service=get_itinerary_generator(),
                ara_service=get_ara_conversation_service(),
            )
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            session = await ara_repository.get_session(db, session_id, tourist_id)
            if session is None:
                return
            await ara_repository.update_session_context(db, session, status="failed")
            await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                (
                    "Tuve un problema armando el itinerario completo. "
                    "Puedes intentarlo de nuevo o ajustar un poco la búsqueda."
                ),
                metadata={
                    "generation_error": type(exc).__name__,
                    "detail": str(exc),
                },
            )
            await ara_repository.commit_or_rollback(db)


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
    ara_service: AraConversationService = Depends(get_ara_conversation_service),
) -> AraGenerateItineraryResponse:
    return await _generate_itinerary_from_ara_session_core(
        session_id=session_id,
        payload=payload,
        db=db,
        current_user=current_user,
        embedding_service=embedding_service,
        llm_service=llm_service,
        ara_service=ara_service,
    )


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
        _run_ara_itinerary_generation_job,
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
