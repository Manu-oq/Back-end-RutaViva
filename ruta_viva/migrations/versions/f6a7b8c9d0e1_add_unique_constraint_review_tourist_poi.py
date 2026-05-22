"""add unique constraint review tourist poi

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_reviews_tourist_poi", "reviews", ["tourist_id", "poi_id"])


def downgrade() -> None:
    op.drop_constraint("uq_reviews_tourist_poi", "reviews", type_="unique")
