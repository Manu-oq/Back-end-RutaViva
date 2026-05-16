from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.entrepreneur_repository import EntrepreneurRepository
from app.schemas.entrepreneur import (
    EntrepreneurIncomeResponse,
    EntrepreneurMetricsResponse,
    EntrepreneurPostCreate,
    EntrepreneurPostResponse,
    EntrepreneurPostUpdate,
    POIVisitCreate,
    POIVisitResponse,
)


router = APIRouter(tags=["entrepreneur"])
entrepreneur_repository = EntrepreneurRepository()


def _ensure_entrepreneur(current_user: User) -> None:
    if current_user.entrepreneur_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only entrepreneur users can access this resource.",
        )


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
    return [EntrepreneurPostResponse.model_validate(post) for post in posts]


@router.post("/me/posts", response_model=EntrepreneurPostResponse, status_code=status.HTTP_201_CREATED)
async def create_my_post(
    payload: EntrepreneurPostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurPostResponse:
    _ensure_entrepreneur(current_user)
    post = await entrepreneur_repository.create_post(db, current_user.id, payload)
    return EntrepreneurPostResponse.model_validate(post)


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
    return EntrepreneurPostResponse.model_validate(post)


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
    return [EntrepreneurPostResponse.model_validate(post) for post in posts]



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
    return visit
