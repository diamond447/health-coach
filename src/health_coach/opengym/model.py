"""Pure model functions over openGym state dictionary.

Handles UID generation, workout normalization (kg conversion, effort, warmups, unilateral sets),
compact routine reading, and routine planning builders.
"""

import datetime as dt
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
LB_TO_KG = Decimal("0.45359237")


def _to_base36(num: int) -> str:
    if num == 0:
        return "0"
    digits: list[str] = []
    while num > 0:
        digits.append(_BASE36[num % 36])
        num //= 36
    return "".join(reversed(digits))


def make_uid(now_ms: int | None = None) -> str:
    """Generate an openGym ID matching the frontend `uid()` format.

    Frontend: Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    prefix = _to_base36(now_ms)
    suffix = "".join(secrets.choice(_BASE36) for _ in range(5))
    return f"{prefix}{suffix}"


def _decimal(val: Any) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _to_kg(weight: Any, unit: str) -> Decimal | None:
    w = _decimal(weight)
    if w is None:
        return None
    if unit.lower() == "lb":
        return (w * LB_TO_KG).quantize(Decimal("0.01"))
    return w.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class NormalizedSet:
    external_id: str
    exercise_id: str
    set_no: int
    reps: Decimal | None
    weight_kg: Decimal | None
    rir: Decimal | None
    rpe: Decimal | None
    is_warmup: bool
    done: bool
    set_type: str = "straight"
    notes: str | None = None


@dataclass(frozen=True)
class NormalizedSession:
    external_id: str
    local_date: dt.date
    start_ts: dt.datetime | None
    end_ts: dt.datetime | None
    routine_id: str | None
    routine_name: str | None
    notes: str | None
    sets: list[NormalizedSet] = field(default_factory=list)


def normalize_workouts(
    state: dict[str, Any],
    tz: ZoneInfo | None = None,
) -> list[NormalizedSession]:
    """Parse state['workouts'] into normalized sessions and sets."""
    unit = str(state.get("unit") or "kg")
    workouts = state.get("workouts") or []
    if not isinstance(workouts, list):
        return []

    sessions: list[NormalizedSession] = []

    for w in workouts:
        if not isinstance(w, dict):
            continue
        w_id = str(w.get("id") or make_uid())
        d_str = w.get("d")

        start_ts: dt.datetime | None = None
        if w.get("start"):
            start_ts = dt.datetime.fromtimestamp(w["start"] / 1000.0, tz=dt.UTC)

        end_ts: dt.datetime | None = None
        if w.get("end"):
            end_ts = dt.datetime.fromtimestamp(w["end"] / 1000.0, tz=dt.UTC)

        if d_str:
            local_date = dt.date.fromisoformat(str(d_str))
        elif start_ts and tz:
            local_date = start_ts.astimezone(tz).date()
        elif start_ts:
            local_date = start_ts.date()
        else:
            local_date = dt.datetime.now(tz=tz or dt.UTC).date()

        session_notes = w.get("notes") or w.get("note")
        if session_notes is not None:
            session_notes = str(session_notes).strip() or None

        entries = w.get("entries") or []
        set_counts: dict[str, int] = defaultdict(int)
        normalized_sets: list[NormalizedSet] = []

        for e_idx, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            ex_id = str(e.get("id") or "")
            raw_sets = e.get("sets") or []

            for s_idx, s in enumerate(raw_sets):
                if not isinstance(s, dict):
                    continue

                set_counts[ex_id] += 1
                set_no = set_counts[ex_id]

                set_id = str(s.get("id") or f"{w_id}:{e_idx}:{s_idx}")

                # Unilateral handling
                sides = s.get("sides")
                w_val: Any
                r_val: Any
                if isinstance(sides, dict) and "L" in sides and "R" in sides:
                    side_l = sides["L"] if isinstance(sides["L"], dict) else {}
                    side_r = sides["R"] if isinstance(sides["R"], dict) else {}
                    w_val = max(
                        float(side_l.get("w") or 0.0),
                        float(side_r.get("w") or 0.0),
                    )
                    r_val = float(side_l.get("r") or 0.0) + float(side_r.get("r") or 0.0)
                    done = bool(side_l.get("done") and side_r.get("done"))
                    rirs = [
                        float(x) for x in (side_l.get("rir"), side_r.get("rir")) if x is not None
                    ]
                    rir_val: float | None = min(rirs) if rirs else None
                    rpes = [
                        float(x) for x in (side_l.get("rpe"), side_r.get("rpe")) if x is not None
                    ]
                    rpe_val: float | None = max(rpes) if rpes else None
                else:
                    w_val = s.get("w")
                    r_val = s.get("r")
                    done = bool(s.get("done"))
                    rir_val = float(s["rir"]) if s.get("rir") is not None else None
                    rpe_val = float(s["rpe"]) if s.get("rpe") is not None else None

                phase = str(s.get("phase") or "").strip().lower()
                is_warmup = s.get("warmup") is True or phase in ("warmup", "warm-up", "warm_up")

                # Failure / AMRAP flag (RIR 0 when taken to failure and unrated)
                if s.get("failure") is True and not is_warmup and rir_val is None:
                    rir_val = 0.0

                weight_kg = _to_kg(w_val, unit)
                reps_dec = _decimal(r_val)
                if reps_dec is not None:
                    reps_dec = reps_dec.quantize(Decimal("0.1"))

                rir_dec = (
                    Decimal(str(rir_val)).quantize(Decimal("0.1")) if rir_val is not None else None
                )
                rpe_dec = (
                    Decimal(str(rpe_val)).quantize(Decimal("0.1")) if rpe_val is not None else None
                )

                stype = s.get("type")
                set_type = stype if stype in ("dropset", "restpause") else "straight"

                normalized_sets.append(
                    NormalizedSet(
                        external_id=set_id,
                        exercise_id=ex_id,
                        set_no=set_no,
                        reps=reps_dec,
                        weight_kg=weight_kg,
                        rir=rir_dec,
                        rpe=rpe_dec,
                        is_warmup=is_warmup,
                        done=done,
                        set_type=set_type,
                        notes=str(s["note"]).strip() if s.get("note") else None,
                    )
                )

        sessions.append(
            NormalizedSession(
                external_id=w_id,
                local_date=local_date,
                start_ts=start_ts,
                end_ts=end_ts,
                routine_id=str(w["routineId"]) if w.get("routineId") else None,
                routine_name=str(w["name"]) if w.get("name") else None,
                notes=session_notes,
                sets=normalized_sets,
            )
        )

    return sessions


@dataclass(frozen=True)
class CompactExercise:
    id: str
    sets: int
    reps: int | None
    reps_min: int | None
    reps_max: int | None
    weight: float | None
    mode: str
    rest_sec: int | None
    superset_group: str | None
    pyramid: list[int | str] | None
    pyramid_weight: list[float] | None
    progression: bool
    notes: str | None

    @property
    def note(self) -> str | None:
        return self.notes


@dataclass(frozen=True)
class CompactRoutine:
    id: str
    name: str
    exercise_count: int
    exclude_from_progression: bool
    exercises: list[CompactExercise]


def read_routines(state: dict[str, Any]) -> list[CompactRoutine]:
    """Read routines in compact summary form."""
    raw_routines = state.get("routines") or []
    if not isinstance(raw_routines, list):
        return []

    result: list[CompactRoutine] = []
    for r in raw_routines:
        if not isinstance(r, dict):
            continue
        r_id = str(r.get("id") or "")
        r_name = str(r.get("name") or "")
        ex_list = r.get("ex") or []
        exclude = r.get("excludeFromProgression") is True

        exercises: list[CompactExercise] = []
        for cfg in ex_list:
            if not isinstance(cfg, dict):
                continue
            mode = str(cfg.get("mode") or "reps")
            prog_off = cfg.get("prog") == "off" or exclude
            pyr = cfg.get("pyramid") if isinstance(cfg.get("pyramid"), list) else None
            pyr_w = (
                [float(x) for x in cfg["pyramidWeight"]]
                if isinstance(cfg.get("pyramidWeight"), list)
                else None
            )
            note_val = cfg.get("note") or cfg.get("notes")

            exercises.append(
                CompactExercise(
                    id=str(cfg.get("id") or ""),
                    sets=int(cfg.get("sets") or 1),
                    reps=int(cfg["reps"]) if cfg.get("reps") is not None else None,
                    reps_min=int(cfg["repsMin"]) if cfg.get("repsMin") is not None else None,
                    reps_max=int(cfg["repsMax"]) if cfg.get("repsMax") is not None else None,
                    weight=float(cfg["weight"]) if cfg.get("weight") is not None else None,
                    mode=mode,
                    rest_sec=int(cfg["restSec"]) if cfg.get("restSec") is not None else None,
                    superset_group=str(cfg["sg"]) if cfg.get("sg") else None,
                    pyramid=pyr,
                    pyramid_weight=pyr_w,
                    progression=not prog_off,
                    notes=str(note_val).strip() if note_val else None,
                )
            )

        result.append(
            CompactRoutine(
                id=r_id,
                name=r_name,
                exercise_count=len(exercises),
                exclude_from_progression=exclude,
                exercises=exercises,
            )
        )
    return result


@dataclass
class ExerciseSpec:
    exercise_id: str
    sets: int = 3
    reps: int | None = None
    reps_min: int | None = None
    reps_max: int | None = None
    weight: float | Decimal | None = None
    per_set_weights: list[float | Decimal] | None = None
    per_set_reps: list[int | str] | None = None
    rest_sec: int | None = None
    superset_group: str | None = None
    notes: str | None = None
    progression: bool = False
    mode: str = "reps"
    sec: int | None = None
    min: int | float | None = None
    speed: float | None = None


@dataclass
class RoutineSpec:
    name: str
    exercises: list[ExerciseSpec]
    id: str | None = None
    exclude_from_progression: bool = True
    notes: str | None = None


def add_or_update_routine(state: dict[str, Any], spec: RoutineSpec) -> str:
    """Add or update a routine in state from a spec.

    Ensures planned weights are preserved by setting excludeFromProgression=True
    on the routine, prog='off' when progression is false, and pyramid/pyramidWeight
    for per-set planned weights.
    """
    routines = state.setdefault("routines", [])
    routine_id = spec.id or make_uid()

    ex_list: list[dict[str, Any]] = []
    for ex in spec.exercises:
        cfg: dict[str, Any] = {
            "id": ex.exercise_id,
            "sets": ex.sets,
            "mode": ex.mode,
        }
        if ex.mode == "reps":
            if ex.reps is not None:
                cfg["reps"] = ex.reps
            if ex.reps_min is not None:
                cfg["repsMin"] = ex.reps_min
            if ex.reps_max is not None:
                cfg["repsMax"] = ex.reps_max
            if ex.weight is not None:
                cfg["weight"] = float(ex.weight)

            # Write pyramid/pyramidWeight only when per-set reps are known
            if ex.per_set_reps is not None:
                cfg["pyramid"] = list(ex.per_set_reps)
                if ex.per_set_weights is not None:
                    cfg["pyramidWeight"] = [float(w) for w in ex.per_set_weights]

            if not ex.progression:
                cfg["prog"] = "off"
        elif ex.mode == "time":
            cfg["sec"] = ex.sec or 45
            if ex.weight is not None:
                cfg["weight"] = float(ex.weight)
        elif ex.mode == "cardio":
            cfg["min"] = ex.min or 20
            if ex.speed is not None:
                cfg["speed"] = ex.speed

        if ex.rest_sec is not None:
            cfg["restSec"] = ex.rest_sec
        if ex.superset_group:
            cfg["sg"] = ex.superset_group
        if ex.notes:
            cfg["note"] = ex.notes

        ex_list.append(cfg)

    # Find existing routine to preserve extra fields if present
    existing_idx = next(
        (i for i, r in enumerate(routines) if isinstance(r, dict) and r.get("id") == routine_id),
        None,
    )

    if existing_idx is not None:
        updated = dict(routines[existing_idx])
        updated["name"] = spec.name
        updated["ex"] = ex_list
        updated["excludeFromProgression"] = spec.exclude_from_progression
        if spec.notes:
            updated["notes"] = spec.notes
        routines[existing_idx] = updated
    else:
        new_routine: dict[str, Any] = {
            "id": routine_id,
            "name": spec.name,
            "ex": ex_list,
            "excludeFromProgression": spec.exclude_from_progression,
        }
        if spec.notes:
            new_routine["notes"] = spec.notes
        routines.append(new_routine)

    return routine_id


def plan_routine(
    state: dict[str, Any],
    routine_id: str,
    date: str | dt.date | None = None,
    weekday: int | str | None = None,
) -> None:
    """Plan a routine on a specific date (dayPlan) or weekday (week)."""
    if date is not None:
        date_str = date.isoformat() if isinstance(date, dt.date) else str(date)
        day_plan = state.setdefault("dayPlan", {})
        day_plan[date_str] = routine_id

    if weekday is not None:
        wd_str = str(weekday)
        week = state.setdefault("week", {})
        week[wd_str] = routine_id
