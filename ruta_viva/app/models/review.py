from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.poi import POI
    from app.models.tourist_profile import TouristProfile


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating_stars BETWEEN 1 AND 5", name="ck_reviews_rating_stars"),
        UniqueConstraint("tourist_id", "poi_id", name="uq_reviews_tourist_poi"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tourist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tourist_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    poi_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pois.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    text_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tourist: Mapped[TouristProfile] = relationship(back_populates="reviews", lazy="selectin")
    poi: Mapped[POI] = relationship(back_populates="reviews", lazy="selectin")
