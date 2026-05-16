from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ara_message import AraMessage
    from app.models.itinerary import Itinerary
    from app.models.tourist_profile import TouristProfile


class AraSession(Base):
    __tablename__ = "ara_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tourist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tourist_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="clarifying", server_default="clarifying")
    initial_query: Mapped[str] = mapped_column(String(1000), nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intent_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preferences_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    candidate_poi_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    generated_itinerary_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tourist: Mapped[TouristProfile] = relationship(lazy="selectin")
    messages: Mapped[list[AraMessage]] = relationship(
        back_populates="session",
        lazy="selectin",
        order_by="AraMessage.created_at",
        cascade="all, delete-orphan",
    )
    generated_itinerary: Mapped[Itinerary | None] = relationship(lazy="selectin")
