"""Tests for the healthstats web backend (Starlette API and static/SPA serving)."""

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text
from starlette.testclient import TestClient

from health_coach.config import Settings
from health_coach.db.engine import Role, get_engine
from health_coach.web.server import create_app

PRAGUE = ZoneInfo("Europe/Prague")


def _seed_test_data(conn: Any, day: dt.date) -> None:
    if conn.execute(text("SELECT 1 FROM daily_scores WHERE local_date = :d"), {"d": day}).scalar():
        return
    # 1. 30 trailing nights of vitals (D-30 to D)
    for i in range(30, -1, -1):
        d = day - dt.timedelta(days=i)
        conn.execute(
            text(
                "INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms, "
                "breathing_rate, skin_temp_delta, spo2_avg, source) VALUES "
                "(:d, :rhr, :hrv, :br, :temp, :spo2, 'google_health') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {
                "d": d,
                "rhr": 55 + (i % 3),
                "hrv": 52.0 + (i % 5),
                "br": 14.1,
                "temp": 0.2,
                "spo2": 96.0,
            },
        )
        conn.execute(
            text(
                "INSERT INTO daily_activity (local_date, steps, active_zone_minutes, "
                "calories_out, source) VALUES "
                "(:d, :steps, :act, :cal, 'google_health') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {
                "d": d,
                "steps": 8432 + i * 10,
                "act": 46,
                "cal": 2640,
            },
        )
        # Sleep session
        start_ts = dt.datetime.combine(d - dt.timedelta(days=1), dt.time(23, 18), PRAGUE)
        end_ts = dt.datetime.combine(d, dt.time(6, 52), PRAGUE)
        sess_id = conn.execute(
            text(
                "INSERT INTO sleep_sessions (external_id, local_date, start_ts, end_ts, "
                "duration_min, time_in_bed_min, efficiency, is_main, source) VALUES "
                "(:ext, :d, :st, :et, 432, 454, 95, true, 'google_health') "
                "RETURNING id"
            ),
            {
                "ext": f"sleep-{d.isoformat()}",
                "d": d,
                "st": start_ts,
                "et": end_ts,
            },
        ).scalar_one()

        # Stages for day D only
        if i == 0:
            stages = [
                ("light", start_ts, start_ts + dt.timedelta(minutes=30)),
                ("deep", start_ts + dt.timedelta(minutes=30), start_ts + dt.timedelta(minutes=90)),
                (
                    "rem",
                    start_ts + dt.timedelta(minutes=90),
                    start_ts + dt.timedelta(minutes=150),
                ),
                (
                    "awake",
                    start_ts + dt.timedelta(minutes=150),
                    start_ts + dt.timedelta(minutes=160),
                ),
                ("light", start_ts + dt.timedelta(minutes=160), end_ts),
            ]
            for stg, s_t, e_t in stages:
                conn.execute(
                    text(
                        "INSERT INTO sleep_stages (session_id, stage, start_ts, end_ts) "
                        "VALUES (:sid, :stg, :st, :et)"
                    ),
                    {"sid": sess_id, "stg": stg, "st": s_t, "et": e_t},
                )

        # Daily scores
        inputs_data = {
            "rest_hr": 52.0,
            "hr_max": 190.0,
            "baselines": {
                "hrv": [3.95, 0.12],  # center, scale (exp(3.95) ~ 52)
                "rhr": [54.0, 2.5],
                "breathing_rate": [14.0, 0.5],
                "skin_temp": [0.0, 0.2],
            },
        }
        conn.execute(
            text(
                "INSERT INTO daily_scores (local_date, recovery, recovery_z, "
                "recovery_components, flags, strain, cardio_load, muscular_load, "
                "zone_minutes, activities, strain_target_low, strain_target_high, "
                "sleep_need_min, sleep_actual_min, sleep_debt_min, sleep_performance, "
                "sleep_efficiency, sleep_consistency, planned_bedtime, planned_wake, "
                "inputs, algo_version, source) VALUES "
                "(:d, :rec, 0.8, :comp, :flags, :strain, 74.0, 18.0, :zones, :acts, "
                "12.0, 15.0, 491, 432, 14, 88, 95, 81, :bed, :wake, :inp, 1, 'worker') "
                "ON CONFLICT (local_date) DO NOTHING"
            ),
            {
                "d": d,
                "rec": 74 if i == 0 else 60 + (i % 20),
                "comp": json.dumps(
                    [
                        {"signal": "hrv", "value": 62.0, "z": 1.1, "weight": 0.5, "points": 9},
                        {
                            "signal": "resting_hr",
                            "value": 52.0,
                            "z": 0.9,
                            "weight": 0.2,
                            "points": 4,
                        },
                    ]
                ),
                "flags": ["illness"] if i == 5 else [],
                "strain": 11.8 if i == 0 else 10.5,
                "zones": json.dumps({"Z1": 48, "Z2": 26, "Z3": 18, "Z4": 9, "Z5": 2}),
                "acts": json.dumps(
                    [
                        {
                            "kind": "strength",
                            "name": "Push",
                            "start": dt.datetime.combine(d, dt.time(7, 10), PRAGUE).isoformat(),
                            "end": dt.datetime.combine(d, dt.time(8, 12), PRAGUE).isoformat(),
                            "avg_hr": 118,
                            "max_hr": 152,
                            "load": 40.0,
                            "strain": 6.1,
                        }
                    ]
                ),
                "bed": dt.datetime.combine(d, dt.time(22, 0), PRAGUE),
                "wake": dt.datetime.combine(d + dt.timedelta(days=1), dt.time(6, 30), PRAGUE),
                "inp": json.dumps(inputs_data),
            },
        )

    # 2. Nutrition and targets
    conn.execute(
        text(
            "INSERT INTO targets (effective_from, phase, kcal, protein_g, carbs_g, fat_g, "
            "weekly_rate_min_kg, weekly_rate_max_kg, reason, source) VALUES "
            "(:ef, 'cut', 2400, 160, 260, 75, -0.5, -0.3, 'Start cut', 'coach')"
        ),
        {"ef": day - dt.timedelta(days=60)},
    )
    for i in range(14, -1, -1):
        d = day - dt.timedelta(days=i)
        conn.execute(
            text(
                "INSERT INTO nutrition_entries (local_date, meal, description, grams, "
                "kcal, protein_g, carbs_g, fat_g, fiber_g, ts, confidence, source) VALUES "
                "(:d, 'breakfast', 'Ovesná kaše', 100, 520, 24.0, 70.0, 12.0, "
                " 8.0, :ts, 'exact', 'manual'), "
                "(:d, 'lunch', 'Kuřecí rizoto', 350, 760, 42.0, 85.0, 18.0, "
                " 5.0, :ts, 'exact', 'manual') "
                "ON CONFLICT DO NOTHING"
            ),
            {"d": d, "ts": dt.datetime.combine(d, dt.time(8, 0), PRAGUE)},
        )

    # 3. Heart rate samples for intraday chart
    day_start = dt.datetime.combine(day, dt.time(0, 0), PRAGUE)
    for m in range(0, 24 * 60, 15):
        s_ts = day_start + dt.timedelta(minutes=m)
        conn.execute(
            text("INSERT INTO heart_rate_samples (ts, bpm) VALUES (:ts, :bpm)"),
            {"ts": s_ts, "bpm": 60 + (m % 40)},
        )

    # 4. Body metrics for weight trend
    for i in range(30, -1, -1):
        d = day - dt.timedelta(days=i)
        conn.execute(
            text(
                "INSERT INTO body_metrics (local_date, ts, weight_kg, source) VALUES "
                "(:d, :ts, :w, 'scale') ON CONFLICT DO NOTHING"
            ),
            {"d": d, "ts": dt.datetime.combine(d, dt.time(7, 0), PRAGUE), "w": 82.0 - i * 0.04},
        )

    # 5. Exercises & Strength sessions
    conn.execute(
        text(
            "INSERT INTO exercises (id, name, primary_muscles, secondary_muscles, source) VALUES "
            "('bench_press', 'Bench Press', '{chest}', '{triceps,shoulders}', 'catalogue'), "
            "('squat', 'Squat', '{quads}', '{glutes}', 'catalogue') "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    st_id = conn.execute(
        text(
            "INSERT INTO strength_sessions "
            "(external_id, routine_name, local_date, start_ts, end_ts, source) VALUES "
            "('ext-push-1', 'Push', :d, :st, :et, 'opengym') RETURNING id"
        ),
        {
            "d": day,
            "st": dt.datetime.combine(day, dt.time(7, 10), PRAGUE),
            "et": dt.datetime.combine(day, dt.time(8, 12), PRAGUE),
        },
    ).scalar_one()

    conn.execute(
        text(
            "INSERT INTO strength_sets ("
            "  session_id, external_id, exercise_id, set_no, weight_kg, reps, rir, is_warmup"
            ") VALUES "
            "(:sid, 'set-1', 'bench_press', 1, 80.0, 10, 2, false), "
            "(:sid, 'set-2', 'bench_press', 2, 85.0, 8, 1, false)"
        ),
        {"sid": st_id},
    )

    conn.execute(
        text(
            "INSERT INTO exercise_sessions (external_id, local_date, start_ts, end_ts, "
            "activity_type, duration_min, avg_hr, max_hr, calories, distance_km, source) "
            "VALUES ('run-1', :d, :st, :et, 'run', 32, 148, 171, 380, 5.2, 'google_health')"
        ),
        {
            "d": day,
            "st": dt.datetime.combine(day, dt.time(17, 30), PRAGUE),
            "et": dt.datetime.combine(day, dt.time(18, 2), PRAGUE),
        },
    )

    # 6. Journal entries: alcohol and late meals on alternate days (enough for
    # insights), sauna only yesterday
    conn.execute(
        text(
            "INSERT INTO journal_entries (local_date, behavior, amount, note, source) VALUES "
            "(:yd, 'sauna', 1, 'sauna večer', 'chat') "
            "ON CONFLICT DO NOTHING"
        ),
        {"yd": day - dt.timedelta(days=1)},
    )
    for i in range(1, 13):
        conn.execute(
            text(
                "INSERT INTO journal_entries (local_date, behavior, amount, note, source) "
                "VALUES (:d, :b, NULL, NULL, 'chat') ON CONFLICT DO NOTHING"
            ),
            {"d": day - dt.timedelta(days=i), "b": "alcohol" if i % 2 else "late_meal"},
        )

    # 7. Coach log
    conn.execute(
        text(
            "INSERT INTO coach_log (ts, kind, title, body, source) VALUES "
            "(:ts, 'review', 'Týdenní review', 'Super týden, tréninky splněny.', 'coach')"
        ),
        {"ts": dt.datetime.combine(day, dt.time(8, 0), PRAGUE)},
    )


def test_web_endpoints(migrated_db: str, owner: Engine) -> None:
    """Verify all API endpoints with synthetic data in migrated_db."""
    today_d = dt.date(2026, 10, 25)
    with get_engine(Role.owner).connect() as conn:
        _seed_test_data(conn, today_d)
        conn.commit()

    settings = Settings(
        database_url=migrated_db,
        ro_database_url=migrated_db,
        timezone="Europe/Prague",
        web_allowed_users=[],  # No auth check in dev mode
    )
    app = create_app(settings)
    client = TestClient(app)

    # 1. /healthz
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 2. /api/day
    res = client.get(f"/api/day?date={today_d.isoformat()}")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    data = res.json()
    assert data["date"] == "2026-10-25"
    assert data["scores"]["recovery"] == 74
    assert data["scores"]["recovery_zone"] == "green"
    assert data["scores"]["strain"] == 11.8
    assert data["vitals"]["resting_hr"] is not None
    assert data["activity"]["steps"] is not None
    assert "as_of" in data

    # 3. /api/recovery
    res = client.get(f"/api/recovery?date={today_d.isoformat()}&days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["recovery"] == 74
    assert data["zone"] == "green"
    assert len(data["hrv_series"]) == 30
    assert len(data["rhr_series"]) == 30
    assert data["hrv_band"] is not None

    # 4. /api/sleep
    res = client.get(f"/api/sleep?date={today_d.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert data["session"]["efficiency"] == 95
    assert len(data["stages"]) > 0
    assert len(data["week"]) == 7
    assert data["need_breakdown"]["base_need_min"] is not None
    assert "tonight_plan" in data

    # 5. /api/strain
    res = client.get(f"/api/strain?date={today_d.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert data["strain"] == 11.8
    assert len(data["zones"]) == 5
    assert len(data["hr_points"]) > 0
    assert len(data["week_strains"]) == 7

    # 6. /api/nutrition
    res = client.get(f"/api/nutrition?date={today_d.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert data["target_kcal"] == 2400
    assert len(data["macros"]) == 4
    assert len(data["meals"]) > 0
    assert "energy_balance" in data

    # 7. /api/trends
    res = client.get(f"/api/trends?date={today_d.isoformat()}&days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 30
    assert "recovery" in data
    assert "hrv" in data
    assert "rhr" in data
    assert "sleep" in data
    assert "strain" in data
    assert "weight" in data
    assert "kcal" in data

    # 8. /api/calendar
    res = client.get("/api/calendar?month=2026-10")
    assert res.status_code == 200
    data = res.json()
    assert data["month"] == "2026-10"
    assert len(data["cells"]) >= 31
    assert data["stats"]["avg_recovery"] is not None

    # 9. /api/journal
    res = client.get(f"/api/journal?date={today_d.isoformat()}&days=60")
    assert res.status_code == 200
    data = res.json()
    assert "yesterday" in data
    assert len(data["yesterday"]) > 0

    # 10. /api/report
    res = client.get(f"/api/report?period=week&end={today_d.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert "tiles" in data
    assert "daily_recovery" in data
    assert data["coach_review"] is not None


def test_web_auth_and_public_routes(migrated_db: str, owner: Engine) -> None:
    """Test header check: 403 on disallowed, 200 on allowed, public path bypass, SPA fallback."""
    settings = Settings(
        database_url=migrated_db,
        ro_database_url=migrated_db,
        web_allowed_users=["valid_user"],
        web_user_header="X-authentik-username",
    )
    app = create_app(settings)
    client = TestClient(app)

    # 1. API route without header -> 403 JSON
    res = client.get("/api/day")
    assert res.status_code == 403
    assert res.json()["error"] == "forbidden"
    assert res.headers["cache-control"] == "no-store"

    # 2. API route with wrong user -> 403 JSON
    res = client.get("/api/day", headers={"X-authentik-username": "intruder"})
    assert res.status_code == 403
    assert res.json()["error"] == "forbidden"

    # 3. API route with allowed user -> 200
    res = client.get("/api/day", headers={"X-authentik-username": "valid_user"})
    assert res.status_code == 200

    # 4. Public path /healthz bypasses auth without header
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 5. SPA fallback route without header returns 200 HTML
    res = client.get("/recovery")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert res.headers["cache-control"] == "no-cache"

    res = client.get("/spanek")
    assert res.status_code == 200

    # 6. Path traversal attempt falls back to SPA index.html and cannot escape STATIC_DIR
    res = client.get("/../../../etc/passwd")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_web_input_validation(migrated_db: str, owner: Engine) -> None:
    """Test 400 JSON errors for malformed date, month, period, and days clamping/validation."""
    today_d = dt.date(2026, 10, 25)
    with get_engine(Role.owner).connect() as conn:
        _seed_test_data(conn, today_d)
        conn.commit()

    settings = Settings(
        database_url=migrated_db,
        ro_database_url=migrated_db,
        timezone="Europe/Prague",
        web_allowed_users=[],
    )
    app = create_app(settings)
    client = TestClient(app)

    # 1. Malformed date -> 400 {"error": "bad_request", ...}
    for endpoint in [
        "/api/day?date=invalid",
        "/api/day?date=2026-02-31",
        "/api/recovery?date=not-a-date",
        "/api/sleep?date=bad",
        "/api/strain?date=2026-99-99",
        "/api/nutrition?date=bad-date",
        "/api/trends?date=bad",
        "/api/journal?date=bad",
        "/api/report?end=bad",
    ]:
        res = client.get(endpoint)
        assert res.status_code == 400, f"Expected 400 for {endpoint}, got {res.status_code}"
        assert res.json()["error"] == "bad_request"
        assert "detail" in res.json()

    # 2. Malformed month -> 400 {"error": "bad_request", ...}
    for bad_month in ["bad", "2026-13", "2026", "2026-00", "2026-1-1"]:
        res = client.get(f"/api/calendar?month={bad_month}")
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    # 3. Malformed period -> 400 {"error": "bad_request", ...}
    for bad_period in ["year", "day", "all", "123"]:
        res = client.get(f"/api/report?period={bad_period}")
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    # 4. Trends days validation: only 7, 30, 90 allowed, else 400
    for bad_days in ["14", "60", "1", "365", "abc", "-7"]:
        res = client.get(f"/api/trends?days={bad_days}")
        assert res.status_code == 400
        assert res.json()["error"] == "bad_request"

    for valid_days in [7, 30, 90]:
        res = client.get(f"/api/trends?days={valid_days}")
        assert res.status_code == 200
        assert res.json()["days"] == valid_days

    # 5. Clamping days to 7..365 on recovery and journal
    res = client.get("/api/recovery?days=1")
    assert res.status_code == 200
    assert len(res.json()["hrv_series"]) == 7  # clamped to 7

    res = client.get("/api/recovery?days=bad")
    assert res.status_code == 400
    assert res.json()["error"] == "bad_request"

    res = client.get("/api/journal?days=1")
    assert res.status_code == 200

    res = client.get("/api/journal?days=bad")
    assert res.status_code == 400
    assert res.json()["error"] == "bad_request"


def _seed_healthspan(engine: Engine) -> None:
    week1 = dt.date(2026, 10, 19)
    factors_data = [
        {
            "key": "sleep_regularity",
            "name": "Pravidelnost spánku",
            "value": 78.0,
            "unit": "%",
            "goal": "≥ 85 %",
            "hr": 0.95,
            "years": -0.3,
            "has_data": True,
        },
        {
            "key": "sleep_duration",
            "name": "Délka spánku",
            "value": 7.1,
            "unit": "h",
            "goal": "7\u20139 h",
            "hr": 1.0,
            "years": 0.0,
            "has_data": True,
        },
        {
            "key": "moderate_activity",
            "name": "Minuty v zónách 1\u20133",
            "value": 210.0,
            "unit": "min/týden",
            "goal": "≥ 150 min",
            "hr": 0.85,
            "years": -1.9,
            "has_data": True,
        },
        {
            "key": "vigorous_activity",
            "name": "Minuty v zónách 4\u20135",
            "value": 22.0,
            "unit": "min/týden",
            "goal": "≥ 75 min",
            "hr": 1.0,
            "years": 0.0,
            "has_data": True,
        },
        {
            "key": "strength_training",
            "name": "Posilování",
            "value": 3.2,
            "unit": "h/týden",
            "goal": "1\u20132,5 h",
            "hr": 0.92,
            "years": -0.9,
            "has_data": True,
        },
        {
            "key": "steps",
            "name": "Kroky",
            "value": 8900.0,
            "unit": "/den",
            "goal": "≥ 8 000/den",
            "hr": 0.85,
            "years": -1.9,
            "has_data": True,
        },
        {
            "key": "resting_hr",
            "name": "Klidový tep",
            "value": 54.0,
            "unit": "bpm",
            "goal": "≤ 60 bpm",
            "hr": 0.95,
            "years": -0.6,
            "has_data": True,
        },
        {
            "key": "vo2max",
            "name": "VO2max",
            "value": None,
            "unit": "ml/kg/min",
            "goal": "\u2014",
            "hr": None,
            "years": None,
            "has_data": False,
        },
        {
            "key": "body_composition",
            "name": "Podíl svalové hmoty",
            "value": 16.5,
            "unit": "%",
            "goal": "podle věku",
            "hr": 1.0,
            "years": 0.0,
            "has_data": True,
        },
    ]
    with engine.begin() as conn:
        for i in range(4):
            w = week1 - dt.timedelta(weeks=3 - i)
            conn.execute(
                text(
                    "INSERT INTO healthspan_weekly (week_start, delta_years, pace, factors, "
                    "factors_with_data, age, algo_version, source) VALUES "
                    "(:w, -2.6, 0.80, CAST(:f AS jsonb), 8, 42, 1, 'worker') "
                    "ON CONFLICT (week_start) DO UPDATE SET delta_years = EXCLUDED.delta_years"
                ),
                {"w": w, "f": json.dumps(factors_data)},
            )


def test_api_healthspan(migrated_db: str, owner: Engine) -> None:
    engine = get_engine(Role.owner)
    app = create_app(Settings())
    client = TestClient(app)

    # 1. Empty state
    res = client.get("/api/healthspan")
    assert res.status_code == 200
    data = res.json()
    assert data["has_enough_data"] is False
    assert data["latest"] is None
    assert data["history"] == []

    # 2. Seed healthspan_weekly rows
    _seed_healthspan(engine)

    # 3. Successful fetch with data
    res = client.get("/api/healthspan")
    assert res.status_code == 200
    data = res.json()
    assert data["has_enough_data"] is True
    assert data["latest"] is not None
    assert data["latest"]["delta_years"] == -2.6
    assert data["latest"]["pace"] == 0.80
    assert data["latest"]["age"] == 42
    assert data["latest"]["biological_age"] == 39.4
    assert data["latest"]["factors_with_data"] == 8
    assert len(data["latest"]["factors"]) == 9
    assert len(data["history"]) == 4

    # 4. Bad request validation
    res = client.get("/api/healthspan?weeks=bad")
    assert res.status_code == 400
    assert res.json()["error"] == "bad_request"


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "web" / "src" / "fixtures" / "api"
FIXTURE_ENDPOINTS = {
    "day": "/api/day?date=2026-10-25",
    "recovery": "/api/recovery?date=2026-10-25&days=30",
    "sleep": "/api/sleep?date=2026-10-25",
    "strain": "/api/strain?date=2026-10-25",
    "nutrition": "/api/nutrition?date=2026-10-25",
    "trends": "/api/trends?date=2026-10-25&days=30",
    "calendar": "/api/calendar?month=2026-10",
    "journal": "/api/journal?date=2026-10-25&days=60",
    "report": "/api/report?period=week&end=2026-10-25",
    "healthspan": "/api/healthspan",
}


def _shape(value: Any) -> Any:
    """Reduce a JSON value to its structure: keys and value types, not the values."""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        shapes = {json.dumps(_shape(v), sort_keys=True) for v in value}
        return [json.loads(s) for s in sorted(shapes)]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "null"


def test_api_fixtures_match_responses(migrated_db: str, owner: Engine) -> None:
    """The frontend type-checks web/src/fixtures/api/*.json against its response types
    (web/src/fixtures.ts), so the fixtures must have the shape the API really returns.
    Regenerate them with HC_UPDATE_WEB_FIXTURES=1."""
    with owner.begin() as conn:
        _seed_test_data(conn, dt.date(2026, 10, 25))
    _seed_healthspan(owner)
    client = TestClient(create_app(Settings(web_allowed_users=[])))

    update = os.environ.get("HC_UPDATE_WEB_FIXTURES") == "1"
    stale = []
    for name, url in FIXTURE_ENDPOINTS.items():
        res = client.get(url)
        assert res.status_code == 200, url
        path = FIXTURES_DIR / f"{name}.json"
        if update:
            # as_of is the time of the test run; pin it so regenerating gives a clean diff.
            sample = {**res.json(), "as_of": "2026-10-25T12:00+01:00"}
            FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n")
        elif not path.exists() or _shape(json.loads(path.read_text())) != _shape(res.json()):
            stale.append(name)
    assert not stale, f"stale fixtures {stale}: run HC_UPDATE_WEB_FIXTURES=1 uv run pytest"
