from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.poi import POI
from app.models.tourist_profile import TouristProfile
from app.repositories.poi_repository import POIRepository
from app.schemas.bookmark import BookmarkResponse
from app.schemas.poi import POIResponse


class BookmarkRepository:
    def __init__(self) -> None:
        self._poi_repository = POIRepository()

    async def list_bookmarked_pois(
        self,
        db: AsyncSession,
        tourist_id: UUID,
    ) -> list[POIResponse]:
        stmt = (
            select(Bookmark.poi_id)
            .where(Bookmark.tourist_id == tourist_id)
            .order_by(Bookmark.created_at.desc())
        )
        result = await db.execute(stmt)
        poi_ids = list(result.scalars().all())

        pois: list[POIResponse] = []
        for poi_id in poi_ids:
            poi = await self._poi_repository.get_poi_by_id(db, poi_id)
            if poi is not None:
                pois.append(poi)
        return pois

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

        try:
            await db.commit()
            await db.refresh(bookmark)
        except Exception:
            await db.rollback()
            raise

        return BookmarkResponse.model_validate(bookmark)

    async def delete_bookmark(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        poi_id: UUID,
    ) -> bool:
        stmt = delete(Bookmark).where(
            Bookmark.tourist_id == tourist_id,
            Bookmark.poi_id == poi_id,
        )
        result = await db.execute(stmt)
        await db.commit()
        return (result.rowcount or 0) > 0
