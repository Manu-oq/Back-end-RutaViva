"""add conversation_memory table for Ara v2 semantic memory

Revision ID: i6a7b8c9d0e1
Revises: h5a6b7c8d9e0
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "i6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "h5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tourist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hecho", sa.Text(), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("confianza", sa.Float(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column("contexto", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("confianza BETWEEN 0 AND 1", name="ck_conversation_memory_confianza"),
        sa.ForeignKeyConstraint(["session_id"], ["ara_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tourist_id"], ["tourist_profiles.user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_memory_tourist_id"), "conversation_memory", ["tourist_id"])
    op.execute(
        "CREATE INDEX idx_conversation_memory_embedding ON conversation_memory USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_memory_tourist_id"), table_name="conversation_memory")
    op.drop_table("conversation_memory")
