"""add verification confidence and rut fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pois",
        sa.Column("verification_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "pois",
        sa.Column("confidence_score", sa.Float, nullable=False, server_default="0.0"),
    )

    op.add_column(
        "entrepreneur_profiles",
        sa.Column("rut", sa.String(12), nullable=True),
    )
    op.add_column(
        "entrepreneur_profiles",
        sa.Column("verification_status", sa.String(20), nullable=False, server_default="unverified"),
    )

    op.create_unique_constraint("uq_entrepreneur_profiles_rut", "entrepreneur_profiles", ["rut"])

    op.execute(
        "UPDATE pois SET verification_status = 'verified', confidence_score = 0.7 "
        "WHERE entrepreneur_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("uq_entrepreneur_profiles_rut", "entrepreneur_profiles", type_="unique")
    op.drop_column("entrepreneur_profiles", "verification_status")
    op.drop_column("entrepreneur_profiles", "rut")
    op.drop_column("pois", "confidence_score")
    op.drop_column("pois", "verification_status")