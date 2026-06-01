from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.poi_category import POICategory


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    parent: Mapped[Optional[Category]] = relationship(back_populates="children", remote_side="Category.id", lazy="selectin")
    children: Mapped[list[Category]] = relationship(back_populates="parent", lazy="selectin")

    poi_links: Mapped[list[POICategory]] = relationship(back_populates="category", lazy="noload")
