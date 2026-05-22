"""add version column to ara_sessions for optimistic locking

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-22 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ara_sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE ara_sessions ADD CONSTRAINT ck_ara_sessions_version CHECK (version > 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE ara_sessions DROP CONSTRAINT IF EXISTS ck_ara_sessions_version")
    op.execute("ALTER TABLE ara_sessions DROP COLUMN IF EXISTS version")
