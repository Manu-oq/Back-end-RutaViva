from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.bookmark import Bookmark
    from app.models.itinerary import Itinerary
    from app.models.review import Review
    from app.models.user import User


class TouristProfile(Base):
    __tablename__ = "tourist_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    full_name: Mapped[str] = mapped_column(nullable=False)
    interests_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    has_own_transport: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    system_preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship(back_populates="tourist_profile", lazy="selectin")
    bookmarks: Mapped[list[Bookmark]] = relationship(back_populates="tourist", lazy="noload")
    reviews: Mapped[list[Review]] = relationship(back_populates="tourist", lazy="noload")
    itineraries: Mapped[list[Itinerary]] = relationship(back_populates="tourist", lazy="noload")
