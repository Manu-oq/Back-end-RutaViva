"""add frontend sync features

Revision ID: a1b2c3d4e5f6
Revises: 9f4a1b2c3d4e
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9f4a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))

    op.create_table(
        "entrepreneur_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entrepreneur_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entrepreneur_id"], ["entrepreneur_profiles.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_entrepreneur_posts_entrepreneur_id"), "entrepreneur_posts", ["entrepreneur_id"])

    op.create_table(
        "poi_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("poi_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=80), server_default="frontend", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["poi_id"], ["pois.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visitor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_poi_visits_poi_id"), "poi_visits", ["poi_id"])
    op.create_index(op.f("ix_poi_visits_visitor_id"), "poi_visits", ["visitor_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_poi_visits_visitor_id"), table_name="poi_visits")
    op.drop_index(op.f("ix_poi_visits_poi_id"), table_name="poi_visits")
    op.drop_table("poi_visits")
    op.drop_index(op.f("ix_entrepreneur_posts_entrepreneur_id"), table_name="entrepreneur_posts")
    op.drop_table("entrepreneur_posts")
    op.drop_column("users", "avatar_url")
