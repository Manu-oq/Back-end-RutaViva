from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_db
from app.models.poi import POI
from app.models.user import User
from app.repositories.entrepreneur_repository import EntrepreneurRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.entrepreneur import (
    EntrepreneurIncomeResponse,
    EntrepreneurMetricsResponse,
    EntrepreneurPostCreate,
    EntrepreneurPostCreatePOI,
    EntrepreneurPostResponse,
    EntrepreneurPostUpdate,
    POIActivityItem,
    POIAnalyticsResponse,
    POIVisitCreate,
    POIVisitResponse,
    PinPostRequest,
    ReorderPostsRequest,
)


router = APIRouter(tags=["entrepreneur"])
entrepreneur_repository = EntrepreneurRepository()
poi_repository = POIRepository()


def _post_to_response(post) -> EntrepreneurPostResponse:
    return EntrepreneurPostResponse.model_validate(post)


def _ensure_entrepreneur(current_user: User) -> None:
    if current_user.entrepreneur_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only entrepreneur users can access this resource.",
        )


async def _verify_poi_ownership(db: AsyncSession, poi_id: UUID, current_user: User) -> POI:
    poi = await db.get(POI, poi_id)
    if poi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POI not found.")
    if poi.entrepreneur_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this POI.",
        )
    return poi


@router.get("/me/metrics", response_model=EntrepreneurMetricsResponse)
async def read_my_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurMetricsResponse:
    _ensure_entrepreneur(current_user)
    return await entrepreneur_repository.get_metrics(db, current_user.id)


@router.get("/me/income", response_model=EntrepreneurIncomeResponse)
async def read_my_income(current_user: User = Depends(get_current_user)) -> EntrepreneurIncomeResponse:
    _ensure_entrepreneur(current_user)
    return EntrepreneurIncomeResponse()


@router.get("/me/posts", response_model=list[EntrepreneurPostResponse])
async def list_my_posts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EntrepreneurPostResponse]:
    _ensure_entrepreneur(current_user)
    posts = await entrepreneur_repository.list_my_posts(db, current_user.id)
    return [_post_to_response(post) for post in posts]


@router.post("/me/posts", response_model=EntrepreneurPostResponse, status_code=status.HTTP_201_CREATED)
async def create_my_post(
    payload: EntrepreneurPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    poi = await db.get(POI, payload.poi_id)
    if poi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POI not found.")
    if poi.entrepreneur_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this POI.",
        )
    post = await entrepreneur_repository.create_post(db, current_user.id, payload)
    post.poi = poi
    return _post_to_response(post)


@router.patch("/me/posts/{post_id}", response_model=EntrepreneurPostResponse)
async def update_my_post(
    post_id: UUID,
    payload: EntrepreneurPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    post = await entrepreneur_repository.update_post(db, current_user.id, post_id, payload)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return _post_to_response(post)


@router.delete("/me/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ensure_entrepreneur(current_user)
    deleted = await entrepreneur_repository.delete_post(db, current_user.id, post_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{entrepreneur_id}/posts", response_model=list[EntrepreneurPostResponse])
async def list_public_entrepreneur_posts(
    entrepreneur_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[EntrepreneurPostResponse]:
    posts = await entrepreneur_repository.list_published_posts(db, entrepreneur_id)
    return [_post_to_response(post) for post in posts]


@router.post("/pois/{poi_id}/visit", response_model=POIVisitResponse, status_code=status.HTTP_201_CREATED)
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


@router.get("/pois/{poi_id}/analytics", response_model=POIAnalyticsResponse)
async def read_poi_analytics(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> POIAnalyticsResponse:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    return await entrepreneur_repository.get_poi_analytics(db, poi_id)


@router.get("/pois/{poi_id}/activity", response_model=list[POIActivityItem])
async def read_poi_activity(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[POIActivityItem]:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    return await entrepreneur_repository.get_poi_activity(db, poi_id)


@router.get("/pois/{poi_id}/posts", response_model=list[EntrepreneurPostResponse])
async def list_poi_posts(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EntrepreneurPostResponse]:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    posts = await entrepreneur_repository.list_poi_posts(db, poi_id)
    return [_post_to_response(post) for post in posts]


@router.put("/pois/{poi_id}/posts/reorder", response_model=list[EntrepreneurPostResponse])
async def reorder_poi_posts(
    poi_id: UUID,
    payload: ReorderPostsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EntrepreneurPostResponse]:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)

    items = [(item.post_id, item.position) for item in payload.posts]
    if len(items) != len(payload.posts):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate post_id in reorder request.",
        )

    posts = await entrepreneur_repository.reorder_poi_posts(db, poi_id, items)
    return [_post_to_response(post) for post in posts]


@router.post("/pois/{poi_id}/posts", response_model=EntrepreneurPostResponse, status_code=status.HTTP_201_CREATED)
async def create_poi_post(
    poi_id: UUID,
    payload: EntrepreneurPostCreatePOI,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    poi = await _verify_poi_ownership(db, poi_id, current_user)
    post = await entrepreneur_repository.create_post(db, current_user.id, payload, poi_id=poi_id)
    post.poi = poi
    return _post_to_response(post)


@router.patch("/pois/{poi_id}/posts/{post_id}", response_model=EntrepreneurPostResponse)
async def update_poi_post(
    poi_id: UUID,
    post_id: UUID,
    payload: EntrepreneurPostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    post = await entrepreneur_repository.update_post(db, current_user.id, post_id, payload, poi_id=poi_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return _post_to_response(post)


@router.delete("/pois/{poi_id}/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poi_post(
    poi_id: UUID,
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    deleted = await entrepreneur_repository.delete_post(db, current_user.id, post_id, poi_id=poi_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/pois/{poi_id}/posts/{post_id}/pin", response_model=EntrepreneurPostResponse)
async def pin_poi_post(
    poi_id: UUID,
    post_id: UUID,
    payload: PinPostRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    await _verify_poi_ownership(db, poi_id, current_user)
    post = await entrepreneur_repository.pin_poi_post(db, current_user.id, poi_id, post_id, payload.is_pinned)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return _post_to_response(post)
