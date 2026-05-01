from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.bookmark import Bookmark
    from app.models.entrepreneur_profile import EntrepreneurProfile
    from app.models.itinerary_step import ItineraryStep
    from app.models.poi_category import POICategory
    from app.models.review import Review


class POI(Base):
    __tablename__ = "pois"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    entrepreneur_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entrepreneur_profiles.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    description_embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    access_type: Mapped[str] = mapped_column(String(50), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    multimedia_urls: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)

    entrepreneur: Mapped[EntrepreneurProfile | None] = relationship(back_populates="pois", lazy="selectin")
    category_links: Mapped[list[POICategory]] = relationship(back_populates="poi", lazy="noload")
    bookmarks: Mapped[list[Bookmark]] = relationship(back_populates="poi", lazy="noload")
    reviews: Mapped[list[Review]] = relationship(back_populates="poi", lazy="noload")
    itinerary_steps: Mapped[list[ItineraryStep]] = relationship(back_populates="poi", lazy="noload")
