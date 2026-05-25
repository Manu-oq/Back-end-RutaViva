from __future__ import annotations

import logging
from datetime import date
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary
from app.services.ara_response_builder import build_refined_query
from app.services.embedding_service import EmbeddingCache, OpenAIEmbeddingService
from app.services.itinerary_generation_service import (
    build_schedule_guidance,
    merge_unique_context_pois,
    normalize_generated_itinerary_times,
    prepare_context_pois,
    repair_duplicate_poi_steps,
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


def normalize_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    normalized_start = start_date or date.today()
    normalized_end = end_date or normalized_start
    return normalized_start, normalized_end


def _candidate_uuid_list(candidate_poi_ids: list[UUID] | list[str] | None) -> list[UUID]:
    return [
        poi_id if isinstance(poi_id, UUID) else UUID(str(poi_id))
        for poi_id in (candidate_poi_ids or [])
    ]


async def stream_itinerary_generation(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
) -> AsyncGenerator[dict[str, Any], None]:
    try:
        if current_user.tourist_profile is None:
            yield {"event": "error", "data": {"message": "Only tourist users can use Ara."}}
            return

        embedding_cache = EmbeddingCache(embedding_service)

        session = await ara_repository.get_session(db, session_id, current_user.id)
        if session is None:
            yield {"event": "error", "data": {"message": "Ara session not found."}}
            return

        preferences_data = session.preferences_data or {}
        trip_draft = preferences_data.get("trip_draft") or {}
        search_center = trip_draft.get("search_center") if isinstance(trip_draft, dict) else {}
        effective_lat = session.lat
        effective_lon = session.lon
        if (effective_lat is None or effective_lon is None) and isinstance(search_center, dict):
            effective_lat = search_center.get("lat")
            effective_lon = search_center.get("lon")

        if effective_lat is None or effective_lon is None:
            yield {
                "event": "error",
                "data": {"message": "Ara needs a destination/search center before generating an itinerary."},
            }
            return

        yield {"event": "status", "data": {"phase": "searching", "message": "Buscando lugares..."}}

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
            yield {"event": "error", "data": {"message": detail}}
            return

        yield {"event": "status", "data": {"phase": "weather", "message": "Consultando el clima..."}}

        try:
            weather_forecast = await get_forecast(
                generation_payload.lat,
                generation_payload.lon,
                start_date=start_date,
                end_date=end_date,
            )
        except ValueError as exc:
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        except httpx.HTTPError:
            yield {
                "event": "error",
                "data": {"message": "Weather forecast provider failed while generating the itinerary."},
            }
            return

        yield {"event": "status", "data": {"phase": "generating", "message": "Armando tu itinerario con IA..."}}

        enriched_query = (
            f"Solicitud refinada por conversación con Ara: {refined_query}\n"
            f"Fechas del viaje: desde {start_date.isoformat()} hasta {end_date.isoformat()}\n"
            f"Ubicación de referencia: lat={generation_payload.lat}, lon={generation_payload.lon}\n"
            f"Radio máximo: {generation_payload.radius} metros\n"
            f"Duración: {num_days} día(s)"
        )
        schedule_guidance = build_schedule_guidance(generation_payload)

        await ara_repository.update_session_context(db, session, status="generating")
        await ara_repository.commit_or_rollback(db)

        try:
            generated_raw = await llm_service.generate_itinerary(
                enriched_query,
                context_pois,
                weather_forecast,
                schedule_guidance,
            )
        except ValueError as exc:
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        generated_itinerary = GeneratedItinerary.model_validate(generated_raw)

        yield {"event": "status", "data": {"phase": "validating", "message": "Verificando horarios y calidad..."}}

        generated_itinerary = normalize_generated_itinerary_times(generated_itinerary, generation_payload)
        generated_itinerary = repair_duplicate_poi_steps(generated_itinerary, context_pois, generation_payload)
        generated_itinerary = repair_schedule_and_category_issues(generated_itinerary, context_pois, generation_payload)

        valid_poi_ids = {poi.id for poi in context_pois}
        invalid_poi_ids = [step.poi_id for step in generated_itinerary.steps if step.poi_id not in valid_poi_ids]
        if invalid_poi_ids:
            yield {"event": "error", "data": {"message": "Ara recibió lugares fuera del contexto disponible. Intenta regenerar o ajustar la búsqueda."}}
            return
        if not generated_itinerary.steps:
            yield {"event": "error", "data": {"message": "Ara no devolvió actividades para el itinerario. Intenta ajustar la búsqueda o ampliar las opciones."}}
            return

        validate_generated_itinerary_rules(generated_itinerary, context_pois, generation_payload)
        generated_itinerary = sanitize_generated_itinerary_context(generated_itinerary)

        yield {"event": "status", "data": {"phase": "saving", "message": "Guardando..."}}

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

        yield {
            "event": "result",
            "data": AraGenerateItineraryResponse(
                session_id=session_id, status="completed", itinerary=itinerary
            ).model_dump(mode="json"),
        }

    except Exception:
        logger.exception("Streaming itinerary generation failed unexpectedly.")
        yield {"event": "error", "data": {"message": "Ocurrió un error inesperado generando el itinerario."}}
