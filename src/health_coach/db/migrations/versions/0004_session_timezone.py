"""v_daily ends today in the session time zone

Revision ID: 0004
Revises: 0003

Until now v_daily ended on today's date in a fixed time zone. It now uses CURRENT_DATE,
which follows the session's TimeZone: the app sets it from HC_TIMEZONE on every
connection, and `health-coach db sync-roles` makes it the database default.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent
FIXED_TODAY = "(now() AT TIME ZONE 'Europe/Prague')::date"


def _v_daily() -> str:
    """The v_daily definition of revision 0001, as CREATE OR REPLACE."""
    sql = (HERE / "0001_views.sql").read_text()
    start = sql.index("CREATE VIEW v_daily AS")
    end = sql.index(";", start) + 1
    view = sql[start:end].replace("CREATE VIEW", "CREATE OR REPLACE VIEW", 1)
    assert FIXED_TODAY in view
    return view


def upgrade() -> None:
    op.execute(_v_daily().replace(FIXED_TODAY, "CURRENT_DATE"))
    op.alter_column("sleep_sessions", "local_date", comment="Wake-up date, local time zone")


def downgrade() -> None:
    op.execute(_v_daily())
    op.alter_column("sleep_sessions", "local_date", comment="Wake-up date, Europe/Prague")
