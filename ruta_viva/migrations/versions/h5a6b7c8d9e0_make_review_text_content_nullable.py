"""make review text_content nullable

Revision ID: h5a6b7c8d9e0
Revises: g4a5b6c7d8e9
Create Date: 2026-05-22 05:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "g4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("reviews", "text_content", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("reviews", "text_content", existing_type=sa.Text(), nullable=False)
