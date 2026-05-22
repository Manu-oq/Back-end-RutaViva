from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.bookmark import Bookmark
    from app.models.entrepreneur_post import EntrepreneurPost
    from app.models.entrepreneur_profile import EntrepreneurProfile
    from app.models.itinerary_step import ItineraryStep
    from app.models.poi_category import POICategory
    from app.models.poi_visit import POIVisit
    from app.models.review import Review


class POI(Base):
    __tablename__ = "pois"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('pending', 'flagged', 'verified')",
            name="ck_pois_verification_status",
        ),
        CheckConstraint(
            "access_type IN ('public', 'restricted', 'private')",
            name="ck_pois_access_type",
        ),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_pois_confidence_score",
        ),
    )

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
    multimedia_urls: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=lambda: {"cover": None, "gallery": []}
    )
    opening_hours_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    visit_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    entrepreneur: Mapped[EntrepreneurProfile | None] = relationship(back_populates="pois", lazy="selectin")
    category_links: Mapped[list[POICategory]] = relationship(back_populates="poi", lazy="noload")
    bookmarks: Mapped[list[Bookmark]] = relationship(back_populates="poi", lazy="noload")
    reviews: Mapped[list[Review]] = relationship(back_populates="poi", lazy="noload")
    visits: Mapped[list[POIVisit]] = relationship(back_populates="poi", lazy="noload")
    itinerary_steps: Mapped[list[ItineraryStep]] = relationship(back_populates="poi", lazy="noload")
    entrepreneur_posts: Mapped[list[EntrepreneurPost]] = relationship(back_populates="poi", lazy="noload")
