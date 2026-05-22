from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ara_messages import AraMessages
from app.core.exceptions import ConcurrencyError
from app.db.session import AsyncSessionLocal
from app.models.ara_message import AraMessage
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import (
    AraCandidatePOI,
    AraGenerateItineraryRequest,
    AraGenerateItineraryResponse,
    AraIntentInfo,
    AraMessageCreate,
    AraPreferenceSummary,
    AraQuickReply,
    AraSessionCreate,
    AraSessionResponse,
)
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, ItineraryStepUpdate
from app.services.ara_preference_merger import apply_memory_patch, merge_preferences, reset_trip_preferences
from app.services.ara_response_builder import (
    build_assistant_message,
    build_generate_request_message,
    build_quick_replies,
    build_refined_query,
    build_replacement_message,
    build_replacement_quick_replies,
)
from app.services.ara_trip_draft_builder import (
    apply_search_center,
    ensure_trip_draft,
    mark_selected_poi,
    update_trip_draft_from_message,
)
from app.services.ara_turn_classifier import (
    analyze_intent,
    classify_turn,
    extract_candidate_selection,
    extract_itinerary_step_context,
    extract_replace_selection,
    get_classifier_llm_client,
)
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
    candidate_matches_intent,
    destination_scope_message_suffix,
    destination_scope_quick_replies,
    filter_pois_to_search_center,
    inherits_strict_destination_context,
    is_strict_destination_context,
    poi_text,
    remember_destination_scope,
    resolve_effective_search_context,
    search_candidate_pois,
    search_generation_context_with_fallbacks,
    wants_expanded_destination_scope,
)
from app.services.weather_service import get_forecast

ara_repository = AraRepository()
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()

_classifier_llm_client: Any | None = None


async def _update_session_with_retry(
    repo: AraRepository,
    db: AsyncSession,
    session: AraSession,
    user_id: UUID,
    **kwargs: Any,
) -> AraSession:
    expected_version = session.version
    for attempt in range(2):
        success = await repo.update_session_context(
            db,
            session,
            expected_version=expected_version,
            **kwargs,
        )
        if success:
            return session
        if attempt == 1:
            raise ConcurrencyError()
        await db.rollback()
        reloaded = await repo.get_session(db, session.id, user_id)
        if reloaded is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session lost during concurrent update.")
        session = reloaded
        expected_version = session.version
    return session


def _ensure_classifier_llm_client() -> Any | None:
    global _classifier_llm_client
    if _classifier_llm_client is None:
        _classifier_llm_client = get_classifier_llm_client()
    return _classifier_llm_client


def _build_intent_info(intent_data: dict[str, Any] | None, preferences: dict[str, Any] | None = None) -> AraIntentInfo | None:
    if not intent_data:
        return None
    return AraIntentInfo(
        intents=intent_data.get("intents", []),
        primary_intent=intent_data.get("primary_intent"),
        specificity=intent_data.get("specificity"),
        locations=intent_data.get("locations", []),
        turn_count=int(preferences.get("turn_count", 0)) if preferences else 0,
    )


def _build_preference_summary(preferences_data: dict[str, Any] | None) -> AraPreferenceSummary | None:
    if not preferences_data:
        return None
    trip_draft = preferences_data.get("trip_draft")
    destination_scope = None
    if trip_draft and isinstance(trip_draft, dict):
        ds = trip_draft.get("destination_scope")
        if isinstance(ds, dict):
            destination_scope = ds.get("label")
    return AraPreferenceSummary(
        tags=list(preferences_data.get("tags", [])),
        positive_preferences=list(preferences_data.get("positive_preferences", [])),
        negative_constraints=list(preferences_data.get("negative_constraints", [])),
        completed_dimensions=list(preferences_data.get("completed_dimensions", [])),
        trip_draft=trip_draft,
        destination_scope=destination_scope,
        selected_poi_ids=[str(pid) for pid in (preferences_data.get("selected_poi_ids") or [])],
        conversation_mode=preferences_data.get("conversation_mode"),
        route_ready_score=float(preferences_data.get("route_ready_score", 0)),
    )


def _build_candidate_poi(poi: Any) -> AraCandidatePOI:
    multimedia_urls = getattr(poi, "multimedia_urls", None) or {}
    image_url = None
    if isinstance(multimedia_urls, dict):
        candidate_url = multimedia_urls.get("image_url") or multimedia_urls.get("cover") or multimedia_urls.get("image")
        if isinstance(candidate_url, str) and (candidate_url.startswith("http://") or candidate_url.startswith("https://")):
            image_url = candidate_url
    elif isinstance(multimedia_urls, list) and multimedia_urls:
        image_url = str(multimedia_urls[0])
    return AraCandidatePOI(
        id=poi.id if isinstance(poi.id, UUID) else UUID(str(poi.id)),
        name=poi.name,
        description=getattr(poi, "description", None),
        category_ids=list(getattr(poi, "category_ids", []) or []),
        latitude=getattr(poi, "latitude", None),
        longitude=getattr(poi, "longitude", None),
        image_url=image_url,
        distance_meters=getattr(poi, "distance_meters", None),
        poi_role=getattr(poi, "poi_role", None),
    )


def _build_candidate_pois(pois: list[Any]) -> list[AraCandidatePOI]:
    return [_build_candidate_poi(poi) for poi in pois[:8]]


def _extract_active_itinerary_id(preferences: dict[str, Any] | None) -> UUID | None:
    if not preferences:
        return None
    aid = preferences.get("active_itinerary_id")
    if aid is None:
        return None
    try:
        return UUID(str(aid))
    except (TypeError, ValueError):
        return None


