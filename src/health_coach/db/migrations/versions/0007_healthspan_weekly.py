"""weekly estimated biological age (healthspan) and pace of aging

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "healthspan_weekly",
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("delta_years", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("pace", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("factors_with_data", sa.SmallInteger(), nullable=False),
        sa.Column("age", sa.SmallInteger(), nullable=True),
        sa.Column("algo_version", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.Text(), server_default="worker", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("week_start", name=op.f("pk_healthspan_weekly")),
    )
    op.execute("GRANT SELECT ON healthspan_weekly TO coach_ro, coach_rw, ingest, grafana_ro;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON healthspan_weekly TO ingest;")


def downgrade() -> None:
    op.drop_table("healthspan_weekly")
