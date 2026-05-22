"""ara location and candidate uuid array

Revision ID: a7b8c9d0e1f2
Revises: 088edfdc10c4
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "088edfdc10c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ara_sessions",
        sa.Column("location", Geometry("POINT", srid=4326), nullable=True),
    )
    op.execute(
        """
        UPDATE ara_sessions
        SET location = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        """
    )
    op.drop_column("ara_sessions", "lat")
    op.drop_column("ara_sessions", "lon")

    op.add_column(
        "ara_sessions",
        sa.Column(
            "candidate_poi_ids_uuid",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE ara_sessions
        SET candidate_poi_ids_uuid = (
            SELECT array_agg(value::uuid)
            FROM jsonb_array_elements_text(candidate_poi_ids) AS value
        )
        WHERE candidate_poi_ids IS NOT NULL
          AND jsonb_typeof(candidate_poi_ids) = 'array'
        """
    )
    op.drop_column("ara_sessions", "candidate_poi_ids")
    op.alter_column("ara_sessions", "candidate_poi_ids_uuid", new_column_name="candidate_poi_ids")


def downgrade() -> None:
    op.add_column("ara_sessions", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("ara_sessions", sa.Column("lon", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE ara_sessions
        SET lat = ST_Y(location),
            lon = ST_X(location)
        WHERE location IS NOT NULL
        """
    )
    op.drop_column("ara_sessions", "location")

    op.add_column(
        "ara_sessions",
        sa.Column("candidate_poi_ids_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE ara_sessions
        SET candidate_poi_ids_jsonb = to_jsonb(candidate_poi_ids::text[])
        WHERE candidate_poi_ids IS NOT NULL
        """
    )
    op.drop_column("ara_sessions", "candidate_poi_ids")
    op.alter_column("ara_sessions", "candidate_poi_ids_jsonb", new_column_name="candidate_poi_ids")
