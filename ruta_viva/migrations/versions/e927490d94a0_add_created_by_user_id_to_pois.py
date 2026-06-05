"""add created_by_user_id to pois

Revision ID: e927490d94a0
Revises: k2l3m4n5o6p7
Create Date: 2026-06-04 14:08:26.476330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'e927490d94a0'
down_revision: Union[str, Sequence[str], None] = 'k2l3m4n5o6p7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pois", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_pois_created_by_user_id",
        "pois",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_pois_created_by_user_id", "pois", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_pois_created_by_user_id", table_name="pois")
    op.drop_constraint("fk_pois_created_by_user_id", "pois", type_="foreignkey")
    op.drop_column("pois", "created_by_user_id")
