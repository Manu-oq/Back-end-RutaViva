from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.ara_message import AraMessage
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import (
    AraGenerateItineraryRequest,
    AraGenerateItineraryResponse,
    AraMessageCreate,
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
    compact_candidate_pois,
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
    return merge_unique_context_pois(candidate_pois, diversified, max_pois=12)


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
    return [poi for poi in alternatives if poi.id != current_poi.id][:5]


def extract_replacement_request_from_metadata(metadata: dict | None) -> dict[str, UUID] | None:
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
        return None
    return await itinerary_repository.get_itinerary_by_id(db, itinerary_id, current_user.id)


def quick_replies_from_payload(payload: list[dict]) -> list[AraQuickReply]:
    replies: list[AraQuickReply] = []
    for item in payload:
        try:
            replies.append(AraQuickReply.model_validate(item))
        except Exception:
            continue
    return replies


async def create_session(
    db: AsyncSession,
    current_user: User,
    payload: AraSessionCreate,
    embedding_service: OpenAIEmbeddingService,
) -> AraSessionResponse:
    embedding_cache = EmbeddingCache(embedding_service)
    intent = analyze_intent(payload.initial_message)
    preferences = merge_preferences(payload.initial_message)
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
    effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
        payload.initial_message,
        fallback_lat=payload.lat,
        fallback_lon=payload.lon,
        fallback_radius=payload.radius,
    )
    strict_destination = is_strict_destination_context(search_center_metadata, payload.initial_message)
    existing_search_center = (preferences.get("trip_draft") or {}).get("search_center") or {}
    if search_center_metadata.get("source") != "payload" or not existing_search_center.get("label"):
        preferences = apply_search_center(
            preferences,
            lat=effective_lat,
            lon=effective_lon,
            source=str(search_center_metadata.get("source") or "payload"),
            label=search_center_metadata.get("label"),
        )
    replacement_request = (
        extract_replacement_request_from_metadata(payload.metadata)
        or extract_itinerary_step_context(payload.initial_message)
    )
    if replacement_request is not None:
        context = await build_step_replacement_context(
            db,
            current_user,
            itinerary_id=replacement_request["itinerary_id"],
            step_id=replacement_request["step_id"],
        )
        if context is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        _itinerary_title, _step, current_poi = context
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
        except Exception:
            await db.rollback()
            raise

        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=intent,
            preferences=preferences,
            candidate_pois=compact_candidate_pois(
                candidate_pois,
                replacement_step_id=replacement_request["step_id"],
            ),
            generated_itinerary_id=session.generated_itinerary_id,
        )

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
    candidate_pois = finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=payload.initial_message,
    )
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
    except Exception:
        await db.rollback()
        raise

    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=intent,
        preferences=preferences,
        candidate_pois=compact_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ara session not found.")

    previous_intent = session.intent_data or {}
    previous_preferences = session.preferences_data or {}

    replace_selection = extract_replace_selection(payload.message, previous_preferences)
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
            "para aprovechar al máximo este momento del día."
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

        assistant_text = (
            f"Listo, reemplacé esa parada por {chosen_poi.name}. "
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

        assistant_response = session_message_response(assistant_message)
        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=session_message_response(user_message),
            assistant_message=assistant_response,
            quick_replies=assistant_response.quick_replies,
            intent=previous_intent,
            preferences=previous_preferences,
            candidate_pois=compact_candidate_pois([chosen_poi]),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    turn_classification = classify_turn(payload.message, previous_intent, previous_preferences)

    if turn_classification["turn_type"] == "candidate_selection":
        selected_poi_id = extract_candidate_selection(payload.message)
        if selected_poi_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid candidate selection.")
        selected_poi = await poi_repository.get_poi_by_id(db, selected_poi_id)
        if selected_poi is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected POI not found.")

        intent = analyze_intent(f"Quiero ir a {selected_poi.name}", previous_intent)
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
        remaining_candidate_ids = [
            poi_id
            for poi_id in _candidate_uuid_list(session.candidate_poi_ids)
            if poi_id != selected_poi.id
        ]

        quick_replies = build_quick_replies(intent, preferences)
        selected_role = ((preferences.get("trip_draft") or {}).get("selected_pois") or [{}])[-1].get("role")
        if selected_role == "lodging":
            assistant_text = (
                f"Perfecto, guardaré {selected_poi.name} como alojamiento base probable del viaje. "
                "Si después quieres dormir en otra zona, dime el día o la noche y lo ajusto."
            )
        elif selected_role == "meal":
            assistant_text = (
                f"Perfecto, guardaré {selected_poi.name} como opción gastronómica y la ubicaré donde mejor calce. "
                "Si la quieres para un día específico, dime por ejemplo: lunes almuerzo o última noche."
            )
        else:
            assistant_text = (
                f"Perfecto, consideraré {selected_poi.name} dentro de la ruta. "
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
                    "selected_poi_name": selected_poi.name,
                },
            )
            await ara_repository.commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return AraSessionResponse(
            session_id=session.id,
            status=session.status,
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=intent,
            preferences=preferences,
            candidate_pois=[],
            generated_itinerary_id=session.generated_itinerary_id,
        )

    if turn_classification["turn_type"] == "reset_or_new_trip":
        intent = analyze_intent(payload.message)
        preferences = reset_trip_preferences(payload.message)
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
        effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
            payload.message,
            fallback_lat=session.lat,
            fallback_lon=session.lon,
            fallback_radius=session.radius,
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
        candidate_pois = finalize_candidate_pois(
            candidate_pois,
            intent=intent,
            preferences=preferences,
            query=payload.message,
        )
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
            "Perfecto, dejamos atrás el plan anterior y partimos con una idea nueva. "
            + build_assistant_message(intent, preferences, candidate_pois, is_first_turn=True)
        )
        if strict_destination:
            assistant_text += destination_scope_message_suffix(
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
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=intent,
            preferences=preferences,
            candidate_pois=compact_candidate_pois(candidate_pois),
            generated_itinerary_id=None,
        )

    if turn_classification["turn_type"] == "generate_request":
        intent = previous_intent or analyze_intent(session.initial_query)
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
        assistant_text = build_generate_request_message(preferences)

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
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=intent,
            preferences=preferences,
            candidate_pois=[],
            generated_itinerary_id=session.generated_itinerary_id,
        )

    if turn_classification["turn_type"] == "free_question":
        preferences = dict(previous_preferences)
        preferences["turn_count"] = int(preferences.get("turn_count", 0)) + 1
        preferences["last_turn_type"] = "free_question"
        preferences["last_question_topic"] = turn_classification.get("topic")
        preferences["conversation_mode"] = "answering_question"
        if session.generated_itinerary_id is not None and not preferences.get("active_itinerary_id"):
            preferences["active_itinerary_id"] = str(session.generated_itinerary_id)

        active_itinerary = await load_active_itinerary_from_preferences(db, current_user, preferences)
        if active_itinerary is not None:
            step_poi_ids = [s.poi_id for s in active_itinerary.steps]
            candidate_pois = await poi_repository.get_pois_by_ids(db, step_poi_ids) if step_poi_ids else []
        else:
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

        chat_answer = await ara_chat_service.answer_free_question(
            user_message=payload.message,
            topic=str(turn_classification.get("topic") or "general"),
            preferences=preferences,
            candidate_pois=candidate_pois,
            active_itinerary=active_itinerary,
        )
        preferences = apply_memory_patch(preferences, chat_answer.get("memory_patch"))
        quick_replies = quick_replies_from_payload(chat_answer.get("quick_replies") or [])
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
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=previous_intent,
            preferences=preferences,
            candidate_pois=compact_candidate_pois(candidate_pois),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    replacement_request = extract_itinerary_step_context(payload.message)
    intent = analyze_intent(payload.message, previous_intent)
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
    effective_lat, effective_lon, effective_radius, search_center_metadata = await resolve_effective_search_context(
        payload.message,
        fallback_lat=session.lat,
        fallback_lon=session.lon,
        fallback_radius=session.radius,
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
    inherited_strict, inherited_metadata = inherits_strict_destination_context(
        preferences,
        search_center_metadata,
        payload.message,
    )
    if inherited_strict:
        search_center_metadata = inherited_metadata
    strict_destination = inherited_strict or is_strict_destination_context(
        search_center_metadata,
        payload.message,
    )
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
        context = await build_step_replacement_context(
            db,
            current_user,
            itinerary_id=replacement_request["itinerary_id"],
            step_id=replacement_request["step_id"],
        )
        if context is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

        _itinerary_title, step, current_poi = context
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
            user_message=session_message_response(user_message),
            assistant_message=session_message_response(assistant_message),
            quick_replies=quick_replies,
            intent=intent,
            preferences=preferences,
            candidate_pois=compact_candidate_pois(candidate_pois),
            generated_itinerary_id=session.generated_itinerary_id,
        )

    query_for_search = f"{session.initial_query}. {payload.message}"
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
        candidate_pois = await poi_repository.get_pois_by_ids(db, _candidate_uuid_list(session.candidate_poi_ids))
        if strict_destination:
            candidate_pois = filter_pois_to_search_center(
                candidate_pois,
                lat=effective_lat,
                lon=effective_lon,
                radius=effective_radius,
            )
        candidate_pois = filter_blacklisted_context_pois(query_for_search, candidate_pois)
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
    candidate_pois = finalize_candidate_pois(
        candidate_pois,
        intent=intent,
        preferences=preferences,
        query=query_for_search,
    )
    preferences = remember_destination_scope(
        preferences,
        strict_destination=strict_destination,
        search_center_metadata=search_center_metadata,
        local_result_count=len(candidate_pois),
    )

    status_value = "ready_to_generate" if preferences.get("auto_generate_requested") else "clarifying"
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
        user_message=session_message_response(user_message),
        assistant_message=session_message_response(assistant_message),
        quick_replies=quick_replies,
        intent=intent,
        preferences=preferences,
        candidate_pois=compact_candidate_pois(candidate_pois),
        generated_itinerary_id=session.generated_itinerary_id,
    )


