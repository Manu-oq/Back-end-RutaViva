from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.poi_repository import POIRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import (
    ReviewCreate,
    ReviewResponse,
    ReviewSummaryResponse,
    ReviewUpdate,
)
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service
from app.services.review_enrichment_service import generate_review_embedding_and_update_profile


router = APIRouter(tags=["reviews"])
review_repository = ReviewRepository()
poi_repository = POIRepository()


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> ReviewResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can create reviews.",
        )

    try:
        review = await review_repository.create_review(
            db,
            review_in=payload,
            tourist_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    background_tasks.add_task(
        generate_review_embedding_and_update_profile,
        review.id,
        embedding_service,
    )

    await poi_repository.recalculate_confidence(db, payload.poi_id)

    return review


@router.get("/poi/{poi_id}", response_model=list[ReviewResponse])
async def get_reviews_by_poi(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ReviewResponse]:
    return await review_repository.get_reviews_by_poi(db, poi_id)


@router.get("/poi/{poi_id}/summary", response_model=ReviewSummaryResponse)
async def get_reviews_summary_by_poi(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReviewSummaryResponse:
    return await review_repository.get_review_summary_by_poi(db, poi_id)


@router.put("/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: UUID,
    payload: ReviewUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embedding_service: OpenAIEmbeddingService = Depends(get_embedding_service),
) -> ReviewResponse:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can update reviews.",
        )

    if payload.rating_stars is None and payload.text_content is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one review field must be provided.",
        )

    try:
        review = await review_repository.update_review(
            db,
            review_id=review_id,
            tourist_id=current_user.id,
            review_in=payload,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )

    if payload.text_content is not None:
        background_tasks.add_task(
            generate_review_embedding_and_update_profile,
            review.id,
            embedding_service,
        )

    return review


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tourist users can delete reviews.",
        )

    try:
        deleted = await review_repository.delete_review(
            db,
            review_id=review_id,
            tourist_id=current_user.id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
