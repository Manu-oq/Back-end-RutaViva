from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import POI
from app.models.review import Review
from app.models.tourist_profile import TouristProfile
from app.repositories.base import BaseRepository
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummaryResponse, ReviewUpdate


class ReviewRepository(BaseRepository):
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
            await self._commit_or_rollback(db)
            await db.refresh(review)
        except Exception as exc:
            if "uq_reviews_tourist_poi" in str(exc):
                raise ValueError("You have already reviewed this POI.") from exc
            raise

        return ReviewResponse.model_validate(review)

    async def get_reviews_by_poi(self, db: AsyncSession, poi_id: UUID) -> list[ReviewResponse]:
        stmt = select(Review).where(Review.poi_id == poi_id).order_by(Review.created_at.desc())
        result = await db.execute(stmt)
        return [ReviewResponse.model_validate(review) for review in result.scalars().all()]

    async def get_review_summary_by_poi(
        self,
        db: AsyncSession,
        poi_id: UUID,
    ) -> ReviewSummaryResponse:
        stmt = (
            select(
                func.count(Review.id).label("total"),
                func.coalesce(func.avg(Review.rating_stars), 0.0).label("avg_rating"),
                func.coalesce(func.count(Review.id).filter(Review.rating_stars == 1), 0).label("star_1"),
                func.coalesce(func.count(Review.id).filter(Review.rating_stars == 2), 0).label("star_2"),
                func.coalesce(func.count(Review.id).filter(Review.rating_stars == 3), 0).label("star_3"),
                func.coalesce(func.count(Review.id).filter(Review.rating_stars == 4), 0).label("star_4"),
                func.coalesce(func.count(Review.id).filter(Review.rating_stars == 5), 0).label("star_5"),
            )
            .where(Review.poi_id == poi_id)
        )
        result = await db.execute(stmt)
        row = result.one()

        total = int(row.total or 0)
        average = round(float(row.avg_rating), 2) if total > 0 else 0.0
        distribution = {
            1: int(row.star_1 or 0),
            2: int(row.star_2 or 0),
            3: int(row.star_3 or 0),
            4: int(row.star_4 or 0),
            5: int(row.star_5 or 0),
        }

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

        await self._commit_or_rollback(db)
        await db.refresh(review)

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

        await db.delete(review)
        await self._commit_or_rollback(db)

        return True
