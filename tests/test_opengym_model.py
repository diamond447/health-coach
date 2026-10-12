"""Unit tests for openGym state models, normalizers, readers, and builders."""

import datetime as dt
from decimal import Decimal
from typing import Any

from health_coach.opengym.model import (
    ExerciseSpec,
    RoutineSpec,
    add_or_update_routine,
    make_uid,
    normalize_workouts,
    plan_routine,
    read_routines,
)


def test_make_uid() -> None:
    uid1 = make_uid()
    uid2 = make_uid()
    assert isinstance(uid1, str)
    assert len(uid1) >= 10
    assert uid1 != uid2


def test_normalize_workouts_kg_and_lb() -> None:
    state_kg = {
        "unit": "kg",
        "workouts": [
            {
                "id": "w1",
                "d": "2026-03-10",
                "start": 1773136800000,
                "end": 1773140400000,
                "routineId": "r1",
                "name": "Upper A",
                "entries": [
                    {
                        "id": "bench-press",
                        "sets": [
                            {"w": 80, "r": 8, "done": True, "rir": 2, "phase": "work"},
                            {"w": 40, "r": 10, "done": True, "phase": "warmup"},
                            {
                                "w": 85,
                                "r": 6,
                                "done": True,
                                "failure": True,
                            },  # unrated failure -> RIR 0
                        ],
                    }
                ],
            }
        ],
    }

    sessions = normalize_workouts(state_kg)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.external_id == "w1"
    assert s.local_date == dt.date(2026, 3, 10)
    assert s.routine_id == "r1"
    assert s.routine_name == "Upper A"
    assert len(s.sets) == 3

    assert s.sets[0].weight_kg == Decimal("80.00")
    assert s.sets[0].reps == Decimal("8.0")
    assert s.sets[0].rir == Decimal("2.0")
    assert s.sets[0].is_warmup is False
    assert s.sets[0].done is True
    assert s.sets[0].set_no == 1

    assert s.sets[1].is_warmup is True
    assert s.sets[1].set_no == 2

    # Failure set without explicit RIR resolves to 0.0
    assert s.sets[2].rir == Decimal("0.0")
    assert s.sets[2].set_no == 3

    # Pound conversion
    state_lb = {
        "unit": "lb",
        "workouts": [
            {
                "id": "w2",
                "d": "2026-03-11",
                "entries": [
                    {
                        "id": "squat",
                        "sets": [{"w": 225, "r": 5, "done": True}],
                    }
                ],
            }
        ],
    }
    sessions_lb = normalize_workouts(state_lb)
    # 225 lb * 0.45359237 = 102.058... -> 102.06 kg
    assert sessions_lb[0].sets[0].weight_kg == Decimal("102.06")


def test_normalize_workouts_unilateral_set() -> None:
    state = {
        "unit": "kg",
        "workouts": [
            {
                "id": "w_uni",
                "d": "2026-03-12",
                "entries": [
                    {
                        "id": "db-lunge",
                        "sets": [
                            {
                                "id": "set-u1",
                                "sides": {
                                    "L": {"w": 20, "r": 8, "done": True, "rir": 1},
                                    "R": {"w": 22, "r": 8, "done": True, "rir": 2},
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    sessions = normalize_workouts(state)
    assert len(sessions) == 1
    s = sessions[0].sets[0]
    assert s.weight_kg == Decimal("22.00")  # max(20, 22)
    assert s.reps == Decimal("16.0")  # 8 + 8
    assert s.done is True
    assert s.rir == Decimal("1.0")  # min(1, 2)


def test_compact_routines_and_builders() -> None:
    state: dict[str, Any] = {"routines": [], "unit": "kg"}

    spec = RoutineSpec(
        name="Push Day",
        exclude_from_progression=True,
        exercises=[
            ExerciseSpec(
                exercise_id="bench-press",
                sets=3,
                reps=8,
                weight=80.0,
                rest_sec=180,
                progression=False,
            ),
            ExerciseSpec(
                exercise_id="incline-dumbbell-press",
                sets=3,
                per_set_weights=[26.0, 28.0, 30.0],
                per_set_reps=[10, 8, 6],
                rest_sec=120,
            ),
        ],
    )

    r_id = add_or_update_routine(state, spec)
    routines = state["routines"]
    assert isinstance(routines, list)
    assert r_id in [r["id"] for r in routines]

    # Verify state representation
    r_dict = routines[0]
    assert isinstance(r_dict, dict)
    assert r_dict["excludeFromProgression"] is True
    assert r_dict["ex"][0]["weight"] == 80.0
    assert r_dict["ex"][0]["prog"] == "off"
    assert r_dict["ex"][0]["restSec"] == 180

    # Per set weights represented as pyramid / pyramidWeight
    assert r_dict["ex"][1]["pyramidWeight"] == [26.0, 28.0, 30.0]
    assert r_dict["ex"][1]["pyramid"] == [10, 8, 6]

    # Verify compact read
    compact = read_routines(state)
    assert len(compact) == 1
    assert compact[0].name == "Push Day"
    assert compact[0].exercise_count == 2
    assert compact[0].exclude_from_progression is True
    assert compact[0].exercises[0].weight == 80.0
    assert compact[0].exercises[1].pyramid_weight == [26.0, 28.0, 30.0]

    # Plan routine on date and weekday
    plan_routine(state, r_id, date="2026-03-15", weekday=1)
    day_plan = state["dayPlan"]
    assert isinstance(day_plan, dict)
    assert day_plan["2026-03-15"] == r_id
    week = state["week"]
    assert isinstance(week, dict)
    assert week["1"] == r_id
