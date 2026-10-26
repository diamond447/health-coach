"""Integration and MCP tool tests for milestone M7 analytics."""

import datetime as dt
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import Engine, text

from health_coach.jobs.derived import snapshot_tdee
from health_coach.mcp_server.common import today
from health_coach.mcp_server.server import create_server

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


async def call_error(tool: str, args: dict[str, Any]) -> str:
    async with Client(create_server()) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    return " ".join(getattr(c, "text", "") for c in result.content)


# --- M7 "Done" criterion test ---------------------------------------------------------


async def test_m7_done_criterion_tdee(owner: Engine) -> None:
    """M7 done criterion: 28-day synthetic dataset where intake is 2800 kcal/day logged

    every day and weight rises linearly 0.25 kg/week with daily weigh-ins.
    True TDEE = 2800 - 0.25*7700/7 = 2525.
    estimate_tdee must return 2525 +- 50 with confidence high.

    Note: The exponential moving average trend lags initially; to ensure the EMA is
    fully settled, we seed daily weigh-ins starting 35 days before the window start.
    """
    day = today()
    window_end = day - dt.timedelta(days=1)
    # Start weigh-ins 56 days before window_end so EMA slope is settled
    burn_in_days = 35
    total_days = 21 + burn_in_days
    first_weigh_date = window_end - dt.timedelta(days=total_days - 1)
    base_weight = 75.0
    daily_gain = 0.25 / 7.0

    with owner.begin() as conn:
        for i in range(total_days):
            d = first_weigh_date + dt.timedelta(days=i)
            wt = round(base_weight + i * daily_gain, 3)
            conn.execute(
                text(
                    "INSERT INTO body_metrics (ts, local_date, weight_kg, source) "
                    "VALUES (:ts, :d, :kg, 'scale')"
                ),
                {"ts": dt.datetime.combine(d, dt.time(7), dt.UTC), "d": d, "kg": wt},
            )
            # Intake logged for the 28 days ending yesterday
            if d >= window_end - dt.timedelta(days=27):
                conn.execute(
                    text(
                        "INSERT INTO nutrition_entries (ts, local_date, meal, description, "
                        "kcal, protein_g, carbs_g, fat_g, confidence) VALUES "
                        "(:ts, :d, 'lunch', 'chicken and rice', 2800, 160, 300, 80, 'exact')"
                    ),
                    {"ts": dt.datetime.combine(d, dt.time(12), dt.UTC), "d": d},
                )

    res = await call("estimate_tdee", {"window_days": 21})
    assert res["confidence"] == "high"
    assert res["logged_days"] == 21
    assert res["weigh_ins"] == 21
    assert res["avg_intake"] == 2800
    assert res["tdee"] is not None
    # Must be 2525 +- 50
    assert 2475 <= res["tdee"] <= 2575


# --- Nutrition summary test -----------------------------------------------------------


