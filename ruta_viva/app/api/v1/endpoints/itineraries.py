from datetime import date, time, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.itinerary import (
    GenerateItineraryRequest,
    GeneratedItinerary,
    ItineraryResponse,
    ItineraryStepUpdate,
    ReorderItineraryStepsRequest,
)
from app.schemas.poi import POIResponse
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
from app.services.weather_service import get_forecast


router = APIRouter(tags=["itineraries"])
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()

INFORMATION_CATEGORY_ID = 13
EXPLICIT_INFORMATION_TERMS = ("conaf", "información", "informacion", "oficina", "centro de visitantes", "planificar")


def _trip_days(payload: GenerateItineraryRequest) -> int:
    return (payload.end_date - payload.start_date).days + 1


def _asks_for_information(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in EXPLICIT_INFORMATION_TERMS)


def _prepare_context_pois(
    query: str,
    context_pois: list,
    max_pois: int,
) -> list:
    if _asks_for_information(query):
        return context_pois[:max_pois]

    primary_pois = [poi for poi in context_pois if INFORMATION_CATEGORY_ID not in poi.category_ids]
    fallback_information = [poi for poi in context_pois if INFORMATION_CATEGORY_ID in poi.category_ids]
    return (primary_pois + fallback_information)[:max_pois]


def _build_schedule_guidance(payload: GenerateItineraryRequest) -> str:
    days: list[str] = []
    current_date = payload.start_date
    while current_date <= payload.end_date:
        days.append(
            f"{current_date.isoformat()}: mañana 09:00-13:00, almuerzo/descanso 13:00-14:30, "
            "tarde 14:30-18:00, noche opcional 19:00-21:00 solo para gastronomía, cultura urbana, "
            "termas/bienestar o POIs con night_suitable=true."
        )
        current_date += timedelta(days=1)

    return (
        "Genera pasos distribuidos en los días del viaje. Evita huecos grandes sin explicación. "
        "No programes actividades outdoor con requires_daylight=true en la noche. "
        "Si faltan datos de horario, usa criterio conservador sin inventar prohibiciones absolutas.\n"
        + "\n".join(days)
    )


def _parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":", maxsplit=1)
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError):
        return None


def _validate_generated_itinerary_rules(
    generated_itinerary: GeneratedItinerary,
    context_pois: list,
    payload: GenerateItineraryRequest,
) -> None:
    poi_by_id = {poi.id: poi for poi in context_pois}
    explicit_information_request = _asks_for_information(payload.query)

    steps_by_date: dict[date, list] = {}
    for step in generated_itinerary.steps:
        poi = poi_by_id.get(step.poi_id)
        if poi is None:
            continue

        if INFORMATION_CATEGORY_ID in poi.category_ids and not explicit_information_request:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM selected an information/office POI as a main stop without explicit user intent.",
            )

        if step.arrival_time is None or step.departure_time is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary step without arrival_time or departure_time.",
            )

        if step.arrival_time.date() < payload.start_date or step.arrival_time.date() > payload.end_date:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary step outside the requested date range.",
            )
        steps_by_date.setdefault(step.arrival_time.date(), []).append(step)

        if step.departure_time <= step.arrival_time:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM returned an itinerary step with invalid time ordering.",
            )

        visit_rules = poi.visit_rules or {}
        night_suitable = bool(visit_rules.get("night_suitable"))
        latest_start = _parse_hhmm(visit_rules.get("latest_recommended_start_time"))
        requires_daylight = bool(visit_rules.get("requires_daylight"))

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


@router.get("/", response_model=list[ItineraryResponse])
async def list_my_itineraries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ItineraryResponse]:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can list itineraries.",
        )

    return await itinerary_repository.list_itineraries_by_tourist(
        db,
        tourist_id=current_user.id,
    )


@router.post("/generate", response_model=ItineraryResponse, status_code=status.HTTP_201_CREATED)
async def generate_itinerary(
    payload: GenerateItineraryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
    llm_service: ItineraryGenerator = Depends(get_itinerary_generator),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can generate itineraries.",
        )

    query_embedding = await embedding_service.get_embedding(payload.query)
    trip_days = _trip_days(payload)
    retrieval_limit = min(35, max(8, trip_days * 6))
    context_pois = await poi_repository.search_hybrid(
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

    context_pois = _prepare_context_pois(
        query=payload.query,
        context_pois=context_pois,
        max_pois=retrieval_limit,
    )

    enriched_query = (
        f"Solicitud del usuario: {payload.query}\n"
        f"Fechas del viaje: desde {payload.start_date.isoformat()} hasta {payload.end_date.isoformat()}\n"
        f"Ubicación de referencia: lat={payload.lat}, lon={payload.lon}\n"
        f"Radio máximo: {payload.radius} metros\n"
        f"Duración: {trip_days} día(s)"
    )
    schedule_guidance = _build_schedule_guidance(payload)

    try:
        weather_forecast = await get_forecast(
            payload.lat,
            payload.lon,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
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

    _validate_generated_itinerary_rules(
        generated_itinerary=generated_itinerary,
        context_pois=context_pois,
        payload=payload,
    )

    return await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        generated_itinerary=generated_itinerary,
    )


@router.get("/{itinerary_id}/pois", response_model=list[POIResponse])
async def get_my_itinerary_pois(
    itinerary_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[POIResponse]:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can read itinerary POIs.",
        )

    pois = await itinerary_repository.list_pois_for_itinerary(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
    )
    if pois is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Itinerary not found.",
        )

    return pois


@router.patch("/{itinerary_id}/steps/reorder", response_model=ItineraryResponse)
async def reorder_my_itinerary_steps(
    itinerary_id: UUID,
    payload: ReorderItineraryStepsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can edit itinerary steps.",
        )

    try:
        itinerary = await itinerary_repository.reorder_steps(
            db,
            itinerary_id=itinerary_id,
            tourist_id=current_user.id,
            step_ids=payload.step_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")

    return itinerary


@router.patch("/{itinerary_id}/steps/{step_id}", response_model=ItineraryResponse)
async def update_my_itinerary_step(
    itinerary_id: UUID,
    step_id: UUID,
    payload: ItineraryStepUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can edit itinerary steps.",
        )

    try:
        itinerary = await itinerary_repository.update_step(
            db,
            itinerary_id=itinerary_id,
            tourist_id=current_user.id,
            step_id=step_id,
            step_in=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

    return itinerary


@router.delete("/{itinerary_id}/steps/{step_id}", response_model=ItineraryResponse)
async def delete_my_itinerary_step(
    itinerary_id: UUID,
    step_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can edit itinerary steps.",
        )

    itinerary = await itinerary_repository.delete_step(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
        step_id=step_id,
    )
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

    return itinerary


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_itinerary(
    itinerary_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can delete itineraries.",
        )

    deleted = await itinerary_repository.delete_itinerary(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")

    return None


@router.get("/{itinerary_id}", response_model=ItineraryResponse)
async def get_my_itinerary(
    itinerary_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can read itineraries.",
        )

    itinerary = await itinerary_repository.get_itinerary_by_id(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
    )
    if itinerary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Itinerary not found.",
        )

    return itinerary
