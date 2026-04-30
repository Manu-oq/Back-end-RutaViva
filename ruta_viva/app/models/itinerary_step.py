from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.itinerary import Itinerary
    from app.models.poi import POI


class ItineraryStep(Base):
    __tablename__ = "itinerary_steps"
    __table_args__ = (UniqueConstraint("itinerary_id", "step_order", name="uq_itinerary_steps_order"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    itinerary_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    poi_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pois.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    arrival_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departure_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    itinerary: Mapped[Itinerary] = relationship(back_populates="steps", lazy="selectin")
    poi: Mapped[POI] = relationship(back_populates="itinerary_steps", lazy="selectin")
