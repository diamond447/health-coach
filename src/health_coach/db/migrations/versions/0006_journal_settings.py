"""journal entries, app settings, and notification deduplication

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("behavior", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), server_default="chat", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_entries")),
    )
    op.create_index(
        "ix_journal_entries_local_date",
        "journal_entries",
        ["local_date"],
        unique=False,
    )
    op.create_index(
        "uq_journal_entries_local_date_behavior",
        "journal_entries",
        ["local_date", "behavior"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )

    op.create_table(
        "notifications_sent",
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("local_date", "kind", name=op.f("pk_notifications_sent")),
    )

    op.execute(
        "GRANT SELECT ON journal_entries, app_settings TO coach_ro, coach_rw, ingest, grafana_ro;"
    )
    op.execute("GRANT INSERT, UPDATE, DELETE ON journal_entries, app_settings TO coach_rw;")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO coach_rw;")

    op.execute("GRANT SELECT, INSERT, DELETE ON notifications_sent TO ingest;")
    op.execute("GRANT SELECT ON notifications_sent TO grafana_ro;")


def downgrade() -> None:
    op.drop_table("notifications_sent")
    op.drop_table("app_settings")
    op.drop_index(
        "uq_journal_entries_local_date_behavior",
        table_name="journal_entries",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_journal_entries_local_date"), table_name="journal_entries")
    op.drop_table("journal_entries")
