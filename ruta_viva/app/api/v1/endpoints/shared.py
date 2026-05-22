from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.itinerary import ItineraryExportResponse


router = APIRouter(tags=["shared"])
itinerary_repository = ItineraryRepository()


@router.get("/{public_id}", response_model=ItineraryExportResponse)
async def get_shared_itinerary(
    public_id: str,
    db: AsyncSession = Depends(get_db),
) -> ItineraryExportResponse:
    export_data = await itinerary_repository.get_export_data_by_public_id(
        db, public_id=public_id,
    )
    if export_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared itinerary not found.",
        )

    return export_data
