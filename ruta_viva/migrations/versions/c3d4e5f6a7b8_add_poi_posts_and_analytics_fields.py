"""add poi_posts and analytics fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM entrepreneur_posts")

    op.add_column(
        "entrepreneur_posts",
        sa.Column("poi_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.add_column(
        "entrepreneur_posts",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "entrepreneur_posts",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_entrepreneur_posts_poi_id",
        "entrepreneur_posts",
        "pois",
        ["poi_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_entrepreneur_posts_poi_id"),
        "entrepreneur_posts",
        ["poi_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_entrepreneur_posts_poi_id"), table_name="entrepreneur_posts")
    op.drop_constraint("fk_entrepreneur_posts_poi_id", "entrepreneur_posts", type_="foreignkey")
    op.drop_column("entrepreneur_posts", "scheduled_at")
    op.drop_column("entrepreneur_posts", "is_pinned")
    op.drop_column("entrepreneur_posts", "poi_id")