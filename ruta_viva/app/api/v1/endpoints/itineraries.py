from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, ItineraryResponse
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
from app.services.weather_service import get_forecast


router = APIRouter(tags=["itineraries"])
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


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
    context_pois = await poi_repository.search_hybrid(
        db,
        lat=payload.lat,
        lon=payload.lon,
        radius_meters=payload.radius,
        query_embedding=query_embedding,
        user_interests_embedding=current_user.tourist_profile.interests_embedding,
    )

    if not context_pois:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No relevant POIs were found for itinerary generation.",
        )

    enriched_query = (
        f"Solicitud del usuario: {payload.query}\n"
        f"Fechas del viaje: desde {payload.start_date.isoformat()} hasta {payload.end_date.isoformat()}\n"
        f"Ubicación de referencia: lat={payload.lat}, lon={payload.lon}\n"
        f"Radio máximo: {payload.radius} metros"
    )

    try:
        weather_forecast = await get_forecast(payload.lat, payload.lon)
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

    return await itinerary_repository.create_generated_itinerary(
        db,
        tourist_id=current_user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        generated_itinerary=generated_itinerary,
    )


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
