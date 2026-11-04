"""v_weight_trend as a linear window aggregate

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent


def recursive_weight_trend() -> str:
    """The v_weight_trend definition of revision 0001, as CREATE OR REPLACE."""
    sql = (HERE / "0001_views.sql").read_text()
    start = sql.index("CREATE VIEW v_weight_trend AS")
    end = sql.index(";", start) + 1
    return sql[start:end].replace("CREATE VIEW", "CREATE OR REPLACE VIEW", 1)


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0011_weight_trend.sql").read_text())


def downgrade() -> None:
    op.execute(recursive_weight_trend())
    op.execute("DROP AGGREGATE weight_ema(date, numeric)")
    op.execute("DROP FUNCTION weight_ema_final(numeric[])")
    op.execute("DROP FUNCTION weight_ema_step(numeric[], date, numeric)")
