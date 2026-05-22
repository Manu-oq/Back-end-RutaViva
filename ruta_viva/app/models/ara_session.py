from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ara_message import AraMessage
    from app.models.itinerary import Itinerary
    from app.models.tourist_profile import TouristProfile


class AraSession(Base):
    __tablename__ = "ara_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('clarifying', 'searching', 'ready_to_generate', 'queued', 'generating', 'suggesting_step_replacement', 'step_replaced', 'completed', 'failed')",
            name="ck_ara_sessions_status",
        ),
        CheckConstraint(
            "radius IS NULL OR radius > 0",
            name="ck_ara_sessions_radius",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tourist_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tourist_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="clarifying", server_default="clarifying")
    initial_query: Mapped[str] = mapped_column(String(1000), nullable=False)
    location: Mapped[str | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    radius: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intent_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    preferences_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    candidate_poi_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=True)
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

    @property
    def lat(self) -> float | None:
        return getattr(self, "_lat", None)

    @lat.setter
    def lat(self, value: float | None) -> None:
        self._set_location(value, self.lon)

    @property
    def lon(self) -> float | None:
        return getattr(self, "_lon", None)

    @lon.setter
    def lon(self, value: float | None) -> None:
        self._set_location(self.lat, value)

    def set_coordinates(self, lat: float | None, lon: float | None) -> None:
        self._set_location(lat, lon)

    def _set_location(self, lat: float | None, lon: float | None) -> None:
        self._lat = lat
        self._lon = lon
        if lat is None or lon is None:
            self.location = None
            return
        self.location = WKTElement(f"POINT({lon} {lat})", srid=4326)