def _candidate_uuid_list(candidate_poi_ids: list[UUID] | list[str] | None) -> list[UUID]:
    return [
        poi_id if isinstance(poi_id, UUID) else UUID(str(poi_id))
        for poi_id in (candidate_poi_ids or [])
    ]


def normalize_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    normalized_start = start_date or date.today()
    normalized_end = end_date or normalized_start
    return normalized_start, normalized_end


def align_candidate_pois_with_intent(
    candidate_pois: list,
    intent: dict[str, Any],
    query: str,
    *,
    completed_dimensions: set | None = None,
) -> list:
    primary_intent = str(intent.get("primary_intent") or "exploracion")
    completed = completed_dimensions or set()
    normalized_query = query.lower()

    explicit_current_intent = (
        primary_intent == "gastronomia"
        and any(term in normalized_query for term in ("restaurant", "restaurante", "pizzeria", "pizzería", "pizza", "cafe", "café", "comida", "cocina", "bar", "pub", "empanada", "sushi", "marisco", "sopa", "sopas", "cazuela", "carne", "carnes", "picada", "pasteleria", "pastelería", "almorzar", "cenar"))
    ) or (
        primary_intent == "alojamiento"
        and any(term in normalized_query for term in ("hotel", "hostal", "hostel", "cabaña", "cabana", "alojamiento", "hospedaje", "camping"))
    ) or (
        primary_intent == "naturaleza"
        and any(term in normalized_query for term in ("sendero", "trekking", "mirador", "lago", "volcan", "volcán", "parque", "cascada", "terma", "outdoor", "aire libre"))
    ) or (
        primary_intent == "cultura"
        and any(term in normalized_query for term in ("museo", "patrimonio", "mapuche", "artesania", "artesanía", "historia", "feria"))
    )

    if primary_intent in completed and not explicit_current_intent:
        return candidate_pois
    if primary_intent not in {"gastronomia", "alojamiento", "naturaleza", "cultura"}:
        return candidate_pois

    poi_texts = {id(poi): poi_text(poi) for poi in candidate_pois}

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
                specific_matches = [poi for poi in candidate_pois if any(term in poi_texts[id(poi)] for term in terms)]
                if specific_matches:
                    return specific_matches

    aligned = [poi for poi in candidate_pois if candidate_matches_intent(poi, primary_intent, query, poi_text_cache=poi_texts)]
    if aligned:
        return aligned

    if primary_intent in {"gastronomia", "alojamiento"}:
        return []
    return candidate_pois


def exclude_selected_candidate_pois(candidate_pois: list, preferences: dict[str, Any]) -> list:
    excluded_ids: set[str] = set(preferences.get("selected_poi_ids") or [])
    if preferences.get("last_selected_poi_id"):
        excluded_ids.add(str(preferences["last_selected_poi_id"]))
    if preferences.get("active_itinerary_poi_ids"):
        excluded_ids.update(str(value) for value in preferences.get("active_itinerary_poi_ids", []))
    if not excluded_ids:
        return candidate_pois
    return [poi for poi in candidate_pois if str(getattr(poi, "id", "")) not in excluded_ids]


def finalize_candidate_pois(candidate_pois: list, *, intent: dict[str, Any], preferences: dict[str, Any], query: str) -> list:
    if preferences.get("surprise_route_requested"):
        return exclude_selected_candidate_pois(candidate_pois, preferences)[:8]
    completed = set(preferences.get("completed_dimensions") or [])
    aligned = align_candidate_pois_with_intent(candidate_pois, intent, query, completed_dimensions=completed)
    return exclude_selected_candidate_pois(aligned, preferences)[:8]


async def maybe_diversify_candidate_pois(
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
    embedding_cache: EmbeddingCache | None = None,
) -> list:
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

    logger.info(
        "Diversification triggered primary_intent=%s completed=%s surprise=%s",
        primary_intent, completed_dimensions, surprise,
    )
    diversification_query = (
        f"{base_query}. Para equilibrar el viaje, buscar también naturaleza, miradores, cultura, "
        "actividades suaves y descanso. No limitar la conversación solo a restaurantes o comida."
    )
    diversified = await search_candidate_pois(
        db,
        poi_repository,
        diversification_query,
        current_user,
        embedding_service,
        lat=lat,
        lon=lon,
        radius=radius,
        limit=12,
        embedding_cache=embedding_cache,
    )
    diversified = filter_blacklisted_context_pois(diversification_query, diversified)
    merged = merge_unique_context_pois(candidate_pois, diversified, max_pois=12)
    logger.info(
        "Diversification result: original=%d diversified=%d merged=%d",
        len(candidate_pois), len(diversified), len(merged),
    )
    return merged


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
        f"Buscar alternativa turística real para reemplazar este POI: {current_poi.name}. "
        f"Descripción actual: {current_poi.description}. Preferencias del usuario: {message}"
    )
    logger.debug(
        "Searching replacement alternatives for poi=%s lat=%s lon=%s radius=%s",
        current_poi.name, search_lat, search_lon, search_radius,
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
    logger.info("Replacement alternatives found: %d for poi=%s", len(result), current_poi.name)
    return result


def extract_replacement_request_from_metadata(metadata: dict | None) -> dict[str, UUID] | None:
    if not metadata or metadata.get("intent") != "change_itinerary_step":
        return None

    try:
        return {
            "itinerary_id": UUID(str(metadata["itinerary_id"])),
            "step_id": UUID(str(metadata["step_id"])),
        }
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Invalid replacement metadata: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="metadata.itinerary_id and metadata.step_id must be valid UUIDs for change_itinerary_step.",
        ) from exc