async def generate_itinerary_from_session(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
) -> AraGenerateItineraryResponse:
    from app.api.deps import get_current_user
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
            "\nRuta sorpresa equilibrada: recuperar un pool diverso, no solo lugares gastronómicos. "
            "Incluir naturaleza, cultura, miradores, descanso, actividades suaves y gastronomía."
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
        f"Duración: {num_days} día(s)"
    )
    schedule_guidance = build_schedule_guidance(generation_payload)

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
    generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, generation_payload)
    generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

    valid_poi_ids = {poi.id for poi in context_pois}
    invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
    if invalid_poi_ids:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The LLM returned POIs outside Ara context.")
    if not generated_itinerary.steps:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ara did not return itinerary steps.")

    validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)
    generated_itinerary = sanitize_generated_itinerary_context(generated_itinerary)

    itinerary = await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        generated_itinerary=generated_itinerary,
    )

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


async def run_ara_itinerary_generation_job(
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
            await generate_itinerary_from_session(
                session_id=session_id,
                payload=payload,
                db=db,
                current_user=current_user,
                embedding_service=get_embedding_service(),
                llm_service=get_itinerary_generator(),
            )
        except Exception:
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
                    "generation_error": True,
                },
            )
            await ara_repository.commit_or_rollback(db)
