from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, func, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.entrepreneur_profile import EntrepreneurProfile
    from app.models.tourist_profile import TouristProfile


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    tourist_profile: Mapped[TouristProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )
    entrepreneur_profile: Mapped[EntrepreneurProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )

    @property
    def display_name(self) -> str | None:
        if self.tourist_profile is not None:
            return self.tourist_profile.full_name

        if self.entrepreneur_profile is not None and self.entrepreneur_profile.admin_data is not None:
            value = self.entrepreneur_profile.admin_data.get("display_name")
            return str(value) if value is not None else None

        return None
