"""Integration and MCP tool tests for training tools (search_exercises, get_workout_log)."""

import datetime as dt
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import Engine, text

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


async def test_search_exercises_empty_and_filters(owner: Engine) -> None:
    # Empty cache returns warning
    res = await call("search_exercises", {"query": "bench"})
    assert "warnings" in res
    assert "exercise cache is empty: the openGym sync has not run yet" in res["warnings"][0]

    # No filter raises error
    err = await call_error("search_exercises", {})
    assert "give at least one of" in err

    # Seed exercises
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO exercises "
                "(id, name, category, primary_muscles, secondary_muscles, equipment) VALUES "
                "('bench-press', 'Barbell Bench Press', 'Chest', '{chest}', "
                " '{triceps}', '{barbell}'), "
                "('pull-up', 'Pull Up', 'Back', '{lats}', '{biceps}', '{bodyweight}')"
            )
        )

    # Search by query
    found = await call("search_exercises", {"query": "bench"})
    assert len(found["rows"]) == 1
    assert found["rows"][0][0] == "bench-press"
    assert found["rows"][0][1] == "Barbell Bench Press"

    # Search by muscle
    found_muscle = await call("search_exercises", {"muscle": "lats"})
    assert len(found_muscle["rows"]) == 1
    assert found_muscle["rows"][0][0] == "pull-up"

    # Search by equipment
    found_eq = await call("search_exercises", {"equipment": "barbell"})
    assert len(found_eq["rows"]) == 1
    assert found_eq["rows"][0][0] == "bench-press"


async def test_get_workout_log(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO exercises (id, name, category, primary_muscles, equipment) "
                "VALUES ('squat-id', 'Barbell Back Squat', 'Legs', '{quads,glutes}', '{barbell}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO strength_sessions "
                "(id, external_id, local_date, routine_name, day_name, notes) "
                "VALUES (10, 'sesh-1', :d, 'Leg Day', 'Legs A', 'Felt great')"
            ),
            {"d": day},
        )
        conn.execute(
            text(
                "INSERT INTO strength_sets "
                "(session_id, external_id, exercise_id, set_no, reps, weight_kg, rir, is_warmup) "
                "VALUES (10, 'set-1', 'squat-id', 1, 5, 100.0, 2, false), "
                "       (10, 'set-w', 'squat-id', 0, 10, 60.0, 5, true)"
            )
        )

    log_res = await call("get_workout_log", {"start": (day - dt.timedelta(days=1)).isoformat()})
    assert len(log_res["rows"]) == 2
    # Columns: local_date, routine_name, day_name, exercise, set_no, reps,
    # weight_kg, rir, is_warmup, notes
    warmup_row = log_res["rows"][0]
    work_row = log_res["rows"][1]
    assert warmup_row[3] == "Barbell Back Squat"
    assert warmup_row[4] == 0
    assert warmup_row[8] is True  # is_warmup
    assert work_row[4] == 1
    assert work_row[5] == 5  # reps
    assert work_row[6] == 100.0  # weight_kg
    assert work_row[8] is False  # is_warmup
    assert work_row[9] == "Felt great"  # notes
