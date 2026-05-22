from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_db
from app.models.poi import POI
from app.models.user import User
from app.repositories.entrepreneur_repository import EntrepreneurRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.entrepreneur import POIVisitCreate, POIVisitResponse, PublicEntrepreneurPostResponse
from app.schemas.poi import POICreationCheck, POICreate, POIMediaAppend, POIResponse, POIUpdate
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service


router = APIRouter(tags=["pois"])
poi_repository = POIRepository()
entrepreneur_repository = EntrepreneurRepository()


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


def _parse_category_ids(category_ids: list[str] | None) -> list[int] | None:
    if not category_ids:
        return None

    parsed_ids: list[int] = []
    invalid_values: list[str] = []

    for raw_value in category_ids:
        for value in raw_value.split(","):
            cleaned_value = value.strip()
            if not cleaned_value:
                continue
            try:
                category_id = int(cleaned_value)
            except ValueError:
                invalid_values.append(cleaned_value)
                continue
            if category_id <= 0:
                invalid_values.append(cleaned_value)
                continue
            if category_id not in parsed_ids:
                parsed_ids.append(category_id)

    if invalid_values:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category_ids must contain positive integer IDs. Invalid values: {', '.join(invalid_values)}",
        )

    return parsed_ids or None


POI_DAILY_LIMIT = 10
POI_HOURLY_LIMIT = 5


def _calculate_confidence_score(
    has_image: bool,
    description_length: int,
    has_category: bool,
    has_opening_hours: bool,
    has_contact: bool,
    is_verified_entrepreneur: bool,
) -> float:
    score = 0.0
    if has_image:
        score += 0.2
    if description_length >= 50:
        score += 0.15
    elif description_length >= 20:
        score += 0.05
    if has_category:
        score += 0.1
    if has_opening_hours:
        score += 0.1
    if has_contact:
        score += 0.05
    if is_verified_entrepreneur:
        score += 0.2
    return min(round(score, 2), 1.0)


@router.post("/", response_model=POIResponse | POICreationCheck, status_code=status.HTTP_201_CREATED)
async def create_poi(
    payload: POICreate,
    force_create: bool = Query(default=False, description="Set to true to create even if duplicates are detected."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> POIResponse | POICreationCheck:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    hourly_count = await db.scalar(
        select(func.count()).select_from(POI).where(
            POI.entrepreneur_id == current_user.id,
            POI.created_at >= hour_ago,
        )
    )
    if (hourly_count or 0) >= POI_HOURLY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: maximum {POI_HOURLY_LIMIT} POIs per hour.",
        )

    daily_count = await db.scalar(
        select(func.count()).select_from(POI).where(
            POI.entrepreneur_id == current_user.id,
            POI.created_at >= today_start,
        )
    )
    if (daily_count or 0) >= POI_DAILY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: maximum {POI_DAILY_LIMIT} POIs per day.",
        )

    text = f"{payload.name}. {payload.description}"
    embedding = await embedding_service.get_embedding(text)

    duplicates = await poi_repository.find_potential_duplicates(
        db,
        lat=payload.latitude,
        lon=payload.longitude,
        query_embedding=embedding,
        category_ids=payload.category_ids,
    )

    if duplicates and not force_create:
        pending = {
            "name": payload.name,
            "description": payload.description,
            "access_type": payload.access_type,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "category_ids": payload.category_ids,
            "image_url": payload.image_url,
            "contact_phone": payload.contact_phone,
            "contact_email": payload.contact_email,
            "opening_hours_text": payload.opening_hours_text,
            "visit_rules": payload.visit_rules,
        }
        return POICreationCheck(
            potential_duplicates=duplicates,
            pending_creation=pending,
        )

    entrepreneur_id = current_user.id if current_user.entrepreneur_profile is not None else None
    is_verified = (
        current_user.entrepreneur_profile is not None
        and current_user.entrepreneur_profile.verification_status == "verified"
    )

    confidence = _calculate_confidence_score(
        has_image=bool(payload.image_url),
        description_length=len(payload.description),
        has_category=len(payload.category_ids) > 0,
        has_opening_hours=bool(payload.opening_hours_text),
        has_contact=bool(payload.contact_phone or payload.contact_email),
        is_verified_entrepreneur=is_verified,
    )

    verification_status = "verified" if is_verified else "pending"

    return await poi_repository.create_poi(
        db,
        payload,
        entrepreneur_id=entrepreneur_id,
        embedding=embedding,
        verification_status=verification_status,
        confidence_score=confidence,
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
    category_ids: list[str] | None = Query(
        default=None,
        description=(
            "Optional category filter. Accepts comma-separated IDs "
            "(category_ids=2,4,9) or repeated query params "
            "(category_ids=2&category_ids=4)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> list[POIResponse]:
    parsed_category_ids = _parse_category_ids(category_ids)
    return await poi_repository.get_pois_nearby(
        db,
        lat=lat,
        lon=lon,
        radius_meters=radius,
        category_ids=parsed_category_ids,
    )


@router.get("/semantic-search", response_model=list[POIResponse])
async def semantic_search_pois(
    query: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    radius: float = Query(5000, gt=0),
    limit: int = Query(20, ge=1, le=100),
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
        limit=limit,
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


@router.get("/{poi_id}/posts", response_model=list[PublicEntrepreneurPostResponse])
async def list_public_poi_posts(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[PublicEntrepreneurPostResponse]:
    from app.models.poi import POI as POIModel

    poi_exists = await db.get(POIModel, poi_id)
    if poi_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="POI not found.",
        )

    posts = await entrepreneur_repository.list_published_poi_posts(db, poi_id)
    return [PublicEntrepreneurPostResponse.model_validate(post) for post in posts]


@router.post("/{poi_id}/visit", response_model=POIVisitResponse, status_code=status.HTTP_201_CREATED)
async def record_poi_visit(
    poi_id: UUID,
    payload: POIVisitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> POIVisitResponse:
    visit = await entrepreneur_repository.record_poi_visit(
        db,
        poi_id=poi_id,
        visitor_id=current_user.id if current_user is not None else None,
        visit_in=payload,
    )
    if visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POI not found.")

    await poi_repository.recalculate_confidence(db, poi_id)

    return visit


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

    await poi_repository.recalculate_confidence(db, poi_id)

    return await poi_repository.get_poi_by_id(db, poi_id)


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
    if payload.name is not None or payload.description is not None:
        next_name = payload.name or current_poi.name
        next_description = payload.description or current_poi.description
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

    await poi_repository.recalculate_confidence(db, poi_id)

    return await poi_repository.get_poi_by_id(db, poi_id)


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
