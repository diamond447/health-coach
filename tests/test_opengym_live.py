"""Live integration test against a real openGym container.

Opt-in: set HC_TEST_OPENGYM_URL (e.g. http://127.0.0.1:3399).
"""

import os
import uuid
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text

from health_coach.config import Settings
from health_coach.ingest.opengym import (
    load_token,
    pair_and_store,
    sync_opengym_workouts,
)
from health_coach.mcp_server.common import today
from health_coach.opengym.client import OpenGymClient
from health_coach.opengym.model import (
    ExerciseSpec,
    RoutineSpec,
    add_or_update_routine,
    make_uid,
    plan_routine,
    read_routines,
)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("HC_TEST_OPENGYM_URL"),
        reason="HC_TEST_OPENGYM_URL not set",
    ),
]

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_opengym_live_flow(owner: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = os.environ["HC_TEST_OPENGYM_URL"].rstrip("/")
    username = f"user_{uuid.uuid4().hex[:8]}"
    password = "Correct-Horse-Battery-Staple-99"

    # 1. Register a new user with password
    with httpx.Client(base_url=base_url) as http_client:
        reg_res = http_client.post(
            "/api/register/password",
            json={"name": username, "password": password},
        )
        assert reg_res.status_code == 200, reg_res.text

        # 2. Mint a pairing code (cookie session from registration)
        pair_res = http_client.post(
            "/api/pair/create",
            headers={"sec-fetch-site": "same-origin", "Origin": base_url},
        )
        assert pair_res.status_code == 200, pair_res.text
        code = pair_res.json()["code"]

    settings = Settings(
        opengym_url=base_url,
        token_key=SecretStr(TEST_FERNET_KEY),
    )

    # 3. Redeem pairing code and store encrypted token in Postgres
    pair_and_store(owner, settings, code)
    token = load_token(owner, settings)
    assert token is not None

    # 4. Plan a routine with per-set weights
    client = OpenGymClient(base_url, token)
    ex_spec = ExerciseSpec(
        exercise_id="bench-press",
        sets=3,
        reps=8,
        weight=85.0,
        per_set_weights=[80.0, 85.0, 90.0],
        per_set_reps=[8, 8, 8],
        rest_sec=120,
        notes="Heavy day",
        progression=False,
    )

    day = today()

    def plan_mutator(state: dict[str, Any]) -> dict[str, Any]:
        r_id = add_or_update_routine(
            state,
            RoutineSpec(
                name="Upper Power",
                exercises=[ex_spec],
                exclude_from_progression=True,
            ),
        )
        plan_routine(state, r_id, date=day.isoformat())
        return state

    client.mutate(plan_mutator)

    # 5. Read it back and verify planned routine & schedule
    data = client.get_data()
    state = data["state"]
    routines = read_routines(state)
    assert any(r.name == "Upper Power" for r in routines)
    planned_r = next(r for r in routines if r.name == "Upper Power")
    assert planned_r.exclude_from_progression is True
    assert planned_r.exercises[0].pyramid_weight == [80.0, 85.0, 90.0]
    assert state.get("dayPlan", {}).get(day.isoformat()) == planned_r.id

    # 6. Log a workout through PUT /api/data
    workout_id = make_uid()
    workout = {
        "id": workout_id,
        "d": day.isoformat(),
        "start": 1728640000000,
        "end": 1728643600000,
        "routineId": planned_r.id,
        "name": "Upper Power",
        "entries": [
            {
                "id": "bench-press",
                "sets": [
                    {"w": 80.0, "r": 8, "done": True, "rir": 2, "warm": False},
                    {"w": 85.0, "r": 8, "done": True, "rir": 1, "warm": False},
                    {"w": 90.0, "r": 8, "done": True, "rir": 0, "warm": False},
                ],
            }
        ],
    }
    bw_entry = {"d": day.isoformat(), "w": 82.5, "t": 1728640000000}

    def log_mutator(st: dict[str, Any]) -> dict[str, Any]:
        st.setdefault("workouts", []).append(workout)
        st.setdefault("bodyweight", []).append(bw_entry)
        return st

    client.mutate(log_mutator)

    # 7. Seed exercise in DB exercises table so foreign key resolves, then sync
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO exercises (id, name, category, primary_muscles, equipment) "
                "VALUES ('bench-press', 'Barbell Bench Press', 'Chest', '{chest}', '{barbell}') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )

    # 8. Sync openGym workouts and bodyweight into Postgres
    sync_opengym_workouts(owner, settings)

    # 9. Verify strength_sessions, strength_sets, and body_metrics in DB
    with owner.connect() as conn:
        session_row = conn.execute(
            text(
                "SELECT external_id, routine_name, local_date "
                "FROM strength_sessions WHERE external_id = :id"
            ),
            {"id": workout_id},
        ).first()
        assert session_row is not None
        assert session_row.routine_name == "Upper Power"
        assert session_row.local_date == day

        set_rows = conn.execute(
            text(
                "SELECT ss.set_no, ss.reps, ss.weight_kg, ss.rir, ss.is_warmup "
                "FROM strength_sets ss JOIN strength_sessions s ON s.id = ss.session_id "
                "WHERE s.external_id = :id ORDER BY ss.set_no"
            ),
            {"id": workout_id},
        ).all()
        assert len(set_rows) == 3
        assert [(r.set_no, r.reps, float(r.weight_kg), r.rir, r.is_warmup) for r in set_rows] == [
            (1, 8, 80.0, 2, False),
            (2, 8, 85.0, 1, False),
            (3, 8, 90.0, 0, False),
        ]

        bw_row = conn.execute(
            text(
                "SELECT weight_kg, source FROM body_metrics "
                "WHERE local_date = :d AND source = 'opengym'"
            ),
            {"d": day},
        ).first()
        assert bw_row is not None
        assert float(bw_row.weight_kg) == 82.5


def test_fit_live_flow(tmp_path: Any) -> None:
    import anyio
    from mcp import Client

    from health_coach.fit.server import create_fit_server
    from health_coach.fit.settings import FitSettings
    from health_coach.fit.store import FitStore
    from health_coach.fit.tools import current_subject_var

    base_url = os.environ["HC_TEST_OPENGYM_URL"].rstrip("/")
    username = f"fit_user_{uuid.uuid4().hex[:8]}"
    password = "Correct-Horse-Battery-Staple-99"

    # 1. Register a new user
    with httpx.Client(base_url=base_url) as http_client:
        reg_res = http_client.post(
            "/api/register/password",
            json={"name": username, "password": password},
        )
        assert reg_res.status_code == 200, reg_res.text

        # 2. Mint pairing code
        pair_res = http_client.post(
            "/api/pair/create",
            headers={"sec-fetch-site": "same-origin", "Origin": base_url},
        )
        assert pair_res.status_code == 200, pair_res.text
        code = pair_res.json()["code"]

    db_file = str(tmp_path / "fit_live.db")
    settings = FitSettings(
        opengym_url=base_url,
        db_path=db_file,
        token_key=SecretStr(TEST_FERNET_KEY),
        auth_disabled=True,
        dev_subject=username,
    )
    store = FitStore(settings)
    server = create_fit_server(settings, with_auth=False, store=store)

    async def _run() -> None:
        current_subject_var.set(username)
        async with Client(server) as client:
            # 3. Link
            res = await client.call_tool("link_opengym", {"code": code})
            assert not res.is_error
            assert res.structured_content["openGym_username"] == username

            # 4. Get account
            acc = await client.call_tool("get_account", {})
            assert not acc.is_error
            assert acc.structured_content["openGym_username"] == username

            # 5. Plan session
            day = today()
            plan_res = await client.call_tool(
                "plan_session",
                {
                    "date": day.isoformat(),
                    "name": "Live Fit Workout",
                    "exercises": [
                        {
                            "exercise_id": "bench-press",
                            "sets": [
                                {"reps": 8, "weight_kg": 82.5, "rir": 2},
                                {"reps": 8, "weight_kg": 85.0, "rir": 1},
                            ],
                            "rest_s": 90,
                        }
                    ],
                },
            )
            assert not plan_res.is_error
            assert plan_res.structured_content["status"] == "planned"

            # 6. Verify with get_planned
            planned = await client.call_tool("get_planned", {"days": 7})
            assert not planned.is_error
            sched = planned.structured_content["schedule"]
            today_entry = next((e for e in sched if e["date"] == day.isoformat()), None)
            assert today_entry is not None
            assert today_entry["routine_name"] == "Live Fit Workout"

            # 7. Unlink
            unl = await client.call_tool("unlink_opengym", {})
            assert not unl.is_error
            assert unl.structured_content["status"] == "unlinked"

    anyio.run(_run)
