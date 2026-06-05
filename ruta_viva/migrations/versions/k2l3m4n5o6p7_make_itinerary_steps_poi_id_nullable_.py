"""make itinerary_steps poi_id nullable, add is_generic and name columns

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("itinerary_steps", "poi_id",
                    existing_type=postgresql.UUID(),
                    nullable=True)

    op.drop_constraint("itinerary_steps_poi_id_fkey", "itinerary_steps", type_="foreignkey")
    op.create_foreign_key(
        "itinerary_steps_poi_id_fkey",
        "itinerary_steps",
        "pois",
        ["poi_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("itinerary_steps",
                  sa.Column("is_generic", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("itinerary_steps",
                  sa.Column("name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("itinerary_steps", "name")
    op.drop_column("itinerary_steps", "is_generic")

    op.drop_constraint("itinerary_steps_poi_id_fkey", "itinerary_steps", type_="foreignkey")
    op.create_foreign_key(
        "itinerary_steps_poi_id_fkey",
        "itinerary_steps",
        "pois",
        ["poi_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column("itinerary_steps", "poi_id",
                    existing_type=postgresql.UUID(),
                    nullable=False)