def session_message_response(message: AraMessage) -> Any:
    return ara_repository.to_message_response(message)


async def load_active_itinerary_from_preferences(
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
        logger.debug("Invalid itinerary_id in preferences: %s", itinerary_id_value)
        return None
    return await itinerary_repository.get_itinerary_by_id(db, itinerary_id, current_user.id)


def quick_replies_from_payload(payload: list[dict]) -> list[AraQuickReply]:
    replies: list[AraQuickReply] = []
    for item in payload:
        try:
            replies.append(AraQuickReply.model_validate(item))
        except Exception:
            logger.debug("Skipping invalid quick reply payload: %s", item)
            continue
    return replies


async def create_session(
    db: AsyncSession,
    current_user: User,
    payload: AraSessionCreate,
    embedding_service: OpenAIEmbeddingService,
) -> AraSessionResponse:
    logger.info(
        "Creating session user_id=%s initial_query=%.100r lat=%s lon=%s radius=%s",
        current_user.id, payload.initial_message, payload.lat, payload.lon, payload.radius,
    )
    embedding_cache = EmbeddingCache(embedding_service)
    intent = await analyze_intent(payload.initial_message, llm_client=_ensure_classifier_llm_client())
    logger.debug("Session intent analysis result: %s", intent)
    preferences = merge_preferences(payload.initial_message)
    logger.debug("Initial preferences after merge: %s", preferences)
    start_date, end_date = normalize_dates(payload.start_date, payload.end_date)
    preferences = update_trip_draft_from_message(
        payload.initial_message,
        preferences,
        intent,
        start_date=start_date,
        end_date=end_date,
        payload_lat=payload.lat,
        payload_lon=payload.lon,
    )
    logger.debug("Preferences after trip draft update: %s", preferences)
    effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
        payload.initial_message,
        fallback_lat=payload.lat,
        fallback_lon=payload.lon,
        fallback_radius=payload.radius,
    )
    logger.info(
        "Search context resolved lat=%s lon=%s radius=%s source=%s label=%s",
        effective_lat, effective_lon, effective_radius,
        search_center_metadata.get("source"), search_center_metadata.get("label"),
    )
    strict_destination = is_strict_destination_context(search_center_metadata, payload.initial_message)
    logger.debug("Strict destination context: %s", strict_destination)
    existing_search_center = (preferences.get("trip_draft") or {}).get("search_center") or {}
    if search_center_metadata.get("source") != "payload" or not existing_search_center.get("label"):
        preferences = apply_search_center(
            preferences,
            lat=effective_lat,
            lon=effective_lon,
            source=str(search_center_metadata.get("source") or "payload"),
            label=search_center_metadata.get("label"),
        )
        logger.debug("Search center applied to preferences: %s", preferences.get("trip_draft", {}).get("search_center"))
    replacement_request = (
        extract_replacement_request_from_metadata(payload.metadata)
        or extract_itinerary_step_context(payload.initial_message)
    )
    if replacement_request is not None:
        logger.info("Replacement request detected itinerary_id=%s step_id=%s", replacement_request.get("itinerary_id"), replacement_request.get("step_id"))
        context = await build_step_replacement_context(
            db,
            current_user,
            itinerary_id=replacement_request["itinerary_id"],
            step_id=replacement_request["step_id"],
        )
        if context is None:
            logger.warning("Replacement context not found for step_id=%s", replacement_request.get("step_id"))
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        _itinerary_title, _step, current_poi = context
        logger.info("Searching replacement alternatives for poi=%s", current_poi.name)
        candidate_pois = await search_step_replacement_alternatives(
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
            "current_poi_name": str((payload.metadata or {}).get("poi_name") or current_poi.name),
            "frontend_metadata": payload.metadata or {},
        }
        quick_replies = build_replacement_quick_replies(candidate_pois, replacement_request["step_id"])
        assistant_text = build_replacement_message(current_poi.name, candidate_pois)

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
            logger.info(
                "Session created (replacement) session_id=%s user_id=%s status=%s",
                session.id, current_user.id, session.status,
            )
        except Exception:
            await db.rollback()
            logger.exception("Failed to create session (replacement path) user_id=%s", current_user.id)
            raise

        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=_build_intent_info(intent, preferences),
            preferences=_build_preference_summary(preferences),
            candidate_pois=_build_candidate_pois(candidate_pois),
            generated_itinerary_id=session.generated_itinerary_id,
            active_itinerary_id=_extract_active_itinerary_id(preferences),
        )

    logger.debug("Searching candidate POIs for session creation query=%.100r", payload.initial_message)
    candidate_pois = await search_candidate_pois(
        db,
        poi_repository,
        payload.initial_message,
        current_user,
        embedding_service,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
        embedding_cache=embedding_cache,
    )
    logger.info("POI search returned %d candidates", len(candidate_pois))
    candidate_pois = filter_blacklisted_context_pois(payload.initial_message, candidate_pois)
    candidate_pois = await maybe_diversify_candidate_pois(
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
        embedding_cache=embedding_cache,
    )
    logger.debug("After diversification: %d candidates", len(candidate_pois))
    candidate_pois = finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=payload.initial_message,
    )
    logger.debug("After finalize: %d candidates", len(candidate_pois))
    preferences = remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )
    quick_replies = build_quick_replies(intent, preferences)
    quick_replies = (
        destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
        + quick_replies
    )
    assistant_text = build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=True,
    )
    if strict_destination:
        assistant_text += destination_scope_message_suffix(
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
        logger.info(
            "Session created session_id=%s user_id=%s status=%s intent=%s",
            session.id, current_user.id, session.status, intent.get("primary_intent"),
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to create session (normal path) user_id=%s", current_user.id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=_build_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
        destination_context=search_center_metadata,
    )




async def _handle_replace_selection(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    session_id: UUID,
    replace_selection: dict[str, UUID],
    previous_preferences: dict[str, Any],
    previous_intent: dict[str, Any],
) -> AraSessionResponse:
    replacement_context = previous_preferences.get("replacement_context") or {}
    itinerary_id_value = replacement_context.get("itinerary_id")
    if itinerary_id_value is None:
        logger.warning("Missing itinerary_id for replacement session_id=%s", session_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ara needs itinerary_id context before replacing a step.",
        )

    chosen_poi = await poi_repository.get_poi_by_id(db, replace_selection["poi_id"])
    if chosen_poi is None:
        logger.warning("Replacement POI not found poi_id=%s", replace_selection["poi_id"])
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replacement POI not found.")

    current_itinerary = await itinerary_repository.get_itinerary_by_id(
        db, itinerary_id=UUID(itinerary_id_value), tourist_id=current_user.id,
    )
    current_step = None
    current_poi_name = None
    if current_itinerary is not None:
        current_step = next(
            (s for s in current_itinerary.steps if s.id == replace_selection["step_id"]),
            None,
        )
        if current_step is not None:
            current_poi_name = current_step.poi_name

    replacement_context = previous_preferences.get("replacement_context") or {}
    original_poi_name = str(
        (replacement_context.get("frontend_metadata") or {}).get("poi_name")
        or current_poi_name
        or "la parada anterior"
    )

    existing_ai_context = dict(current_step.ai_context) if current_step and current_step.ai_context else {}
    chosen_poi_desc = (chosen_poi.description or "")[:120]
    existing_ai_context["reason"] = (
        f"Te sugiero {chosen_poi.name or 'esta parada'}: {chosen_poi_desc} "
        "para aprovechar al maximo este momento del dia."
    )
    existing_ai_context["source"] = "ara_step_replacement"
    existing_ai_context["replaced_poi_name"] = original_poi_name

    updated_itinerary = await itinerary_repository.update_step(
        db,
        itinerary_id=UUID(itinerary_id_value),
        tourist_id=current_user.id,
        step_id=replace_selection["step_id"],
        step_in=ItineraryStepUpdate(
            poi_id=replace_selection["poi_id"],
            ai_context=existing_ai_context,
        ),
    )
    if updated_itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

    assistant_text = AraMessages.get("replacement_complete", poi_name=chosen_poi.name)
    try:
        previous_preferences.pop("replacement_context", None)
        session = await _update_session_with_retry(ara_repository, db, session, current_user.id, status="step_replaced", preferences_data=previous_preferences)
        user_message = await ara_repository.add_message(db, session.id, "user", payload.message)
        assistant_message = await ara_repository.add_message(
            db,
            session.id,
            "assistant",
            assistant_text,
            quick_replies=[
                {
                    "id": "ver_itinerario_actualizado",
                    "label": AraMessages.get("reply_ver_itinerario_label"),
                    "value": AraMessages.get("reply_ver_itinerario_value", itinerary_id=itinerary_id_value),
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
        logger.info(
            "Step replaced session_id=%s step_id=%s new_poi=%s",
            session_id, replace_selection["step_id"], chosen_poi.name,
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to replace step session_id=%s", session_id)
        raise

    assistant_response = session_message_response(assistant_message)
    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=assistant_response,
        quick_replies=assistant_response.quick_replies,
        intent=_build_intent_info(previous_intent, previous_preferences),
        preferences=_build_preference_summary(previous_preferences),
        candidate_pois=_build_candidate_pois([chosen_poi]),
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(previous_preferences),
    )


async def _handle_candidate_selection(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    session_id: UUID,
    turn_count: int,
    turn_classification: dict[str, Any],
    selected_poi_id: UUID,
    selected_poi: Any,
    previous_preferences: dict[str, Any],
    previous_intent: dict[str, Any],
    llm_client: Any,
) -> AraSessionResponse:
    logger.info("Candidate selected session_id=%s poi=%s", session_id, selected_poi.name)
    intent = await analyze_intent(f"Quiero ir a {selected_poi.name}", previous_intent, llm_client=llm_client)
    logger.debug("Intent after selection: %s", intent)
    preferences = merge_preferences(
        f"Quiero ir a {selected_poi.name}",
        previous_preferences,
        turn_classification=turn_classification,
    )
    start_date, end_date = normalize_dates(session.start_date, session.end_date)
    preferences = ensure_trip_draft(
        preferences,
        start_date=start_date,
        end_date=end_date,
        payload_lat=session.lat,
        payload_lon=session.lon,
    )
    preferences = mark_selected_poi(preferences, selected_poi)
    logger.debug("Preferences after marking selected POI: %s", preferences)
    remaining_candidate_ids = [
        poi_id
        for poi_id in _candidate_uuid_list(session.candidate_poi_ids)
        if poi_id != selected_poi.id
    ]

    quick_replies = build_quick_replies(intent, preferences)
    selected_role = ((preferences.get("trip_draft") or {}).get("selected_pois") or [{}])[-1].get("role")
    if selected_role == "lodging":
        assistant_text = AraMessages.get("selection_lodging", poi_name=selected_poi.name)
    elif selected_role == "meal":
        assistant_text = AraMessages.get("selection_meal", poi_name=selected_poi.name)
    else:
        assistant_text = AraMessages.get("selection_default", poi_name=selected_poi.name)

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
                "selected_poi_name": selected_poi.name,
            },
        )
        await ara_repository.commit_or_rollback(db)
        logger.info(
            "Candidate selection committed session_id=%s turn=%d status=%s",
            session_id, turn_count, session.status,
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to process candidate selection session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=[],
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
    )


async def _handle_reset_or_new_trip(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    embedding_service: OpenAIEmbeddingService,
    embedding_cache: EmbeddingCache,
    session_id: UUID,
    turn_count: int,
    turn_classification: dict[str, Any],
    llm_client: Any,
) -> AraSessionResponse:
    logger.info("Reset/new trip requested session_id=%s turn=%d", session_id, turn_count)
    intent = await analyze_intent(payload.message, llm_client=llm_client)
    logger.debug("Intent after reset: %s", intent)
    preferences = reset_trip_preferences(payload.message)
    logger.debug("Preferences after reset: %s", preferences)
    start_date, end_date = normalize_dates(session.start_date, session.end_date)
    preferences = update_trip_draft_from_message(
        payload.message,
        preferences,
        intent,
        start_date=start_date,
        end_date=end_date,
        payload_lat=session.lat,
    )
    effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
        payload.message,
        fallback_lat=session.lat,
        fallback_lon=session.lon,
        fallback_radius=session.radius,
    )
    logger.info(
        "Reset search context lat=%s lon=%s radius=%s source=%s",
        effective_lat, effective_lon, effective_radius, search_center_metadata.get("source"),
    )
    strict_destination = is_strict_destination_context(search_center_metadata, payload.message)
    preferences = apply_search_center(
        preferences,
        lat=effective_lat,
        lon=effective_lon,
        source=str(search_center_metadata.get("source") or "payload"),
        label=search_center_metadata.get("label"),
    )
    session.lat = effective_lat
    session.lon = effective_lon
    session.radius = effective_radius
    logger.debug("Searching candidate POIs for reset query=%.100r", payload.message)
    candidate_pois = await search_candidate_pois(
        db,
        poi_repository,
        payload.message,
        current_user,
        embedding_service,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
        limit=12,
        embedding_cache=embedding_cache,
    )
    logger.info("Reset POI search returned %d candidates", len(candidate_pois))
    candidate_pois = filter_blacklisted_context_pois(payload.message, candidate_pois)
    candidate_pois = await maybe_diversify_candidate_pois(
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
        embedding_cache=embedding_cache,
    )
    logger.debug("After diversification for reset: %d candidates", len(candidate_pois))
    candidate_pois = finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=payload.message,
    )
    logger.debug("After finalize for reset: %d candidates", len(candidate_pois))
    preferences = remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )
    quick_replies = build_quick_replies(intent, preferences)
    quick_replies = (
        destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
        + quick_replies
    )
    assistant_text = (
        AraMessages.get("session_reset_prefix")
        + build_assistant_message(intent, preferences, candidate_pois, is_first_turn=True)
    )
    if strict_destination:
        assistant_text += destination_scope_message_suffix(
            search_center_metadata,
            local_result_count=len(candidate_pois),
        )

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
        logger.info(
            "Reset committed session_id=%s turn=%d status=%s candidates=%d",
            session_id, turn_count, session.status, len(candidate_pois),
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to process reset/new trip session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=_build_candidate_pois(candidate_pois),
        generated_itinerary_id=None,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
        destination_context=search_center_metadata,
    )


