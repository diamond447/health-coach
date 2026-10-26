"""web_journal role

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'web_journal') THEN
                CREATE ROLE web_journal NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO web_journal;")
    op.execute("GRANT SELECT, INSERT ON journal_entries TO web_journal;")
    op.execute(
        "GRANT UPDATE (amount, note, updated_at, deleted_at) ON journal_entries TO web_journal;"
    )
    op.execute("GRANT USAGE ON SEQUENCE journal_entries_id_seq TO web_journal;")
    op.execute("ALTER ROLE web_journal SET statement_timeout = '5s';")
    op.execute("ALTER ROLE web_journal SET idle_in_transaction_session_timeout = '30s';")


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SEQUENCE journal_entries_id_seq FROM web_journal;")
    op.execute("REVOKE ALL PRIVILEGES ON journal_entries FROM web_journal;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM web_journal;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'web_journal') THEN
                DROP OWNED BY web_journal;
                DROP ROLE web_journal;
            END IF;
        END
        $$;
        """
    )
