from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.itinerary import (
    GenerateItineraryRequest,
    ItineraryResponse,
    ItineraryStepUpdate,
    ItineraryStepWeatherResponse,
    PaginatedItineraryResponse,
    ReorderItineraryStepsRequest,
    ReorderStepsWithTimesRequest,
    RescheduleStepRequest,
)
from app.schemas.poi import POIResponse
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.itinerary_generation_service import generate_itinerary_from_request
from app.services.itinerary_weather_service import get_itinerary_step_weather
from app.services.llm_service import ItineraryGenerator, get_itinerary_generator
import app.services.weather_service as weather_service_module


router = APIRouter(tags=["itineraries"])
poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


@router.get("/", response_model=PaginatedItineraryResponse)
async def list_my_itineraries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can list itineraries.",
        )

    offset = (page - 1) * page_size
    items = await itinerary_repository.list_itineraries_by_tourist(
        db, tourist_id=current_user.id, offset=offset, limit=page_size,
    )
    total = await itinerary_repository.count_itineraries_by_tourist(
        db, tourist_id=current_user.id,
    )
    total_pages = (total + page_size - 1) // page_size

    return PaginatedItineraryResponse(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages,
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

    return await generate_itinerary_from_request(
        db, payload, current_user, embedding_service, llm_service,
        poi_repository, itinerary_repository, weather_service_module,
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


@router.post("/{itinerary_id}/steps", response_model=ItineraryResponse, status_code=status.HTTP_201_CREATED)
async def add_my_itinerary_step(
    itinerary_id: UUID,
    payload: ItineraryStepCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can add itinerary steps.",
        )

    try:
        itinerary = await itinerary_repository.add_step(
            db,
            itinerary_id=itinerary_id,
            tourist_id=current_user.id,
            step_data=payload,
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


@router.patch("/{itinerary_id}/status", response_model=ItineraryResponse)
async def update_my_itinerary_status(
    itinerary_id: UUID,
    payload: ItineraryStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can update itinerary status.",
        )

    itinerary = await itinerary_repository.update_status(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
        new_status=payload.status,
    )
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")

    return itinerary


@router.patch("/{itinerary_id}/steps/{step_id}/reschedule", response_model=ItineraryResponse)
async def reschedule_my_itinerary_step(
    itinerary_id: UUID,
    step_id: UUID,
    payload: RescheduleStepRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can edit itinerary steps.",
        )

    itinerary = await itinerary_repository.reschedule_step(
        db,
        itinerary_id=itinerary_id,
        tourist_id=current_user.id,
        step_id=step_id,
        payload=payload,
    )
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary or step not found.")

    return itinerary


@router.patch("/{itinerary_id}/steps/reorder-with-times", response_model=ItineraryResponse)
async def reorder_my_itinerary_steps_with_times(
    itinerary_id: UUID,
    payload: ReorderStepsWithTimesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItineraryResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can edit itinerary steps.",
        )

    try:
        itinerary = await itinerary_repository.reorder_steps_with_times(
            db,
            itinerary_id=itinerary_id,
            tourist_id=current_user.id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")

    return itinerary


@router.get("/{itinerary_id}/weather", response_model=list[ItineraryStepWeatherResponse])
async def get_my_itinerary_weather(
    itinerary_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ItineraryStepWeatherResponse]:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can access itinerary weather.",
        )

    return await get_itinerary_step_weather(
        db, itinerary_id, current_user.id, itinerary_repository, weather_service_module,
    )
