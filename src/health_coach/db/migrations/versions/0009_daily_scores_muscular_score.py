"""daily_scores muscular_score column

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Table-level grants from 0005 already cover the new column.
    op.add_column("daily_scores", sa.Column("muscular_score", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_scores", "muscular_score")
