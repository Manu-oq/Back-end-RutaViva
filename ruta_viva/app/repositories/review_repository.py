from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import POI
from app.models.review import Review
from app.models.tourist_profile import TouristProfile
from app.schemas.review import ReviewCreate, ReviewResponse
from app.services.embedding_service import OpenAIEmbeddingService

PROFILE_DECAY_WEIGHT = 0.9
REVIEW_SIGNAL_WEIGHT = 0.1


class ReviewRepository:
    async def create_review(
        self,
        db: AsyncSession,
        review_in: ReviewCreate,
        tourist_id: UUID,
        embedding_service: OpenAIEmbeddingService,
    ) -> ReviewResponse:
        poi = await db.get(POI, review_in.poi_id)
        if poi is None:
            raise ValueError("POI not found.")

        tourist_profile = await db.get(TouristProfile, tourist_id)
        if tourist_profile is None:
            raise ValueError("Tourist profile not found.")

        review_embedding = await embedding_service.get_embedding(review_in.text_content)

        review = Review(
            tourist_id=tourist_id,
            poi_id=review_in.poi_id,
            rating_stars=review_in.rating_stars,
            text_content=review_in.text_content,
            text_embedding=review_embedding,
        )
        db.add(review)

        try:
            tourist_profile.interests_embedding = self._update_interests_embedding(
                current_embedding=tourist_profile.interests_embedding,
                review_embedding=review_embedding,
            )

            await db.commit()
            await db.refresh(review)
        except Exception:
            await db.rollback()
            raise

        return ReviewResponse.model_validate(review)

    async def get_reviews_by_poi(self, db: AsyncSession, poi_id: UUID) -> list[ReviewResponse]:
        stmt = select(Review).where(Review.poi_id == poi_id).order_by(Review.created_at.desc())
        result = await db.execute(stmt)
        return [ReviewResponse.model_validate(review) for review in result.scalars().all()]

    def _update_interests_embedding(
        self,
        current_embedding: list[float] | None,
        review_embedding: list[float],
    ) -> list[float]:
        if current_embedding is None:
            return review_embedding

        if len(current_embedding) != len(review_embedding):
            raise ValueError(
                "Cannot update tourist interests embedding because current profile and review embedding dimensions differ."
            )

        return [
            (current_value * PROFILE_DECAY_WEIGHT) + (review_value * REVIEW_SIGNAL_WEIGHT)
            for current_value, review_value in zip(current_embedding, review_embedding, strict=True)
        ]
