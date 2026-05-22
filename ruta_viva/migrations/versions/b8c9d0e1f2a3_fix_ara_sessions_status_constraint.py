"""fix ara_sessions status constraint

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ara_sessions DROP CONSTRAINT IF EXISTS ck_ara_sessions_status")
    op.execute(
        "ALTER TABLE ara_sessions ADD CONSTRAINT ck_ara_sessions_status "
        "CHECK (status IN ('clarifying', 'searching', 'ready_to_generate', "
        "'queued', 'generating', 'suggesting_step_replacement', "
        "'step_replaced', 'completed', 'failed'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ara_sessions DROP CONSTRAINT IF EXISTS ck_ara_sessions_status")
    op.execute(
        "ALTER TABLE ara_sessions ADD CONSTRAINT ck_ara_sessions_status "
        "CHECK (status IN ('clarifying', 'searching', 'generating', 'completed', 'failed'))"
    )
