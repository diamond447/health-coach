"""single-pass v_body_daily and daily_range()

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent


def _body_daily_0001() -> str:
    sql = (HERE / "0001_views.sql").read_text()
    start = sql.index("CREATE VIEW v_body_daily AS")
    end = sql.index(";", start) + 1
    return sql[start:end].replace("CREATE VIEW", "CREATE OR REPLACE VIEW", 1)


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0013_daily_range.sql").read_text())


def downgrade() -> None:
    op.execute("DROP FUNCTION daily_range(date, date)")
    op.execute(_body_daily_0001())
