"""v_weight_trend (revision 0011) returns exactly what the recursive view of revision 0001
returned, on a long synthetic history with gaps, several readings a day and deletions."""

import datetime as dt
import random
from zoneinfo import ZoneInfo

from alembic import command
from sqlalchemy import Connection, Engine, text

from health_coach.db.admin import alembic_config

PRAGUE = ZoneInfo("Europe/Prague")
COLUMNS = "local_date, weight_kg, avg_7d_kg, trend_kg, weekly_rate_kg"


def _seed(conn: Connection, days: int, seed: int) -> None:
    rnd = random.Random(seed)  # noqa: S311 - reproducible test data
    today = dt.datetime.now(PRAGUE).date()
    rows = []
    skip_until = -1
    for i in range(days):
        day = today - dt.timedelta(days=days - 1 - i)
        if rnd.random() < 0.01:  # a run of missed days (holiday)
            skip_until = i + rnd.randrange(5, 20)
        if i < skip_until or rnd.random() < 0.2:
            continue
        base = 82 - i / 400 + rnd.uniform(-0.8, 0.8)
        for reading in range(rnd.choice([1, 1, 1, 2, 3])):
            hour = 6 + reading * 6
            rows.append(
                {
                    "ts": dt.datetime.combine(day, dt.time(hour, rnd.randrange(60)), PRAGUE),
                    "d": day,
                    "kg": round(base + reading * 0.4, 2),
                    "fat": round(rnd.uniform(16, 20), 1) if rnd.random() < 0.5 else None,
                    "deleted": rnd.random() < 0.02,
                }
            )
        if rnd.random() < 0.05:  # a reading with body fat only
            rows.append(
                {
                    "ts": dt.datetime.combine(day, dt.time(5, 0), PRAGUE),
                    "d": day,
                    "kg": None,
                    "fat": 18.0,
                    "deleted": False,
                }
            )
    conn.execute(
        text(
            "INSERT INTO body_metrics (ts, local_date, weight_kg, body_fat_pct, source, "
            "deleted_at) VALUES (:ts, :d, :kg, :fat, 'test', "
            "CASE WHEN :deleted THEN now() END)"
        ),
        rows,
    )


def _trend(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as conn:
        return [
            tuple(r) for r in conn.execute(text(f"SELECT {COLUMNS} FROM v_weight_trend ORDER BY 1"))
        ]


def test_linear_weight_trend_matches_the_recursive_view(owner: Engine) -> None:
    with owner.begin() as conn:
        _seed(conn, days=3 * 365, seed=42)
        definition = conn.execute(
            text("SELECT pg_get_viewdef('v_weight_trend'::regclass)")
        ).scalar_one()
    assert "RECURSIVE" not in definition.upper()
    linear = _trend(owner)

    cfg = alembic_config()
    command.downgrade(cfg, "0010")
    try:
        with owner.connect() as conn:
            definition = conn.execute(
                text("SELECT pg_get_viewdef('v_weight_trend'::regclass)")
            ).scalar_one()
        assert "RECURSIVE" in definition.upper()
        recursive = _trend(owner)
    finally:
        command.upgrade(cfg, "head")

    assert len(linear) > 700
    assert sum(1 for r in linear if r[4] is not None) > 650
    assert linear == recursive
    assert _trend(owner) == linear
