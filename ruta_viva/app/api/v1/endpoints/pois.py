from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.poi_repository import POIRepository
from app.schemas.poi import POICreate, POIMediaAppend, POIResponse, POIUpdate
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service


router = APIRouter(tags=["pois"])
poi_repository = POIRepository()


def _ensure_can_manage_poi(current_user: User, entrepreneur_id: UUID | None) -> None:
    if current_user.entrepreneur_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only entrepreneur users can manage POIs.",
        )

    if entrepreneur_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner entrepreneur can manage this POI.",
        )


@router.post("/", response_model=POIResponse, status_code=status.HTTP_201_CREATED)
async def create_poi(
    payload: POICreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> POIResponse:
    entrepreneur_id = (
        current_user.id if getattr(current_user, "entrepreneur_profile", None) is not None else None
    )
    text = f"{payload.nombre}. {payload.descripcion}"
    embedding = await embedding_service.get_embedding(text)
    return await poi_repository.create_poi(
        db,
        payload,
        entrepreneur_id=entrepreneur_id,
        embedding=embedding,
    )


@router.get("/mine", response_model=list[POIResponse])
async def list_my_pois(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[POIResponse]:
    if current_user.entrepreneur_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only entrepreneur users can list owned POIs.",
        )

    return await poi_repository.get_pois_by_entrepreneur(db, entrepreneur_id=current_user.id)


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


@router.get("/{poi_id}", response_model=POIResponse)
async def get_poi_detail(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> POIResponse:
    poi = await poi_repository.get_poi_by_id(db, poi_id)
    if poi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    return poi


@router.patch("/{poi_id}/media", response_model=POIResponse)
async def append_poi_media(
    poi_id: UUID,
    payload: POIMediaAppend,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> POIResponse:
    current_poi = await poi_repository.get_poi_model_by_id(db, poi_id)
    if current_poi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    if (
        current_poi.entrepreneur_id is not None
        and current_poi.entrepreneur_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner entrepreneur can update this POI media.",
        )

    updated = await poi_repository.append_media_url(
        db,
        poi_id=poi_id,
        image_url=payload.image_url,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    return updated


@router.put("/{poi_id}", response_model=POIResponse)
async def update_poi(
    poi_id: UUID,
    payload: POIUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> POIResponse:
    current_poi = await poi_repository.get_poi_model_by_id(db, poi_id)
    if current_poi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    _ensure_can_manage_poi(current_user, current_poi.entrepreneur_id)

    if (payload.latitude is None) != (payload.longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Latitude and longitude must be provided together.",
        )

    embedding = None
    if payload.nombre is not None or payload.descripcion is not None:
        next_name = payload.nombre or current_poi.name
        next_description = payload.descripcion or current_poi.description
        embedding = await embedding_service.get_embedding(f"{next_name}. {next_description}")

    updated = await poi_repository.update_poi(
        db,
        poi_id=poi_id,
        poi_in=payload,
        embedding=embedding,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    return updated


@router.delete("/{poi_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poi(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    current_poi = await poi_repository.get_poi_model_by_id(db, poi_id)
    if current_poi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    _ensure_can_manage_poi(current_user, current_poi.entrepreneur_id)
    await poi_repository.delete_poi(db, poi_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
