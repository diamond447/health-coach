"""Load tests/fixtures/seed_history.sql (also usable with psql, see its header)."""

import re
from pathlib import Path

from sqlalchemy import Engine

SEED_SQL = Path(__file__).parent / "fixtures" / "seed_history.sql"


def seed_history(engine: Engine, days: int = 1095, hr_days: int = 7) -> None:
    """Synthetic history of `days` days (plus `hr_days` of intraday heart rate)."""
    lines = [ln for ln in SEED_SQL.read_text().splitlines() if not ln.startswith("\\")]
    sql = "\n".join(lines)
    sql = re.sub(r"(?<!:):days\b", str(int(days)), sql)
    sql = re.sub(r"(?<!:):hr_days\b", str(int(hr_days)), sql)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        assert raw is not None
        raw.execute(sql)
