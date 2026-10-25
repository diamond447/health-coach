"""Database tests for daily WHOOP-style scores computation, worker job, and MCP tools."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from mcp import Client
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from health_coach.db.engine import Role, get_engine
from health_coach.jobs.scores import compute_scores, refresh_scores
from health_coach.mcp_server.common import today
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


def _seed_synthetic_data(conn: Any, day: dt.date) -> None:
    # 1. 30 trailing nights of vitals (D-30 to D-1)
    for i in range(30, 0, -1):
        d = day - dt.timedelta(days=i)
        conn.execute(
            text(
                "INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms, "
                "breathing_rate, skin_temp_delta, spo2_avg, source) VALUES "
                "(:d, :rhr, :hrv, :br, :temp, :spo2, 'google_health')"
            ),
            {
                "d": d,
                "rhr": 60 + (i % 3),
                "hrv": 50.0 + (i % 5),
                "br": 14.0,
                "temp": 0.0,
                "spo2": 98.0,
            },
        )
        # Main sleep sessions for debt history
        start = dt.datetime.combine(d - dt.timedelta(days=1), dt.time(23, 0), PRAGUE)
        end = dt.datetime.combine(d, dt.time(7, 0), PRAGUE)
        conn.execute(
            text(
                "INSERT INTO sleep_sessions (external_id, local_date, start_ts, end_ts, "
                "duration_min, time_in_bed_min, efficiency, is_main, source) VALUES "
                "(:ext, :d, :start, :end, 460, 480, 95, true, 'google_health')"
            ),
            {"ext": f"sleep-{d}", "d": d, "start": start, "end": end},
        )

    # 2. Vitals for day D
    conn.execute(
        text(
            "INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms, "
            "breathing_rate, skin_temp_delta, spo2_avg, source) VALUES "
            "(:d, 58, 55.0, 14.0, 0.1, 98.0, 'google_health')"
        ),
        {"d": day},
    )

    # 3. Main sleep ending on day D
    start_d = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(23, 0), PRAGUE)
    end_d = dt.datetime.combine(day, dt.time(7, 0), PRAGUE)
    conn.execute(
        text(
            "INSERT INTO sleep_sessions (external_id, local_date, start_ts, end_ts, "
            "duration_min, time_in_bed_min, efficiency, is_main, source) VALUES "
            "(:ext, :d, :start, :end, 450, 480, 94, true, 'google_health')"
        ),
        {"ext": f"sleep-{day}", "d": day, "start": start_d, "end": end_d},
    )

    # 4. Exercise workout and HR samples on day D
    workout_start = dt.datetime.combine(day, dt.time(10, 0), PRAGUE)
    workout_end = dt.datetime.combine(day, dt.time(11, 0), PRAGUE)
    conn.execute(
        text(
            "INSERT INTO exercise_sessions (external_id, local_date, start_ts, end_ts, "
            "activity_type, duration_min, avg_hr, max_hr, source) VALUES "
            "('run-1', :d, :start, :end, 'running', 60, 145, 160, 'google_health')"
        ),
        {"d": day, "start": workout_start, "end": workout_end},
    )

    # 60 HR samples (1 per minute)
    for m in range(60):
        ts = workout_start + dt.timedelta(minutes=m)
        conn.execute(
            text(
                "INSERT INTO heart_rate_samples (ts, bpm, source) "
                "VALUES (:ts, 145, 'google_health')"
            ),
            {"ts": ts},
        )


async def test_compute_scores_and_mcp_tools(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        _seed_synthetic_data(conn, day)

    # Ingest role computes scores
    engine = get_engine(Role.ingest)
    compute_scores(engine, day)

    # Verify daily_scores row
    with get_engine(Role.ro).connect() as conn:
        row = conn.execute(
            text("SELECT * FROM daily_scores WHERE local_date = :d"),
            {"d": day},
        ).one()

    assert row.local_date == day
    assert row.recovery is not None
    assert row.recovery >= 67  # good vitals -> green
    assert row.recovery_z is not None
    assert isinstance(row.recovery_components, list)
    assert row.strain is not None and row.strain > 0.0
    assert row.cardio_load is not None and row.cardio_load > 0.0
    assert row.zone_minutes is not None
    assert len(row.activities) == 1
    assert row.activities[0]["name"] == "running"
    assert row.sleep_need_min is not None
    assert row.sleep_actual_min == 450
    assert row.sleep_performance is not None
    assert row.planned_bedtime is not None
    assert row.planned_wake is not None
    assert row.algo_version == 1

    # Test MCP tool get_scores
    scores_res = await call("get_scores", {"start": day.isoformat(), "end": day.isoformat()})
    assert len(scores_res["rows"]) == 1
    scored_day = scores_res["rows"][0]
    assert scored_day["local_date"] == day.isoformat()
    assert scored_day["recovery_zone"] == "green"
    assert scored_day["sleep_need"] is not None  # e.g. "8h 00m"
    assert scored_day["sleep_actual"] == "7h 30m"  # 450 min

    # Test get_context_snapshot includes scores_today
    snap = await call("get_context_snapshot")
    assert "scores_today" in snap
    assert snap["scores_today"] is not None
    assert snap["scores_today"]["recovery"] == row.recovery
    assert snap["scores_today"]["recovery_zone"] == "green"
    assert snap["scores_today"]["strain"] == float(row.strain)
    assert snap["scores_today"]["sleep_performance"] is not None


def test_refresh_scores_and_sync_state(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        _seed_synthetic_data(conn, day)

    engine = get_engine(Role.ingest)
    count = refresh_scores(engine, days_back=2)
    assert count >= 2

    with get_engine(Role.ro).connect() as conn:
        sync_row = conn.execute(
            text("SELECT * FROM sync_state WHERE source = 'worker' AND data_type = 'scores'")
        ).first()
        assert sync_row is not None
        assert sync_row.last_success_at is not None
        assert sync_row.error_count == 0


def test_daily_scores_role_grants(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_scores (local_date, recovery, strain, algo_version) "
                "VALUES (:d, 70, 10.5, 1)"
            ),
            {"d": day},
        )

    # coach_ro can SELECT
    with get_engine(Role.ro).connect() as conn:
        score = conn.execute(
            text("SELECT recovery FROM daily_scores WHERE local_date = :d"), {"d": day}
        ).scalar_one()
        assert score == 70

    # coach_ro cannot INSERT
    with get_engine(Role.ro).connect() as conn, pytest.raises(DBAPIError):
        conn.execute(
            text(
                "INSERT INTO daily_scores (local_date, recovery, algo_version) "
                "VALUES ('2020-01-01', 50, 1)"
            )
        )

    # coach_rw can SELECT but cannot INSERT/UPDATE daily_scores (worker only)
    with get_engine(Role.rw).connect() as conn:
        assert (
            conn.execute(
                text("SELECT recovery FROM daily_scores WHERE local_date = :d"), {"d": day}
            ).scalar_one()
            == 70
        )
    with get_engine(Role.rw).connect() as conn, pytest.raises(DBAPIError, match="permission"):
        conn.execute(
            text(
                "INSERT INTO daily_scores (local_date, recovery, algo_version) "
                "VALUES ('2020-01-01', 50, 1)"
            )
        )

    # ingest can INSERT and UPDATE
    with get_engine(Role.ingest).begin() as conn:
        conn.execute(
            text("UPDATE daily_scores SET recovery = 80 WHERE local_date = :d"),
            {"d": day},
        )
    with get_engine(Role.ro).connect() as conn:
        assert (
            conn.execute(
                text("SELECT recovery FROM daily_scores WHERE local_date = :d"), {"d": day}
            ).scalar_one()
            == 80
        )


def test_compute_scores_missing_data_stores_nulls(owner: Engine) -> None:
    """Missing HR/strength data and missing sleep session must store NULLs, not rest/0 values."""
    day = dt.date(2026, 5, 10)
    engine = get_engine(Role.ingest)
    compute_scores(engine, day)

    with get_engine(Role.ro).connect() as conn:
        row = conn.execute(
            text("SELECT * FROM daily_scores WHERE local_date = :d"),
            {"d": day},
        ).one()

    # Strain fields must be NULL (not 0.0 or empty containers)
    assert row.strain is None
    assert row.cardio_load is None
    assert row.muscular_load is None
    assert row.zone_minutes is None
    assert row.activities is None

    # Sleep fields must be NULL when no main sleep, but sleep_need_min stays
    assert row.sleep_need_min is not None
    assert row.sleep_actual_min is None
    assert row.sleep_debt_min is None
    assert row.sleep_performance is None
    assert row.sleep_efficiency is None
    assert row.sleep_consistency is None

    # Recovery is None since both HRV and resting HR are missing
    assert row.recovery is None