async def test_get_nutrition_summary(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO targets (effective_from, phase, kcal, protein_g, reason) "
                "VALUES (:d, 'bulk', 2500, 150, 'bulk targets')"
            ),
            {"d": day - dt.timedelta(days=30)},
        )
        for i in range(7):
            d = day - dt.timedelta(days=6 - i)
            conn.execute(
                text(
                    "INSERT INTO body_metrics (ts, local_date, weight_kg, source) "
                    "VALUES (:ts, :d, 80.0, 'chat')"
                ),
                {"ts": dt.datetime.combine(d, dt.time(7), dt.UTC), "d": d},
            )
            conn.execute(
                text(
                    "INSERT INTO nutrition_entries (ts, local_date, meal, description, "
                    "kcal, protein_g, carbs_g, fat_g, confidence, micros) VALUES "
                    "(:ts, :d, 'breakfast', 'oats', 600, 30, 90, 10, 'exact', NULL), "
                    "(:ts, :d, 'lunch', 'chicken', 1000, 80, 100, 20, 'exact', NULL), "
                    "(:ts, :d, 'dinner', 'salmon', 900, 50, 70, 30, 'exact', "
                    ' \'{"potassium": 0.5, "sodium": 0.4}\'::jsonb)'
                ),
                {"ts": dt.datetime.combine(d, dt.time(8), dt.UTC), "d": d},
            )

    res = await call(
        "get_nutrition_summary",
        {"start": (day - dt.timedelta(days=6)).isoformat(), "end": day.isoformat()},
    )
    assert len(res["daily"]["rows"]) == 7
    assert res["averages"]["kcal_avg"] == 2500
    assert res["averages"]["protein_avg_g"] == 160.0
    assert res["averages"]["protein_g_per_kg"] == 2.0
    assert res["completeness"]["days_logged"] == 7
    assert res["meal_distribution_pct"]["lunch"] == 40.0
    assert len(res["top_foods"]["rows"]) == 3
    assert res["micros"] is None
    assert res["micros_coverage"] is None

    # Single day query includes micros and micros_coverage
    res_single = await call(
        "get_nutrition_summary",
        {"start": day.isoformat(), "end": day.isoformat()},
    )
    assert res_single["micros"] is not None
    assert len(res_single["micros"]) == 2
    assert res_single["micros_coverage"] == {"entries_with": 1, "entries_total": 3}
    potassium = next(m for m in res_single["micros"] if m["key"] == "potassium")
    assert potassium["amount"] == 500.0  # 0.5 g -> 500 mg
    assert potassium["unit"] == "mg"
    assert potassium["reference"] == 2000.0
    assert potassium["kind"] == "target"
    assert potassium["pct"] == 25


# --- Recovery readiness tests ---------------------------------------------------------


async def test_recovery_status_unknown(owner: Engine) -> None:
    res = await call("get_recovery_status")
    assert res["readiness"] == "unknown"
    assert "no data available" in res["reasons"]


async def test_recovery_status_green_and_missing_hrv(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        # Seed 35 days of baseline so baseline view produces means and non-zero SDs
        for i in range(36):
            d = day - dt.timedelta(days=35 - i)
            # Sleep session: 450 min
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions (external_id, start_ts, end_ts, local_date, "
                    "duration_min, is_main, source) VALUES (:ext, :s, :e, :d, 450, true, 'gh')"
                ),
                {
                    "ext": f"sleep-{i}",
                    "s": dt.datetime.combine(d - dt.timedelta(days=1), dt.time(23), dt.UTC),
                    "e": dt.datetime.combine(d, dt.time(6, 30), dt.UTC),
                    "d": d,
                },
            )
            # Vitals with varying RHR (so SD > 0) but NO HRV (testing missing-HRV degradation)
            conn.execute(
                text(
                    "INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms) "
                    "VALUES (:d, :rhr, NULL)"
                ),
                {"d": d, "rhr": 61 if i == 35 else 60 + (i % 4)},
            )
            conn.execute(
                text("INSERT INTO checkins (local_date, energy, soreness) VALUES (:d, 4, 2)"),
                {"d": d},
            )

    res = await call("get_recovery_status", {"date": day.isoformat()})
    assert res["readiness"] == "green"
    assert "hrv_z" in res["missing"]
    assert res["reasons"] == []


async def test_recovery_status_amber_and_red(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        for i in range(36):
            d = day - dt.timedelta(days=35 - i)
            is_today = i == 35
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions (external_id, start_ts, end_ts, local_date, "
                    "duration_min, is_main, source) VALUES (:ext, :s, :e, :d, :dur, true, 'gh')"
                ),
                {
                    "ext": f"sleep-{i}",
                    "s": dt.datetime.combine(d - dt.timedelta(days=1), dt.time(23), dt.UTC),
                    "e": dt.datetime.combine(d, dt.time(6, 30), dt.UTC),
                    "d": d,
                    "dur": 340 if is_today else 450,  # Short sleep < 360 min on today
                },
            )
            # Base vitals: mean RHR = 61.5 (SD ~1.1), mean HRV = 50.0 (SD ~1.4)
            # On today: hrv_rmssd_ms = 35.0 (z < -1.5)
            conn.execute(
                text(
                    "INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms) "
                    "VALUES (:d, :rhr, :hrv)"
                ),
                {"d": d, "rhr": 60 + (i % 4), "hrv": 35.0 if is_today else 48.0 + (i % 5)},
            )
            conn.execute(
                text("INSERT INTO checkins (local_date, energy, soreness) VALUES (:d, :eng, :sor)"),
                {"d": d, "eng": 1 if is_today else 4, "sor": 5 if is_today else 2},
            )

    # Today has sleep < 360, hrv_z <= -1.5, soreness=5 with energy=1 -> red!
    res = await call("get_recovery_status", {"date": day.isoformat()})
    assert res["readiness"] == "red"
    assert len(res["reasons"]) >= 2

    # Context snapshot also surfaces red flag and reasons
    snap = await call("get_context_snapshot")
    assert snap["recovery_today"]["flag"] == "red"
    assert len(snap["recovery_today"]["reasons"]) >= 2


