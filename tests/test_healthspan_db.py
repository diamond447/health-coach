"""Database tests for weekly healthspan computation, worker job, and MCP tool."""

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from mcp import Client
from sqlalchemy import Engine, text

from health_coach.config import Settings
from health_coach.db.engine import Role, get_engine
from health_coach.jobs.healthspan import (
    compute_healthspan_for_week,
    refresh_healthspan,
)
from health_coach.mcp_server.server import create_server

PRAGUE = ZoneInfo("Europe/Prague")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def call(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    async with Client(create_server()) as client:
        result = await client.call_tool(tool, args or {})
    assert not result.is_error, result.content
    content: dict[str, Any] | None = result.structured_content
    assert content is not None
    return content


def _seed_synthetic_healthspan_data(conn: Any, week_start: dt.date) -> None:
    """Seed 26 weeks of synthetic data ending at week_start + 6 days."""
    window_start = week_start - dt.timedelta(weeks=25)
    total_days = (week_start + dt.timedelta(days=6) - window_start).days + 1

    for i in range(total_days):
        d = window_start + dt.timedelta(days=i)

        # 1. Daily vitals: resting HR 54, cardio fitness 42 (on days i % 14 == 0)
        cardio = 42.0 if i % 14 == 0 else None
        conn.execute(
            text(
                "INSERT INTO daily_vitals (local_date, resting_hr, cardio_fitness, source) "
                "VALUES (:d, 54.0, :cf, 'google_health') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {"d": d, "cf": cardio},
        )

        # 2. Daily activity: 9000 steps
        conn.execute(
            text(
                "INSERT INTO daily_activity (local_date, steps, source) "
                "VALUES (:d, 9000, 'google_health') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {"d": d},
        )

        # 3. Daily scores: sleep consistency 80, sleep actual 440 min (~7.3 h), zone minutes
        zm = {"Z1": 20, "Z2": 15, "Z3": 10, "Z4": 5, "Z5": 0}  # 45 min mod/day, 5 min vig/day
        conn.execute(
            text(
                "INSERT INTO daily_scores (local_date, sleep_consistency, sleep_actual_min, "
                "zone_minutes, algo_version, source) VALUES "
                "(:d, 80, 440, CAST(:zm AS jsonb), 1, 'worker') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {"d": d, "zm": json.dumps(zm)},
        )

        # 4. Body metrics: 18% body fat every 14 days
        if i % 14 == 0:
            ts = dt.datetime.combine(d, dt.time(8, 0), PRAGUE)
            conn.execute(
                text(
                    "INSERT INTO body_metrics (ts, local_date, body_fat_pct, source) "
                    "VALUES (:ts, :d, 18.0, 'openfoodfacts') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"ts": ts, "d": d},
            )

        # 5. Strength session 3x a week (Mon, Wed, Fri)
        if d.weekday() in (0, 2, 4):
            start_ts = dt.datetime.combine(d, dt.time(17, 0), PRAGUE)
            end_ts = dt.datetime.combine(d, dt.time(18, 0), PRAGUE)
            conn.execute(
                text(
                    "INSERT INTO strength_sessions "
                    "(external_id, local_date, start_ts, end_ts, source) "
                    "VALUES (:ext, :d, :st, :et, 'opengym') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"ext": f"gym-{d.isoformat()}", "d": d, "st": start_ts, "et": end_ts},
            )


def test_compute_healthspan_persists_to_db(owner: Engine) -> None:
    engine = get_engine(Role.owner)
    week_start = dt.date(2026, 10, 19)  # Monday
    settings = Settings(birth_year=1984, sex="male")

    with engine.begin() as conn:
        _seed_synthetic_healthspan_data(conn, week_start)
        res = compute_healthspan_for_week(conn, week_start, settings)

    assert res.delta_years is not None
    # All 9 factors should have data
    assert res.factors_with_data == 9
    assert res.age == 42  # 2026 - 1984
    assert res.biological_age == round(42 + res.delta_years, 1)

    # Verify database persistence
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT week_start, delta_years, pace, factors_with_data, age, algo_version "
                "FROM healthspan_weekly WHERE week_start = :w"
            ),
            {"w": week_start},
        ).one()
        assert row.week_start == week_start
        assert float(row.delta_years) == res.delta_years
        assert row.factors_with_data == 9
        assert row.age == 42
        assert row.algo_version == 1


def test_refresh_healthspan_backfill_and_pace(owner: Engine) -> None:
    engine = get_engine(Role.owner)
    week_start = dt.date(2026, 10, 19)
    settings = Settings(birth_year=1984, sex="male", timezone="Europe/Prague")

    with engine.begin() as conn:
        _seed_synthetic_healthspan_data(conn, week_start)

    # Backfill 12 weeks
    count = refresh_healthspan(engine, weeks_back=12, settings=settings)
    assert count == 12

    # Verify that later weeks now have pace computed (since >= 8 weeks are available)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT week_start, delta_years, pace FROM healthspan_weekly ORDER BY week_start")
        ).all()
        assert len(rows) == 12
        # Early weeks will have pace=None, but by week 8+ pace should be a valid number
        latest_row = rows[-1]
        assert latest_row.pace is not None
        assert 0.5 <= float(latest_row.pace) <= 1.5


async def test_mcp_get_healthspan_tool(owner: Engine) -> None:
    engine = get_engine(Role.owner)
    week_start = dt.date(2026, 10, 19)
    settings = Settings(birth_year=1984, sex="male")

    with engine.begin() as conn:
        _seed_synthetic_healthspan_data(conn, week_start)
        compute_healthspan_for_week(conn, week_start, settings)

    res = await call("get_healthspan", {"weeks": 4})
    assert "latest" in res
    assert "history" in res
    assert "disclaimer" in res
    assert "estimate" in res["disclaimer"].lower()

    latest = res["latest"]
    assert latest is not None
    assert latest["age"] == 42
    assert latest["factors_with_data"] == 9
    assert len(latest["factors"]) == 9
    assert latest["delta_years"] is not None
    assert latest["biological_age"] == round(42 + float(latest["delta_years"]), 1)
