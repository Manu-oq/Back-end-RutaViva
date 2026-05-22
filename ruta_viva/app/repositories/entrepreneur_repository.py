from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.entrepreneur_post import EntrepreneurPost
from app.models.poi import POI
from app.models.poi_visit import POIVisit
from app.models.review import Review
from app.repositories.base import BaseRepository
from app.schemas.entrepreneur import (
    EntrepreneurMetricsResponse,
    EntrepreneurPostCreate,
    EntrepreneurPostCreatePOI,
    EntrepreneurPostUpdate,
    POIActivityItem,
    POIAnalyticsResponse,
    POIVisitCreate,
    POIVisitResponse,
)


class EntrepreneurRepository(BaseRepository):
    async def create_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        post_in: EntrepreneurPostCreate | EntrepreneurPostCreatePOI,
        poi_id: UUID | None = None,
    ) -> EntrepreneurPost:
        target_poi_id = poi_id if poi_id is not None else getattr(post_in, "poi_id", None)
        if target_poi_id is None:
            raise ValueError("poi_id is required to create an entrepreneur post.")

        post = EntrepreneurPost(
            entrepreneur_id=entrepreneur_id,
            poi_id=target_poi_id,
            title=post_in.title,
            content=post_in.content,
            image_url=post_in.image_url,
            is_published=post_in.is_published,
        )
        db.add(post)
        await self._commit_or_rollback(db)
        await db.refresh(post)
        await db.refresh(post, ["poi"])
        return post

    async def update_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        post_id: UUID,
        post_in: EntrepreneurPostUpdate,
        poi_id: UUID | None = None,
    ) -> EntrepreneurPost | None:
        post = await db.get(EntrepreneurPost, post_id)
        if post is None or post.entrepreneur_id != entrepreneur_id:
            return None
        if poi_id is not None and post.poi_id != poi_id:
            return None

        if post_in.title is not None:
            post.title = post_in.title
        if post_in.content is not None:
            post.content = post_in.content
        if post_in.image_url is not None:
            post.image_url = post_in.image_url
        if post_in.is_published is not None:
            post.is_published = post_in.is_published

        await self._commit_or_rollback(db)
        await db.refresh(post)
        await db.refresh(post, ["poi"])
        return post

    async def delete_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        post_id: UUID,
        poi_id: UUID | None = None,
    ) -> bool:
        post = await db.get(EntrepreneurPost, post_id)
        if post is None or post.entrepreneur_id != entrepreneur_id:
            return False
        if poi_id is not None and post.poi_id != poi_id:
            return False

        await db.delete(post)
        await self._commit_or_rollback(db)
        return True

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

    async def list_poi_posts(self, db: AsyncSession, poi_id: UUID) -> list[EntrepreneurPost]:
        result = await db.execute(
            select(EntrepreneurPost)
            .where(EntrepreneurPost.poi_id == poi_id)
            .order_by(EntrepreneurPost.is_pinned.desc(), EntrepreneurPost.sort_order, EntrepreneurPost.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_published_poi_posts(self, db: AsyncSession, poi_id: UUID) -> list[EntrepreneurPost]:
        result = await db.execute(
            select(EntrepreneurPost)
            .where(
                EntrepreneurPost.poi_id == poi_id,
                EntrepreneurPost.is_published.is_(True),
            )
            .order_by(EntrepreneurPost.is_pinned.desc(), EntrepreneurPost.sort_order, EntrepreneurPost.created_at.desc())
        )
        return list(result.scalars().all())

    async def pin_poi_post(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
        poi_id: UUID,
        post_id: UUID,
        is_pinned: bool,
    ) -> EntrepreneurPost | None:
        post = await db.get(EntrepreneurPost, post_id)
        if post is None or post.entrepreneur_id != entrepreneur_id or post.poi_id != poi_id:
            return None

        post.is_pinned = is_pinned

        await self._commit_or_rollback(db)
        await db.refresh(post)
        await db.refresh(post, ["poi"])

        return post

    async def reorder_poi_posts(
        self,
        db: AsyncSession,
        poi_id: UUID,
        items: list[tuple[UUID, int]],
    ) -> list[EntrepreneurPost]:
        post_ids = [item[0] for item in items]
        result = await db.execute(
            select(EntrepreneurPost).where(
                and_(
                    EntrepreneurPost.poi_id == poi_id,
                    EntrepreneurPost.id.in_(post_ids),
                )
            )
        )
        posts_by_id = {post.id: post for post in result.scalars().all()}

        for post_id, position in items:
            post = posts_by_id.get(post_id)
            if post is not None:
                post.sort_order = position

        await self._commit_or_rollback(db)
        for post in posts_by_id.values():
            await db.refresh(post)

        result = await db.execute(
            select(EntrepreneurPost)
            .where(EntrepreneurPost.poi_id == poi_id)
            .order_by(EntrepreneurPost.sort_order, EntrepreneurPost.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_metrics(self, db: AsyncSession, entrepreneur_id: UUID) -> EntrepreneurMetricsResponse:
        poi_ids_subquery = select(POI.id).where(POI.entrepreneur_id == entrepreneur_id)

        metrics_stmt = (
            select(
                func.coalesce(func.count(POI.id), 0).label("total_pois"),
                func.coalesce(func.count(POIVisit.id), 0).label("total_visits"),
                func.coalesce(func.count(Review.id), 0).label("total_reviews"),
                func.coalesce(func.avg(Review.rating_stars), None).label("average_rating"),
                func.coalesce(func.count(Bookmark.id), 0).label("total_bookmarks"),
                func.coalesce(
                    select(func.count(EntrepreneurPost.id))
                    .where(
                        and_(
                            EntrepreneurPost.entrepreneur_id == entrepreneur_id,
                            EntrepreneurPost.is_published.is_(True),
                        )
                    )
                    .correlate(None)
                    .scalar_subquery(),
                    0,
                ).label("published_posts"),
            )
            .select_from(POI)
            .outerjoin(POIVisit, POIVisit.poi_id == POI.id)
            .outerjoin(Review, Review.poi_id == POI.id)
            .outerjoin(Bookmark, Bookmark.poi_id == POI.id)
            .where(POI.entrepreneur_id == entrepreneur_id)
        )
        result = await db.execute(metrics_stmt)
        row = result.one()

        return EntrepreneurMetricsResponse(
            total_pois=int(row.total_pois or 0),
            total_visits=int(row.total_visits or 0),
            total_reviews=int(row.total_reviews or 0),
            average_rating=float(row.average_rating) if row.average_rating is not None else None,
            total_bookmarks=int(row.total_bookmarks or 0),
            published_posts=int(row.published_posts or 0),
        )

    async def get_poi_analytics(self, db: AsyncSession, poi_id: UUID) -> POIAnalyticsResponse:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        visits_count = await db.scalar(
            select(func.count()).select_from(POIVisit).where(POIVisit.poi_id == poi_id)
        )

        weekly_visits = await db.scalar(
            select(func.count())
            .select_from(POIVisit)
            .where(and_(POIVisit.poi_id == poi_id, POIVisit.created_at >= week_ago))
        )

        favorites_count = await db.scalar(
            select(func.count()).select_from(Bookmark).where(Bookmark.poi_id == poi_id)
        )

        review_stats = await db.execute(
            select(func.count(Review.id), func.avg(Review.rating_stars)).where(Review.poi_id == poi_id)
        )
        reviews_count, avg_rating = review_stats.one()

        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = this_month_start - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        this_month_visits = await db.scalar(
            select(func.count())
            .select_from(POIVisit)
            .where(and_(POIVisit.poi_id == poi_id, POIVisit.created_at >= this_month_start))
        )

        last_month_visits = await db.scalar(
            select(func.count())
            .select_from(POIVisit)
            .where(
                and_(
                    POIVisit.poi_id == poi_id,
                    POIVisit.created_at >= last_month_start,
                    POIVisit.created_at <= last_month_end,
                )
            )
        )

        lm = int(last_month_visits or 0)
        tm = int(this_month_visits or 0)

        if lm == 0:
            monthly_growth = 1.0 if tm > 0 else 0.0
        else:
            monthly_growth = (tm - lm) / lm

        return POIAnalyticsResponse(
            visits_count=int(visits_count or 0),
            favorites_count=int(favorites_count or 0),
            reviews_count=int(reviews_count or 0),
            avg_rating=float(avg_rating) if avg_rating is not None else 0.0,
            weekly_visits=int(weekly_visits or 0),
            monthly_growth=round(monthly_growth, 4),
        )

    async def get_poi_activity(self, db: AsyncSession, poi_id: UUID, limit: int = 50) -> list[POIActivityItem]:
        activities: list[POIActivityItem] = []

        reviews = await db.execute(
            select(Review).where(Review.poi_id == poi_id).order_by(Review.created_at.desc()).limit(limit)
        )
        for review in reviews.scalars().all():
            activities.append(
                POIActivityItem(
                    type="new_review",
                    timestamp=review.created_at,
                    data={"rating_stars": review.rating_stars, "text_preview": review.text_content[:100]}),
            )

        bookmarks = await db.execute(
            select(Bookmark).where(Bookmark.poi_id == poi_id).order_by(Bookmark.created_at.desc()).limit(limit)
        )
        for bookmark in bookmarks.scalars().all():
            tourist_name = bookmark.tourist.full_name if bookmark.tourist else None
            activities.append(
                POIActivityItem(
                    type="new_favorite",
                    timestamp=bookmark.created_at,
                    data={"tourist_name": tourist_name}),
            )

        posts = await db.execute(
            select(EntrepreneurPost)
            .where(EntrepreneurPost.poi_id == poi_id)
            .order_by(EntrepreneurPost.created_at.desc())
            .limit(limit)
        )
        for post in posts.scalars().all():
            activities.append(
                POIActivityItem(
                    type="new_post",
                    timestamp=post.created_at,
                    data={"title": post.title}),
            )

        visits = await db.execute(
            select(POIVisit).where(POIVisit.poi_id == poi_id).order_by(POIVisit.created_at.desc()).limit(limit)
        )
        for visit in visits.scalars().all():
            activities.append(
                POIActivityItem(
                    type="new_visit",
                    timestamp=visit.created_at,
                    data={"source": visit.source}),
            )

        activities.sort(key=lambda a: a.timestamp, reverse=True)
        return activities[:limit]

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

        await self._commit_or_rollback(db)
        await db.refresh(visit)

        return POIVisitResponse.model_validate(visit)
