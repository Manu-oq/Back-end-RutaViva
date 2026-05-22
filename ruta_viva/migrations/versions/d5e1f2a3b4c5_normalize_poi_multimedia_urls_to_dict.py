"""normalize_poi_multimedia_urls_to_dict

Revision ID: d5e1f2a3b4c5
Revises: d0e1f2a3b4c5
Create Date: 2026-05-22 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d5e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE pois SET multimedia_urls = '{\"cover\": null, \"gallery\": []}'::jsonb "
        "WHERE multimedia_urls IS NOT NULL AND jsonb_typeof(multimedia_urls) = 'array'"
    )
    op.execute(
        "ALTER TABLE pois ADD CONSTRAINT ck_pois_multimedia_urls_is_object "
        "CHECK (multimedia_urls IS NULL OR jsonb_typeof(multimedia_urls) = 'object')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pois DROP CONSTRAINT IF EXISTS ck_pois_multimedia_urls_is_object")
