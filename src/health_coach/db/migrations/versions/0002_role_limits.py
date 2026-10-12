"""role limits

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HERE = Path(__file__).parent


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    cursor.execute((HERE / "0002_role_limits.sql").read_text())


def downgrade() -> None:
    op.execute("ALTER ROLE coach_ro RESET work_mem")
    op.execute("ALTER ROLE coach_ro RESET temp_file_limit")
    op.execute("ALTER ROLE grafana_ro RESET work_mem")
    op.execute("ALTER ROLE grafana_ro RESET temp_file_limit")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO coach_rw")
