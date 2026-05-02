from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import ReviewCreate, ReviewResponse
from app.services.embedding_service import OpenAIEmbeddingService, get_embedding_service


router = APIRouter(tags=["reviews"])
review_repository = ReviewRepository()


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreate,
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
        return await review_repository.create_review(
            db,
            review_in=payload,
            tourist_id=current_user.id,
            embedding_service=embedding_service,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/poi/{poi_id}", response_model=list[ReviewResponse])
async def get_reviews_by_poi(
    poi_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ReviewResponse]:
    return await review_repository.get_reviews_by_poi(db, poi_id)
