from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.entrepreneur_post import EntrepreneurPost
from app.models.poi import POI
from app.models.poi_visit import POIVisit
from app.models.review import Review
from app.schemas.entrepreneur import (
    EntrepreneurMetricsResponse,
    EntrepreneurPostCreate,
    EntrepreneurPostUpdate,
    POIVisitCreate,
    POIVisitResponse,
)


class EntrepreneurRepository:
    async def create_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        post_in: EntrepreneurPostCreate,
    ) -> EntrepreneurPost:
        post = EntrepreneurPost(
            entrepreneur_id=entrepreneur_id,
            title=post_in.title,
            content=post_in.content,
            image_url=post_in.image_url,
            is_published=post_in.is_published,
        )
        db.add(post)

        try:
            await db.commit()
            await db.refresh(post)
        except Exception:
            await db.rollback()
            raise

        return post

    async def list_my_posts(self, db: AsyncSession, entrepreneur_id: UUID) -> list[EntrepreneurPost]:
        result = await db.execute(
            select(EntrepreneurPost)
            .where(EntrepreneurPost.entrepreneur_id == entrepreneur_id)
            .order_by(EntrepreneurPost.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_published_posts(self, db: AsyncSession, entrepreneur_id: UUID) -> list[EntrepreneurPost]:
        result = await db.execute(
            select(EntrepreneurPost)
            .where(
                and_(
                    EntrepreneurPost.entrepreneur_id == entrepreneur_id,
                    EntrepreneurPost.is_published.is_(True),
                )
            )
            .order_by(EntrepreneurPost.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        post_id: UUID,
        post_in: EntrepreneurPostUpdate,
    ) -> EntrepreneurPost | None:
        post = await db.get(EntrepreneurPost, post_id)
        if post is None or post.entrepreneur_id != entrepreneur_id:
            return None

        if post_in.title is not None:
            post.title = post_in.title
        if post_in.content is not None:
            post.content = post_in.content
        if post_in.image_url is not None:
            post.image_url = post_in.image_url
        if post_in.is_published is not None:
            post.is_published = post_in.is_published

        try:
            await db.commit()
            await db.refresh(post)
        except Exception:
            await db.rollback()
            raise

        return post

    async def delete_post(self, db: AsyncSession, entrepreneur_id: UUID, post_id: UUID) -> bool:
        post = await db.get(EntrepreneurPost, post_id)
        if post is None or post.entrepreneur_id != entrepreneur_id:
            return False

        try:
            await db.delete(post)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return True

    async def get_metrics(self, db: AsyncSession, entrepreneur_id: UUID) -> EntrepreneurMetricsResponse:
        poi_ids_subquery = select(POI.id).where(POI.entrepreneur_id == entrepreneur_id)

        total_pois = await db.scalar(select(func.count()).select_from(POI).where(POI.entrepreneur_id == entrepreneur_id))
        total_visits = await db.scalar(select(func.count()).select_from(POIVisit).where(POIVisit.poi_id.in_(poi_ids_subquery)))
        review_stats = await db.execute(
            select(func.count(Review.id), func.avg(Review.rating_stars)).where(Review.poi_id.in_(poi_ids_subquery))
        )
        total_reviews, average_rating = review_stats.one()
        total_bookmarks = await db.scalar(
            select(func.count()).select_from(Bookmark).where(Bookmark.poi_id.in_(poi_ids_subquery))
        )
        published_posts = await db.scalar(
            select(func.count())
            .select_from(EntrepreneurPost)
            .where(
                and_(
                    EntrepreneurPost.entrepreneur_id == entrepreneur_id,
                    EntrepreneurPost.is_published.is_(True),
                )
            )
        )

        return EntrepreneurMetricsResponse(
            total_pois=int(total_pois or 0),
            total_visits=int(total_visits or 0),
            total_reviews=int(total_reviews or 0),
            average_rating=float(average_rating) if average_rating is not None else None,
            total_bookmarks=int(total_bookmarks or 0),
            published_posts=int(published_posts or 0),
        )

    async def record_poi_visit(
        self,
        db: AsyncSession,
        poi_id: UUID,
        visitor_id: UUID | None,
        visit_in: POIVisitCreate,
    ) -> POIVisitResponse | None:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return None

        visit = POIVisit(
            poi_id=poi_id,
            visitor_id=visitor_id,
            source=visit_in.source,
        )
        db.add(visit)

        try:
            await db.commit()
            await db.refresh(visit)
        except Exception:
            await db.rollback()
            raise

        return POIVisitResponse.model_validate(visit)
