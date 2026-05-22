"""add public_id column to itineraries for sharing

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-22 04:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE itineraries ADD COLUMN public_id VARCHAR(12) NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_itineraries_public_id "
        "ON itineraries (public_id) WHERE public_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_itineraries_public_id")
    op.execute("ALTER TABLE itineraries DROP COLUMN IF EXISTS public_id")
