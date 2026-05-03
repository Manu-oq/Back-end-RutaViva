from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.poi import POI
from app.models.review import Review
from app.models.tourist_profile import TouristProfile
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummaryResponse, ReviewUpdate
from app.services.embedding_service import OpenAIEmbeddingService

PROFILE_DECAY_WEIGHT = 0.9
REVIEW_SIGNAL_WEIGHT = 0.1
logger = logging.getLogger("ruta_viva.reviews")


class ReviewRepository:
    async def create_review(
        self,
        db: AsyncSession,
        review_in: ReviewCreate,
        tourist_id: UUID,
    ) -> ReviewResponse:
        poi = await db.get(POI, review_in.poi_id)
        if poi is None:
            raise ValueError("POI not found.")

        tourist_profile = await db.get(TouristProfile, tourist_id)
        if tourist_profile is None:
            raise ValueError("Tourist profile not found.")

        review = Review(
            tourist_id=tourist_id,
            poi_id=review_in.poi_id,
            rating_stars=review_in.rating_stars,
            text_content=review_in.text_content,
            text_embedding=None,
        )
        db.add(review)

        try:
            await db.commit()
            await db.refresh(review)
        except Exception:
            await db.rollback()
            raise

        return ReviewResponse.model_validate(review)

    async def generate_review_embedding_and_update_profile(
        self,
        review_id: UUID,
        embedding_service: OpenAIEmbeddingService,
    ) -> None:
        """
        Tarea diferida: genera el embedding de la reseña y actualiza el perfil
        del turista sin bloquear la respuesta HTTP del endpoint.
        """
        try:
            async with AsyncSessionLocal() as db:
                review = await db.get(Review, review_id)
                if review is None:
                    return

                if review.text_embedding is not None:
                    return

                tourist_profile = await db.get(TouristProfile, review.tourist_id)
                if tourist_profile is None:
                    return

                review_embedding = await embedding_service.get_embedding(review.text_content)

                review.text_embedding = review_embedding
                tourist_profile.interests_embedding = self._update_interests_embedding(
                    current_embedding=tourist_profile.interests_embedding,
                    review_embedding=review_embedding,
                )

                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to enrich review %s with embedding in background task.", review_id)

    async def get_reviews_by_poi(self, db: AsyncSession, poi_id: UUID) -> list[ReviewResponse]:
        stmt = select(Review).where(Review.poi_id == poi_id).order_by(Review.created_at.desc())
        result = await db.execute(stmt)
        return [ReviewResponse.model_validate(review) for review in result.scalars().all()]

    async def get_review_summary_by_poi(
        self,
        db: AsyncSession,
        poi_id: UUID,
    ) -> ReviewSummaryResponse:
        stmt = select(Review.rating_stars).where(Review.poi_id == poi_id)
        result = await db.execute(stmt)
        ratings = list(result.scalars().all())
        distribution = {star: 0 for star in range(1, 6)}
        for rating in ratings:
            distribution[rating] += 1

        total = len(ratings)
        average = round(sum(ratings) / total, 2) if total > 0 else 0.0
        return ReviewSummaryResponse(
            poi_id=poi_id,
            average_rating=average,
            total_reviews=total,
            rating_distribution=distribution,
        )

    async def update_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        tourist_id: UUID,
        review_in: ReviewUpdate,
    ) -> ReviewResponse | None:
        review = await db.get(Review, review_id)
        if review is None:
            return None

        if review.tourist_id != tourist_id:
            raise PermissionError("Cannot update a review created by another tourist.")

        if review_in.rating_stars is not None:
            review.rating_stars = review_in.rating_stars

        if review_in.text_content is not None:
            cleaned_text = review_in.text_content.strip()
            if not cleaned_text:
                raise ValueError("Review text cannot be empty.")
            if cleaned_text != review.text_content:
                review.text_content = cleaned_text
                review.text_embedding = None

        try:
            await db.commit()
            await db.refresh(review)
        except Exception:
            await db.rollback()
            raise

        return ReviewResponse.model_validate(review)

    async def delete_review(
        self,
        db: AsyncSession,
        review_id: UUID,
        tourist_id: UUID,
    ) -> bool | None:
        review = await db.get(Review, review_id)
        if review is None:
            return None

        if review.tourist_id != tourist_id:
            raise PermissionError("Cannot delete a review created by another tourist.")

        try:
            await db.delete(review)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return True

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
