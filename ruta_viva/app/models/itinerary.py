from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.itinerary_step import ItineraryStep
    from app.models.tourist_profile import TouristProfile


class Itinerary(Base):
    __tablename__ = "itineraries"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tourist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tourist_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned", server_default="planned")

    tourist: Mapped[TouristProfile] = relationship(back_populates="itineraries", lazy="selectin")
    steps: Mapped[list[ItineraryStep]] = relationship(
        back_populates="itinerary",
        lazy="selectin",
        order_by="ItineraryStep.step_order",
    )
