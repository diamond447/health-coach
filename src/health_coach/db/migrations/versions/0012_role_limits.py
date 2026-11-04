"""parallelism, connection and idle limits for the query roles

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0012_role_limits.sql").read_text())


def downgrade() -> None:
    op.execute("ALTER ROLE coach_ro RESET max_parallel_workers_per_gather")
    op.execute("ALTER ROLE coach_ro RESET lock_timeout")
    op.execute("ALTER ROLE coach_ro CONNECTION LIMIT -1")
    op.execute("ALTER ROLE grafana_ro RESET max_parallel_workers_per_gather")
    op.execute("ALTER ROLE grafana_ro RESET idle_in_transaction_session_timeout")
    op.execute("ALTER ROLE grafana_ro CONNECTION LIMIT -1")
    op.execute("ALTER ROLE coach_rw RESET idle_in_transaction_session_timeout")