async def _handle_generate_request(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    previous_preferences: dict[str, Any],
    previous_intent: dict[str, Any],
    session_id: UUID,
    turn_count: int,
    turn_classification: dict[str, Any],
    llm_client: Any,
) -> AraSessionResponse:
    logger.info("Generate request received session_id=%s turn=%d", session_id, turn_count)
    intent = previous_intent if previous_intent else await analyze_intent(session.initial_query, llm_client=llm_client)
    preferences = merge_preferences(
        payload.message,
        previous_preferences,
        turn_classification=turn_classification,
    )
    logger.debug("Preferences merged for generate_request: %s", preferences)
    start_date, end_date = normalize_dates(session.start_date, session.end_date)
    preferences = update_trip_draft_from_message(
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
    logger.debug("Trip draft updated for generate_request")
    quick_replies = [
        AraQuickReply(
            id="generar_itinerario_async",
            label=AraMessages.get("reply_generar_itinerario_label"),
            value=AraMessages.get("reply_crear_itinerario_value"),
            type="generate",
        )
    ]
    assistant_text = build_generate_request_message(preferences)

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
        logger.info(
            "Generate request committed session_id=%s turn=%d status=ready_to_generate",
            session_id, turn_count,
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to process generate request session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=[],
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
    )


async def _handle_free_question(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    ara_chat_service: Any,
    embedding_service: OpenAIEmbeddingService,
    embedding_cache: EmbeddingCache,
    previous_preferences: dict[str, Any],
    previous_intent: dict[str, Any],
    session_id: UUID,
    turn_count: int,
    turn_classification: dict[str, Any],
) -> AraSessionResponse:
    logger.info("Free question received session_id=%s turn=%d topic=%s", session_id, turn_count, turn_classification.get("topic"))
    preferences = dict(previous_preferences)
    preferences["turn_count"] = int(preferences.get("turn_count", 0)) + 1
    preferences["last_turn_type"] = "free_question"
    preferences["last_question_topic"] = turn_classification.get("topic")
    preferences["conversation_mode"] = "answering_question"
    if session.generated_itinerary_id is not None and not preferences.get("active_itinerary_id"):
        preferences["active_itinerary_id"] = str(session.generated_itinerary_id)
        logger.debug("Active itinerary set from generated_itinerary_id=%s", session.generated_itinerary_id)

    active_itinerary = await load_active_itinerary_from_preferences(db, current_user, preferences)
    if active_itinerary is not None:
        step_poi_ids = [s.poi_id for s in active_itinerary.steps]
        candidate_pois = await poi_repository.get_pois_by_ids(db, step_poi_ids) if step_poi_ids else []
        logger.debug("Loaded %d POIs from active itinerary for free question", len(candidate_pois))
    else:
        logger.debug("Searching POIs for free question query=%.100r", payload.message)
        candidate_pois = await search_candidate_pois(
            db,
            poi_repository,
            f"{session.initial_query}. {payload.message}",
            current_user,
            embedding_service,
            lat=session.lat,
            lon=session.lon,
            radius=session.radius,
            limit=8,
            embedding_cache=embedding_cache,
        )
        candidate_pois = filter_blacklisted_context_pois(payload.message, candidate_pois)

    logger.debug("Calling answer_free_question session_id=%s", session_id)
    chat_answer = await ara_chat_service.answer_free_question(
        user_message=payload.message,
        topic=str(turn_classification.get("topic") or "general"),
        preferences=preferences,
        candidate_pois=candidate_pois,
        active_itinerary=active_itinerary,
    )
    logger.debug("Free question answered used_context=%s evidence_level=%s", chat_answer.get("used_context"), chat_answer.get("evidence_level"))
    preferences = apply_memory_patch(preferences, chat_answer.get("memory_patch"))
    logger.debug("Memory patch applied session_id=%s", session_id)
    quick_replies = quick_replies_from_payload(chat_answer.get("quick_replies") or [])
    metadata = {
        **turn_classification,
        "used_context": chat_answer.get("used_context"),
        "evidence_level": chat_answer.get("evidence_level"),
    }

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
        logger.info(
            "Free question committed session_id=%s turn=%d status=%s",
            session_id, turn_count, session.status,
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to process free question session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(previous_intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=_build_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
    )


async def _handle_replacement_request(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    embedding_service: OpenAIEmbeddingService,
    intent: dict[str, Any],
    preferences: dict[str, Any],
    effective_lat: float | None,
    effective_lon: float | None,
    effective_radius: float | None,
    replacement_request: dict[str, UUID],
    session_id: UUID,
    turn_count: int,
) -> AraSessionResponse:
    logger.info(
        "Replacement request in general turn session_id=%s itinerary_id=%s step_id=%s",
        session_id, replacement_request.get("itinerary_id"), replacement_request.get("step_id"),
    )
    context = await build_step_replacement_context(
        db,
        current_user,
        itinerary_id=replacement_request["itinerary_id"],
        step_id=replacement_request["step_id"],
    )
    if context is None:
        logger.warning("Replacement context not found session_id=%s", session_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

    _itinerary_title, step, current_poi = context
    logger.info("Searching replacement alternatives for poi=%s session_id=%s", current_poi.name, session_id)
    candidate_pois = await search_step_replacement_alternatives(
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
        "current_poi_name": current_poi.name,
    }
    quick_replies = build_replacement_quick_replies(candidate_pois, replacement_request["step_id"])
    assistant_text = build_replacement_message(current_poi.name, candidate_pois)

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
        logger.info(
            "Step replacement suggested session_id=%s turn=%d candidates=%d",
            session_id, turn_count, len(candidate_pois),
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to suggest step replacement session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=_build_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
    )


async def _handle_refinement(
    db: AsyncSession,
    session: Any,
    current_user: User,
    payload: AraMessageCreate,
    embedding_service: OpenAIEmbeddingService,
    embedding_cache: EmbeddingCache,
    intent: dict[str, Any],
    preferences: dict[str, Any],
    effective_lat: float | None,
    effective_lon: float | None,
    effective_radius: float | None,
    search_center_metadata: dict[str, Any],
    strict_destination: bool,
    session_id: UUID,
    turn_count: int,
    turn_classification: dict[str, Any],
) -> AraSessionResponse:
    query_for_search = f"{session.initial_query}. {payload.message}"
    logger.debug("Searching POIs for general turn session_id=%s query=%.100r", session_id, query_for_search)
    candidate_pois = await search_candidate_pois(
        db,
        poi_repository,
        query_for_search,
        current_user,
        embedding_service,
        lat=effective_lat,
        lon=effective_lon,
        radius=effective_radius,
        embedding_cache=embedding_cache,
    )
    candidate_pois = filter_blacklisted_context_pois(query_for_search, candidate_pois)
    if not candidate_pois and session.candidate_poi_ids:
        logger.info("No POIs found via search, falling back to session candidate POIs session_id=%s", session_id)
        candidate_pois = await poi_repository.get_pois_by_ids(db, _candidate_uuid_list(session.candidate_poi_ids))
        if strict_destination:
            candidate_pois = filter_pois_to_search_center(
                candidate_pois,
                lat=effective_lat,
                lon=effective_lon,
                radius=effective_radius,
            )
        candidate_pois = filter_blacklisted_context_pois(query_for_search, candidate_pois)
        logger.debug("Fallback returned %d candidates session_id=%s", len(candidate_pois), session_id)
    candidate_pois = await maybe_diversify_candidate_pois(
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
        embedding_cache=embedding_cache,
    )
    logger.debug("After diversification: %d candidates session_id=%s", len(candidate_pois), session_id)
    candidate_pois = finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=query_for_search,
    )
    logger.debug("After finalize: %d candidates session_id=%s", len(candidate_pois), session_id)
    preferences = remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )

    status_value = "ready_to_generate" if preferences.get("auto_generate_requested") else "clarifying"
    logger.debug("Status transition session_id=%s status=%s", session_id, status_value)
    quick_replies = build_quick_replies(intent, preferences)
    quick_replies = (
        destination_scope_quick_replies(search_center_metadata, local_result_count=len(candidate_pois))
        + quick_replies
    )
    assistant_text = build_assistant_message(
        intent,
        preferences,
        candidate_pois,
        is_first_turn=False,
    )
    if strict_destination:
        assistant_text += destination_scope_message_suffix(
            search_center_metadata,
            local_result_count=len(candidate_pois),
        )

    try:
        session = await _update_session_with_retry(
            ara_repository, db, session, current_user.id,
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
        logger.info(
            "General turn committed session_id=%s turn=%d status=%s candidates=%d",
            session_id, turn_count, session.status, len(candidate_pois),
        )
    except Exception:
        await db.rollback()
        logger.exception("Failed to process general turn session_id=%s", session_id)
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=_build_intent_info(intent, preferences),
        preferences=_build_preference_summary(preferences),
        candidate_pois=_build_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
        active_itinerary_id=_extract_active_itinerary_id(preferences),
        destination_context=search_center_metadata,
    )


async def handle_message(
    db: AsyncSession,
    current_user: User,
    session_id: UUID,
    payload: AraMessageCreate,
    embedding_service: OpenAIEmbeddingService,
    ara_chat_service: Any,
) -> AraSessionResponse:
    from app.services.ara_chat_service import AraChatService

    embedding_cache = EmbeddingCache(embedding_service)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        logger.warning("Session not found session_id=%s user_id=%s", session_id, current_user.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    previous_intent = session.intent_data or {}
    previous_preferences = session.preferences_data or {}
    turn_count = int(previous_preferences.get("turn_count", 0)) + 1
    logger.info(
        "Message received session_id=%s user_id=%s turn=%d message=%.100r",
        session_id, current_user.id, turn_count, payload.message,
    )

    replace_selection = extract_replace_selection(payload.message, previous_preferences)
    if replace_selection is not None:
        return await _handle_replace_selection(
            db, session, current_user, payload, session_id,
            replace_selection, previous_preferences, previous_intent,
        )

    llm_client = _ensure_classifier_llm_client()
    session_context = {
        "previous_messages": [
            {"role": m.role, "content": m.content}
            for m in (session.messages or [])[-6:]
        ],
    } if session.messages else None

    turn_classification = await classify_turn(
        payload.message, previous_intent, previous_preferences,
        llm_client=llm_client, session_context=session_context,
    )
    logger.info(
        "Turn classified session_id=%s turn=%d turn_type=%s",
        session_id, turn_count, turn_classification.get("turn_type"),
    )

    turn_type = turn_classification["turn_type"]

    if turn_type == "candidate_selection":
        selected_poi_id = extract_candidate_selection(payload.message)
        if selected_poi_id is None:
            logger.warning(
                "Candidate selection classified but no UUID found session_id=%s message=%.100r",
                session_id, payload.message,
            )
            turn_type = "refinement"
            turn_classification["turn_type"] = "refinement"
        else:
            selected_poi = await poi_repository.get_poi_by_id(db, selected_poi_id)
            if selected_poi is None:
                logger.warning("Selected POI not found poi_id=%s", selected_poi_id)
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected POI not found.")
            return await _handle_candidate_selection(
                db, session, current_user, payload, session_id, turn_count,
                turn_classification, selected_poi_id, selected_poi,
                previous_preferences, previous_intent, llm_client,
            )

    if turn_type == "reset_or_new_trip":
        return await _handle_reset_or_new_trip(
            db, session, current_user, payload, embedding_service,
            embedding_cache, session_id, turn_count, turn_classification, llm_client,
        )

    if turn_type == "generate_request":
        return await _handle_generate_request(
            db, session, current_user, payload, previous_preferences, previous_intent,
            session_id, turn_count, turn_classification, llm_client,
        )

    if turn_type == "free_question":
        return await _handle_free_question(
            db, session, current_user, payload, ara_chat_service,
            embedding_service, embedding_cache, previous_preferences,
            previous_intent, session_id, turn_count, turn_classification,
        )

    replacement_request = extract_itinerary_step_context(payload.message)
    intent = await analyze_intent(payload.message, previous_intent, llm_client=llm_client)
    logger.debug("Intent for general turn session_id=%s: %s", session_id, intent)
    preferences = merge_preferences(
        payload.message,
        previous_preferences,
        turn_classification=turn_classification,
    )
    start_date, end_date = normalize_dates(session.start_date, session.end_date)
    preferences = update_trip_draft_from_message(
        payload.message,
        preferences,
        intent,
        start_date=start_date,
        end_date=end_date,
        payload_lat=session.lat,
        payload_lon=session.lon,
    )
    logger.debug("Trip draft updated for general turn session_id=%s", session_id)
    effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
        payload.message,
        fallback_lat=session.lat,
        fallback_lon=session.lon,
        fallback_radius=session.radius,
    )
    logger.info(
        "Search context for general turn session_id=%s lat=%s lon=%s radius=%s source=%s",
        session_id, effective_lat, effective_lon, effective_radius, search_center_metadata.get("source"),
    )
    existing_search_center = (preferences.get("trip_draft") or {}).get("search_center") or {}
    if (
        wants_expanded_destination_scope(payload.message)
        and search_center_metadata.get("source") == "payload"
        and existing_search_center.get("label")
    ):
        effective_radius = max(effective_radius or 0, 60_000)
        search_center_metadata = {
            **search_center_metadata,
            "source": "expanded_destination",
            "label": existing_search_center.get("label"),
        }
        logger.info("Expanded destination scope session_id=%s radius=%d", session_id, effective_radius)
    inherited_strict, inherited_metadata = inherits_strict_destination_context(
        preferences,
        search_center_metadata,
        payload.message,
    )
    if inherited_strict:
        search_center_metadata = inherited_metadata
        logger.debug("Inherited strict destination context session_id=%s", session_id)
    strict_destination = inherited_strict or is_strict_destination_context(
        search_center_metadata,
        payload.message,
    )
    logger.debug("Strict destination: %s session_id=%s", strict_destination, session_id)
    if search_center_metadata.get("source") != "payload" or not existing_search_center.get("label"):
        preferences = apply_search_center(
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
        return await _handle_replacement_request(
            db, session, current_user, payload, embedding_service,
            intent, preferences, effective_lat, effective_lon, effective_radius,
            replacement_request, session_id, turn_count,
        )

    return await _handle_refinement(
        db, session, current_user, payload, embedding_service,
        embedding_cache, intent, preferences, effective_lat, effective_lon,
        effective_radius, search_center_metadata, strict_destination,
        session_id, turn_count, turn_classification,
    )


async def generate_itinerary_from_session(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
) -> AraGenerateItineraryResponse:
    import time as _time
    _phase_start = _time.monotonic()
    logger.info("Itinerary generation START session_id=%s user_id=%s", session_id, current_user.id)
    if current_user.tourist_profile is None:
        logger.warning("Non-tourist user tried to generate itinerary user_id=%s", current_user.id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only tourist users can use Ara.")

    embedding_cache = EmbeddingCache(embedding_service)

    session = await ara_repository.get_session(db, session_id, current_user.id)
    if session is None:
        logger.warning("Session not found for generation session_id=%s", session_id)
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
        logger.warning("Missing search center for generation session_id=%s", session_id)
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
    logger.debug("Refined query built session_id=%s query=%.100r", session_id, refined_query)
    search_query = refined_query
    if preferences_data.get("surprise_route_requested"):
        search_query += (
            "\nRuta sorpresa equilibrada: recuperar un pool diverso, no solo lugares gastronómicos. "
            "Incluir naturaleza, cultura, miradores, descanso, actividades suaves y gastronomía."
        )
        logger.info("Surprise route activated session_id=%s", session_id)
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
        logger.debug("Loaded %d session context POIs session_id=%s", len(session_context_pois), session_id)
    logger.info("Phase: searching POIs with fallbacks session_id=%s", session_id)
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
        logger.warning(
            "No context POIs found for generation session_id=%s strict=%s label=%s",
            session_id, strict_destination, scope_label,
        )
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
        f"Duración: {num_days} día(s)"
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
        logger.debug("Weather fetched session_id=%s", session_id)
    except ValueError as exc:
        logger.error("Weather forecast failed (invalid data) session_id=%s: %s", session_id, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("Weather forecast HTTP error session_id=%s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather forecast provider failed while generating the itinerary.",
        ) from exc

    _phase_weather = _time.monotonic()
    logger.info(
        "Phase: weather ready session_id=%s elapsed=%.2fs",
        session_id, _phase_weather - _phase_start,
    )
    logger.info("Phase: calling LLM for itinerary generation session_id=%s", session_id)
    await ara_repository.update_session_context(db, session, status="generating")
    await ara_repository.commit_or_rollback(db)
    logger.debug("Status updated to 'generating' session_id=%s", session_id)

    generated_raw = await llm_service.generate_itinerary(
        enriched_query,
        context_pois,
        weather_forecast,
        schedule_guidance,
    )
    _phase_llm = _time.monotonic()
    logger.info(
        "Phase: LLM response received session_id=%s elapsed=%.2fs",
        session_id, _phase_llm - _phase_weather,
    )
    generated_itinerary = GeneratedItinerary.model_validate(generated_raw)
    generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, generation_payload)
    generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

    logger.info("Phase: validating LLM output session_id=%s steps=%d", session_id, len(generated_itinerary.steps))
    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        logger.error(
            "LLM returned POIs outside context session_id=%s invalid=%s",
            session_id, [str(pid) for pid in invalid_poi_ids],
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The LLM returned POIs outside Ara context.")
    if not generated_itinerary.steps:
        logger.error("LLM returned no steps session_id=%s", session_id)
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
    logger.debug("Preferences after generation session_id=%s: %s", session_id, preferences)

    _phase_end = _time.monotonic()
    logger.info(
        "Itinerary generation COMPLETE session_id=%s itinerary_id=%s total_elapsed=%.2fs",
        session_id, itinerary.id, _phase_end - _phase_start,
    )

    return AraGenerateItineraryResponse(session_id=session_id, status="completed", itinerary=itinerary)


async def _get_user_for_background_job(db: AsyncSession, user_id: UUID) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.tourist_profile))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def run_ara_itinerary_generation_job(
    session_id: UUID,
    tourist_id: UUID,
    payload: AraGenerateItineraryRequest | None,
) -> None:
    import time as _time
    _job_start = _time.monotonic()
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
                session_id, _time.monotonic() - _job_start,
            )
        except Exception:
            await db.rollback()
            logger.exception("Background job FAILED session_id=%s", session_id)
            session = await ara_repository.get_session(db, session_id, tourist_id)
            if session is None:
                return
            await ara_repository.update_session_context(db, session, status="failed")
            logger.info("Session status set to 'failed' session_id=%s", session_id)
            await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                AraMessages.get("session_generation_failed"),
                metadata={
                    "generation_error": True,
                },
            )
            await ara_repository.commit_or_rollback(db)
