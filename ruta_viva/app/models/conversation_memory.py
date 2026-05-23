from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ara_session import AraSession
    from app.models.tourist_profile import TouristProfile


class ConversationMemory(Base):
    __tablename__ = "conversation_memory"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tourist_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tourist_profiles.user_id"), nullable=False, index=True)
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ara_sessions.id", ondelete="CASCADE"), nullable=True)
    hecho: Mapped[str] = mapped_column(Text, nullable=False)
    categoria: Mapped[str] = mapped_column(String(50), nullable=False)
    confianza: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    contexto: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("confianza >= 0 AND confianza <= 1", name="ck_confianza_range"),
        Index("idx_conversation_memory_embedding", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}, postgresql_with={"m": 16, "ef_construction": 64}),
    )

    # Relationships
    tourist: Mapped["TouristProfile"] = relationship(back_populates="conversation_memories", lazy="selectin")
    session: Mapped["AraSession | None"] = relationship(back_populates="conversation_memories", lazy="selectin")
