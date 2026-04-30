from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.poi_repository import POIRepository
from app.schemas.poi import POICreate, POIResponse


router = APIRouter(tags=["pois"])
poi_repository = POIRepository()


@router.post("/", response_model=POIResponse, status_code=status.HTTP_201_CREATED)
async def create_poi(
    payload: POICreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> POIResponse:
    entrepreneur_id = current_user.id if getattr(current_user, "entrepreneur_profile", None) is not None else None
    return await poi_repository.create_poi(db, payload, entrepreneur_id=entrepreneur_id)


@router.get("/search", response_model=list[POIResponse])
async def search_nearby_pois(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(5000, gt=0),
    db: AsyncSession = Depends(get_db),
) -> list[POIResponse]:
    return await poi_repository.get_pois_nearby(db, lat=lat, lon=lon, radius_meters=radius)
