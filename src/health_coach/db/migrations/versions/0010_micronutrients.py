"""micronutrients in foods and nutrition_entries

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Table-level grants already cover the new columns (no new grants).
    op.add_column(
        "foods",
        sa.Column("micros_100g", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "nutrition_entries",
        sa.Column("micros", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nutrition_entries", "micros")
    op.drop_column("foods", "micros_100g")
