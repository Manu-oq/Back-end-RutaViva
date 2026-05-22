from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.models.tourist_profile import TouristProfile
from app.repositories.base import BaseRepository
from app.repositories.utils import build_poi_response_from_row, get_category_ids_batch
from app.schemas.bookmark import BookmarkResponse
from app.schemas.poi import POIResponse


class BookmarkRepository(BaseRepository):
    async def list_bookmarked_pois(
        self,
        db: AsyncSession,
        tourist_id: UUID,
    ) -> list[POIResponse]:
        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                Bookmark.created_at.label("bookmarked_at"),
            )
            .join(Bookmark, Bookmark.poi_id == POI.id)
            .where(Bookmark.tourist_id == tourist_id)
            .order_by(Bookmark.created_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _, _ in rows])
        return [
            build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))
            for poi, latitude, longitude, _bookmarked_at in rows
        ]

    async def is_bookmarked(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        poi_id: UUID,
    ) -> bool:
        stmt = select(Bookmark.id).where(
            Bookmark.tourist_id == tourist_id,
            Bookmark.poi_id == poi_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_bookmark(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        poi_id: UUID,
    ) -> BookmarkResponse:
        tourist_profile = await db.get(TouristProfile, tourist_id)
        if tourist_profile is None:
            raise ValueError("Tourist profile not found.")

        poi = await db.get(POI, poi_id)
        if poi is None:
            raise ValueError("POI not found.")

        existing_stmt = select(Bookmark).where(
            Bookmark.tourist_id == tourist_id,
            Bookmark.poi_id == poi_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            return BookmarkResponse.model_validate(existing)

        bookmark = Bookmark(tourist_id=tourist_id, poi_id=poi_id)
        db.add(bookmark)

        await self._commit_or_rollback(db)
        await db.refresh(bookmark)

        return BookmarkResponse.model_validate(bookmark)

    async def delete_bookmark(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        poi_id: UUID,
    ) -> bool:
        try:
            stmt = delete(Bookmark).where(
                Bookmark.tourist_id == tourist_id,
                Bookmark.poi_id == poi_id,
            )
            result = await db.execute(stmt)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return (result.rowcount or 0) > 0
