"""daily WHOOP-style scores (recovery, strain, sleep)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_scores",
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("recovery", sa.SmallInteger(), nullable=True),
        sa.Column("recovery_z", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("recovery_components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("strain", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("cardio_load", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("muscular_load", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("zone_minutes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("activities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("strain_target_low", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("strain_target_high", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("sleep_need_min", sa.Integer(), nullable=True),
        sa.Column("sleep_actual_min", sa.Integer(), nullable=True),
        sa.Column("sleep_debt_min", sa.Integer(), nullable=True),
        sa.Column("sleep_performance", sa.SmallInteger(), nullable=True),
        sa.Column("sleep_efficiency", sa.SmallInteger(), nullable=True),
        sa.Column("sleep_consistency", sa.SmallInteger(), nullable=True),
        sa.Column("planned_bedtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_wake", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.PrimaryKeyConstraint("local_date", name=op.f("pk_daily_scores")),
    )
    op.execute("GRANT SELECT ON daily_scores TO coach_ro, coach_rw, ingest, grafana_ro;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON daily_scores TO ingest;")


def downgrade() -> None:
    op.drop_table("daily_scores")
