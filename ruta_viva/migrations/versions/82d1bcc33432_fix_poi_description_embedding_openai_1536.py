"""Lock POI description_embedding to OpenAI 1536 dimensions

Revision ID: 82d1bcc33432
Revises: 13e4146989e2
Create Date: 2026-04-30 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "82d1bcc33432"
down_revision: Union[str, Sequence[str], None] = "13e4146989e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    incompatible_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM pois
            WHERE description_embedding IS NULL
               OR vector_dims(description_embedding) <> 1536
            """
        )
    ).scalar_one()
    if incompatible_count and incompatible_count > 0:
        raise RuntimeError(
            "Cannot lock pois.description_embedding to vector(1536) NOT NULL because some rows are NULL "
            "or use a non-1536 embedding. Backfill those embeddings with OpenAI first, then rerun this migration."
        )

    op.execute(
        sa.text(
            """
            ALTER TABLE pois
            ALTER COLUMN description_embedding
            TYPE vector(1536)
            USING description_embedding::vector(1536)
            """
        )
    )

    op.alter_column(
        "pois",
        "description_embedding",
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "pois",
        "description_embedding",
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        nullable=True,
    )

    op.execute(
        sa.text(
            """
            ALTER TABLE pois
            ALTER COLUMN description_embedding
            TYPE vector
            USING description_embedding::vector
            """
        )
    )