# --- Sleep analysis test --------------------------------------------------------------


async def test_get_sleep_analysis(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        for i in range(14):
            d = day - dt.timedelta(days=13 - i)
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions (external_id, start_ts, end_ts, local_date, "
                    "duration_min, efficiency, minutes_deep, minutes_light, minutes_rem, "
                    "minutes_awake, sleep_score, is_main, source) VALUES "
                    "(:ext, :s, :e, :d, :dur, 90, 80, 240, 100, 20, 85, true, 'gh')"
                ),
                {
                    "ext": f"sl-{i}",
                    "s": dt.datetime.combine(d - dt.timedelta(days=1), dt.time(23, 15), dt.UTC),
                    "e": dt.datetime.combine(d, dt.time(6, 45), dt.UTC),
                    "d": d,
                    "dur": 450 - i * 10,  # 450 down to 320
                },
            )

    res = await call(
        "get_sleep_analysis",
        {"start": (day - dt.timedelta(days=13)).isoformat(), "end": day.isoformat()},
    )
    assert len(res["nights"]["rows"]) == 14
    assert res["averages"]["duration_min"] is not None
    assert res["sleep_debt_min"] > 0
    assert len(res["worst_nights"]) == 3
    # Worst nights should be the lowest durations
    assert res["worst_nights"][0]["duration_min"] == 320


# --- Training load and Exercise progress tests ----------------------------------------


