"""add parent_id to categories for hierarchical taxonomy

Revision ID: j1k2l3m4n5o6
Revises: i6a7b8c9d0e1
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CATEGORY_HIERARCHY = {
    1: None,
    2: None,
    3: None,
    4: None,
    5: None,
    6: 1,
    7: 1,
    8: 1,
    9: None,
    10: 1,
    11: 5,
    12: None,
    13: None,
    14: None,
    15: None,
}


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("parent_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_categories_parent_id",
        "categories",
        "categories",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("parent_id", sa.Integer),
    )

    for category_id, parent_id in CATEGORY_HIERARCHY.items():
        op.execute(
            categories.update()
            .where(categories.c.id == category_id)
            .values(parent_id=parent_id)
        )


def downgrade() -> None:
    op.drop_constraint("fk_categories_parent_id", "categories", type_="foreignkey")
    op.drop_column("categories", "parent_id")
