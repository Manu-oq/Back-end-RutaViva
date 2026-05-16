"""add poi visit rules and extended categories

Revision ID: 9f4a1b2c3d4e
Revises: 82d1bcc33432
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "9f4a1b2c3d4e"
down_revision: Union[str, None] = "82d1bcc33432"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EXTENDED_CATEGORIES = [
    {"id": 1, "name": "Naturaleza"},
    {"id": 2, "name": "Gastronomía"},
    {"id": 3, "name": "Turismo"},
    {"id": 4, "name": "Alojamiento"},
    {"id": 5, "name": "Cultura"},
    {"id": 6, "name": "Trekking/Senderismo"},
    {"id": 7, "name": "Lagos/Ríos/Playas"},
    {"id": 8, "name": "Montañas/Volcanes/Miradores"},
    {"id": 9, "name": "Termas/Bienestar"},
    {"id": 10, "name": "Parques/Reservas"},
    {"id": 11, "name": "Museos/Patrimonio"},
    {"id": 12, "name": "Aventura/Deportes"},
    {"id": 13, "name": "Servicios turísticos/Información"},
    {"id": 14, "name": "Transporte/Accesos"},
    {"id": 15, "name": "Artesanía/Compras locales"},
]


def upgrade() -> None:
    op.add_column("pois", sa.Column("opening_hours_text", sa.String(length=500), nullable=True))
    op.add_column("pois", sa.Column("visit_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    categories_table = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("icon_url", sa.String),
    )

    for category in EXTENDED_CATEGORIES:
        op.execute(
            postgresql.insert(categories_table)
            .values(id=category["id"], name=category["name"], icon_url=None)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={"name": category["name"], "icon_url": None},
            )
        )

    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('categories', 'id'),
            COALESCE((SELECT MAX(id) FROM categories), 1),
            true
        )
        """
    )


def downgrade() -> None:
    op.drop_column("pois", "visit_rules")
    op.drop_column("pois", "opening_hours_text")
