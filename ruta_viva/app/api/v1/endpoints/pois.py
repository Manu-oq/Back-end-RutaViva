from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.poi_repository import POIRepository
from app.schemas.poi import POICreate, POIResponse
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service


router = APIRouter(tags=["pois"])
poi_repository = POIRepository()


@router.post("/", response_model=POIResponse, status_code=status.HTTP_201_CREATED)
async def create_poi(
    payload: POICreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> POIResponse:
    entrepreneur_id = current_user.id if getattr(current_user, "entrepreneur_profile", None) is not None else None
    text = f"{payload.nombre}. {payload.descripcion}"
    embedding = await embedding_service.get_embedding(text)
    return await poi_repository.create_poi(db, payload, entrepreneur_id=entrepreneur_id, embedding=embedding)


@router.get("/search", response_model=list[POIResponse])
async def search_nearby_pois(
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(5000, gt=0),
    db: AsyncSession = Depends(get_db),
) -> list[POIResponse]:
    return await poi_repository.get_pois_nearby(db, lat=lat, lon=lon, radius_meters=radius)


@router.get("/semantic-search", response_model=list[POIResponse])
async def semantic_search_pois(
    query: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(5000, gt=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> list[POIResponse]:
    query_embedding = await embedding_service.get_embedding(query)
    user_interests_embedding = (
        current_user.tourist_profile.interests_embedding
        if current_user is not None and current_user.tourist_profile is not None
        else None
    )
    return await poi_repository.search_hybrid(
        db,
        lat=lat,
        lon=lon,
        radius_meters=radius,
        query_embedding=query_embedding,
        user_interests_embedding=user_interests_embedding,
    )
