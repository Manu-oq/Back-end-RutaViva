from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    async def _commit_or_rollback(self, db: AsyncSession) -> None:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def commit_or_rollback(self, db: AsyncSession) -> None:
        """Public wrapper for service-level transaction boundaries."""
        await self._commit_or_rollback(db)
