from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, func
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
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
