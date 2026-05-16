"""add ara conversation sessions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ara_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tourist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="clarifying", nullable=False),
        sa.Column("initial_query", sa.String(length=1000), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("radius", sa.Float(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("intent_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preferences_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("candidate_poi_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated_itinerary_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["generated_itinerary_id"], ["itineraries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tourist_id"], ["tourist_profiles.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ara_sessions_generated_itinerary_id"), "ara_sessions", ["generated_itinerary_id"])
    op.create_index(op.f("ix_ara_sessions_tourist_id"), "ara_sessions", ["tourist_id"])

    op.create_table(
        "ara_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("quick_replies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["ara_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ara_messages_session_id"), "ara_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ara_messages_session_id"), table_name="ara_messages")
    op.drop_table("ara_messages")
    op.drop_index(op.f("ix_ara_sessions_tourist_id"), table_name="ara_sessions")
    op.drop_index(op.f("ix_ara_sessions_generated_itinerary_id"), table_name="ara_sessions")
    op.drop_table("ara_sessions")