async def test_training_load_and_exercise_progress(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        # Exercise
        conn.execute(
            text(
                "INSERT INTO exercises "
                "(id, name, primary_muscles, secondary_muscles, equipment) "
                "VALUES ('101', 'Barbell Bench Press', '{chest}', '{triceps}', '{barbell}'), "
                "       ('102', 'Barbell Incline Bench Press', '{chest}', '{triceps}', '{barbell}')"
            )
        )
        # Sessions across 3 weeks
        for i in range(3):
            d = day - dt.timedelta(days=(2 - i) * 7)
            sid = i + 1
            uid = f"00000000-0000-0000-0000-00000000000{sid}"
            conn.execute(
                text(
                    "INSERT INTO strength_sessions (id, external_id, local_date, routine_name) "
                    "VALUES (:id, :uid, :d, 'Push')"
                ),
                {"id": sid, "uid": uid, "d": d},
            )
            # Sets with progression: 80kg -> 85kg -> 90kg
            wt = 80.0 + i * 5.0
            log_id = f"10000000-0000-0000-0000-00000000000{sid}"
            conn.execute(
                text(
                    "INSERT INTO strength_sets (session_id, external_id, exercise_id, set_no, "
                    "reps, weight_kg, rir, is_warmup) VALUES "
                    "(:sid, :lid, '101', 1, 8, :wt, 2, false)"
                ),
                {"sid": sid, "lid": log_id, "wt": wt},
            )
            # Other sport: BJJ
            conn.execute(
                text(
                    "INSERT INTO exercise_sessions (start_ts, end_ts, local_date, activity_type, "
                    "duration_min, hr_zone_minutes) "
                    "VALUES (:s, :e, :d, 'bjj', 60, '{\"2\": 30, \"3\": 30}')"
                ),
                {
                    "s": dt.datetime.combine(d, dt.time(18), dt.UTC),
                    "e": dt.datetime.combine(d, dt.time(19), dt.UTC),
                    "d": d,
                },
            )

    # get_training_load
    load = await call(
        "get_training_load",
        {"start": (day - dt.timedelta(days=20)).isoformat(), "end": day.isoformat()},
    )
    assert len(load["weeks"]) >= 2
    assert any(w["strength_sessions"] >= 1 for w in load["weeks"])

    # get_exercise_progress with exact name
    prog = await call("get_exercise_progress", {"exercise": "Barbell Bench Press"})
    assert prog["exercise_id"] == "101"
    assert len(prog["sessions"]["rows"]) == 3
    # Weight progressed 80 -> 85 -> 90 kg over 2 weeks: slope is positive
    assert prog["e1rm_trend_kg_per_week"] is not None
    assert prog["e1rm_trend_kg_per_week"] > 0
    assert len(prog["prs_in_range"]) >= 1

    # Ambiguous exercise resolution error
    err = await call_error("get_exercise_progress", {"exercise": "Bench"})
    assert "ambiguous" in err
    assert "Barbell Bench Press" in err

    # get_personal_records
    pr = await call("get_personal_records", {"exercise": "101"})
    assert len(pr["rows"]) == 1
    assert pr["rows"][0][2] == 90.0  # best_weight_kg


# --- Compare periods test -------------------------------------------------------------


async def test_compare_periods(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        for i in range(14):
            d = day - dt.timedelta(days=13 - i)
            steps = 8000 if i < 7 else 12000
            conn.execute(
                text("INSERT INTO daily_activity (local_date, steps) VALUES (:d, :steps)"),
                {"d": d, "steps": steps},
            )

    p_a_start = day - dt.timedelta(days=13)
    p_a_end = day - dt.timedelta(days=7)
    p_b_start = day - dt.timedelta(days=6)
    p_b_end = day

    res = await call(
        "compare_periods",
        {
            "metrics": ["steps"],
            "a_start": p_a_start.isoformat(),
            "a_end": p_a_end.isoformat(),
            "b_start": p_b_start.isoformat(),
            "b_end": p_b_end.isoformat(),
        },
    )
    assert len(res["rows"]) == 1
    # steps row: metric, mean_a, mean_b, absolute_change, percent_change, days_a, days_b
    assert res["rows"][0][0] == "steps"
    assert res["rows"][0][1] == 8000.0
    assert res["rows"][0][2] == 12000.0
    assert res["rows"][0][3] == 4000.0
    assert res["rows"][0][4] == 50.0

    # Whitelist rejection
    err = await call_error(
        "compare_periods",
        {
            "metrics": ["invalid_col"],
            "a_start": p_a_start.isoformat(),
            "a_end": p_a_end.isoformat(),
            "b_start": p_b_start.isoformat(),
            "b_end": p_b_end.isoformat(),
        },
    )
    assert "invalid" in err


# --- Derived snapshot job test --------------------------------------------------------


def test_derived_snapshot_job(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        # Add old and new audit rows to test 180-day retention purge
        old_ts = dt.datetime.now(dt.UTC) - dt.timedelta(days=200)
        conn.execute(
            text("INSERT INTO mcp_audit (ts, tool, duration_ms) VALUES (:ts, 'test_old', 10)"),
            {"ts": old_ts},
        )
        conn.execute(
            text("INSERT INTO mcp_audit (ts, tool, duration_ms) VALUES (now(), 'test_new', 10)")
        )

    # Run snapshot_tdee
    snapshot_tdee(owner, day)

    with owner.connect() as conn:
        est = conn.execute(
            text(
                "SELECT local_date, window_days, confidence FROM tdee_estimates "
                "WHERE local_date = :d"
            ),
            {"d": day},
        ).first()
        assert est is not None
        assert est.window_days == 21

        # Audit purge verified
        audit_tools = conn.execute(text("SELECT tool FROM mcp_audit")).scalars().all()
        assert "test_old" not in audit_tools
        assert "test_new" in audit_tools
