from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.entrepreneur_post import EntrepreneurPost
    from app.models.poi import POI
    from app.models.user import User


class EntrepreneurProfile(Base):
    __tablename__ = "entrepreneur_profiles"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'rejected')",
            name="ck_entrepreneur_profiles_verification_status",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    rut: Mapped[str | None] = mapped_column(String(12), nullable=True, unique=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified", server_default="unverified")
    admin_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="entrepreneur_profile", lazy="selectin")
    pois: Mapped[list[POI]] = relationship(back_populates="entrepreneur", lazy="noload")
    posts: Mapped[list[EntrepreneurPost]] = relationship(back_populates="entrepreneur", lazy="noload")
