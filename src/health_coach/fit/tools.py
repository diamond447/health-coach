"""MCP tools for the fit multi-user openGym server."""

import contextlib
import contextvars
import dataclasses
import datetime as dt
import functools
import logging
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal, NoReturn
from zoneinfo import ZoneInfo

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from health_coach.fit.settings import FitSettings
from health_coach.fit.store import FitStore
from health_coach.opengym.catalogue import (
    fetch_catalogue,
    merge_custom_exercises,
    search_catalogue,
)
from health_coach.opengym.client import (
    OpenGymAuthError,
    OpenGymClient,
    OpenGymError,
)
from health_coach.opengym.model import (
    LB_TO_KG,
    ExerciseSpec,
    RoutineSpec,
    add_or_update_routine,
    make_uid,
    normalize_workouts,
    plan_routine,
    read_routines,
)

log = logging.getLogger(__name__)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True)

# Context variables for test injection
current_subject_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fit_current_subject", default=None
)
mock_transport_var: contextvars.ContextVar[httpx.BaseTransport | None] = contextvars.ContextVar(
    "fit_mock_transport", default=None
)


def get_subject(settings: FitSettings) -> str:
    """The verified token's subject. Only with auth disabled (local development and
    tests) may an injected or configured dev subject stand in for it."""
    token = get_access_token()
    if token and token.subject:
        return token.subject
    if settings.auth_disabled:
        dev_sub = current_subject_var.get() or settings.dev_subject
        if dev_sub:
            return dev_sub
    raise ToolError("Authentication required: no subject found in access token")


def rnd_kg(val: float | Decimal | None, step: float = 0.5) -> float | None:
    """Round weight to 0.5, 0.1 or 0.01 kg steps."""
    if val is None:
        return None
    v = float(val)
    if step == 0.5:
        return round(v * 2.0) / 2.0
    if step == 0.01:
        return round(v, 2)
    return round(v, 1)


def fit_audited[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Audit tool call duration and subject without logging workout content or tokens."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.monotonic()
        sub = None
        with contextlib.suppress(Exception):
            token = get_access_token()
            sub = token.subject if token else current_subject_var.get()
        try:
            result = fn(*args, **kwargs)
            ms = int((time.monotonic() - started) * 1000)
            log.info("fit tool %s completed: subject=%s duration_ms=%d", fn.__name__, sub, ms)
            return result
        except Exception as exc:
            ms = int((time.monotonic() - started) * 1000)
            log.info(
                "fit tool %s failed: subject=%s duration_ms=%d error=%s",
                fn.__name__,
                sub,
                ms,
                type(exc).__name__,
            )
            raise

    return wrapper


# Set on routines that plan_session created (value: the planned date), so a later
# replace only ever rewrites those and never a routine the user built.
PLANNED_MARKER = "fitPlanned"


class PlanExerciseSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reps: int | Literal["max"] = Field(
        ...,
        description="Rep count (1..100) or 'max' for AMRAP",
    )
    weight_kg: float | None = Field(
        default=None,
        ge=0.0,
        le=1000.0,
        description="Weight in kg (0..1000)",
    )
    rir: float | None = Field(
        default=None,
        ge=0.0,
        le=10.0,
        description="Reps in reserve (0..10)",
    )
    rpe: float | None = Field(
        default=None,
        ge=1.0,
        le=10.0,
        description="Rate of perceived exertion (1..10)",
    )
    warmup: bool = Field(
        default=False,
        description="Warm-up set flag",
    )

    @field_validator("reps")
    @classmethod
    def validate_reps(cls, v: Any) -> int | Literal["max"]:
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean == "max":
                return "max"
            try:
                v = int(clean)
            except ValueError as err:
                raise ValueError("reps must be an integer between 1 and 100 or 'max'") from err
        if isinstance(v, int):
            if v < 1 or v > 100:
                raise ValueError("reps must be between 1 and 100")
            return v
        raise ValueError("reps must be an integer between 1 and 100 or 'max'")


class PlanExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(
        default="",
        max_length=80,
        description="Exercise ID from catalogue or custom exercises",
    )
    sets: int | list[PlanExerciseSet] = Field(
        default=3,
        description="Number of sets (1..10) or list of per-set definitions (max 10)",
    )
    reps: int | Literal["max"] | None = Field(
        default=None,
        description="Target reps (1..100) or 'max' for flat sets",
    )
    reps_min: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Minimum reps in target range (1..100)",
    )
    reps_max: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum reps in target range (1..100)",
    )
    weight_kg: float | None = Field(
        default=None,
        ge=0.0,
        le=1000.0,
        description="Working weight in kg (0..1000)",
    )
    rest_s: int | None = Field(
        default=None,
        ge=0,
        le=3600,
        description="Rest time in seconds (0..3600)",
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Exercise notes (max 500 characters)",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Alias for note",
    )
    superset_group: str | None = Field(
        default=None,
        max_length=50,
        description="Superset group identifier",
    )
    id: str | None = Field(
        default=None,
        max_length=80,
        description="Alias for exercise_id",
    )
    pyramid: list[int | Literal["max"]] | None = Field(
        default=None,
        description="Optional pyramid rep targets",
    )
    pyramid_weight: list[float] | None = Field(
        default=None,
        description="Optional pyramid weights",
    )
    progression: bool | None = Field(
        default=None,
        description="Progression enabled flag",
    )
    reps_range: str | None = Field(
        default=None,
        description="Rep range string (e.g. 8-12)",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "id" in data and not data.get("exercise_id"):
                data["exercise_id"] = data["id"]
            if "rest_sec" in data and "rest_s" not in data:
                data["rest_s"] = data["rest_sec"]
            if "notes" in data and "note" not in data:
                data["note"] = data["notes"]
        return data

    @field_validator("exercise_id")
    @classmethod
    def validate_exercise_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("exercise_id cannot be empty")
        return s

    @field_validator("sets")
    @classmethod
    def validate_sets(cls, v: Any) -> int | list[PlanExerciseSet]:
        if isinstance(v, int):
            if v < 1 or v > 10:
                raise ValueError("sets must be between 1 and 10")
            return v
        if isinstance(v, list):
            if len(v) < 1 or len(v) > 10:
                raise ValueError("sets list must contain between 1 and 10 sets")
            return v
        raise ValueError("sets must be an integer (1..10) or a list of sets")

    @field_validator("reps")
    @classmethod
    def validate_reps(cls, v: Any) -> int | Literal["max"] | None:
        if v is None:
            return None
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean == "max":
                return "max"
            try:
                v = int(clean)
            except ValueError as err:
                raise ValueError("reps must be an integer between 1 and 100 or 'max'") from err
        if isinstance(v, int):
            if v < 1 or v > 100:
                raise ValueError("reps must be between 1 and 100")
            return v
        raise ValueError("reps must be an integer between 1 and 100 or 'max'")

    @model_validator(mode="after")
    def validate_rep_range(self) -> "PlanExercise":
        if (
            self.reps_min is not None
            and self.reps_max is not None
            and self.reps_min > self.reps_max
        ):
            raise ValueError("reps_min cannot be greater than reps_max")
        return self


class UpdateRoutineChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        description="Updated routine name",
    )
    exercises: list[PlanExercise] | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="Updated exercises (max 30)",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Routine notes (max 500 characters)",
    )
    exclude_from_progression: bool | None = Field(
        default=None,
        description="Whether to exclude from openGym progression",
    )


def _validate_date(date_str: str, tz: ZoneInfo) -> dt.date:
    try:
        target_date = dt.date.fromisoformat(date_str)
    except ValueError as exc:
        raise ToolError(f"Invalid date format '{date_str}': expected YYYY-MM-DD.") from exc
    today = dt.datetime.now(tz).date()
    min_date = today - dt.timedelta(days=400)
    max_date = today + dt.timedelta(days=400)
    if not (min_date <= target_date <= max_date):
        raise ToolError(
            f"Date '{date_str}' is out of range. Allowed range is -400..+400 days from today "
            f"({min_date.isoformat()} to {max_date.isoformat()})."
        )
    return target_date


def _build_exercise_spec(ex: PlanExercise) -> ExerciseSpec:
    note_val = ex.note or ex.notes
    if isinstance(ex.sets, list):
        set_count = len(ex.sets)
        per_set_reps: list[int | str] = [s.reps for s in ex.sets]
        has_any_weight = any(s.weight_kg is not None for s in ex.sets)
        per_set_weights: list[float | Decimal] | None = None
        if has_any_weight or ex.weight_kg is not None:
            fallback = rnd_kg(ex.weight_kg, 0.01) or 0.0
            per_set_weights = [
                rnd_kg(s.weight_kg, 0.01) or 0.0 if s.weight_kg is not None else fallback
                for s in ex.sets
            ]
        first_w = per_set_weights[0] if per_set_weights else rnd_kg(ex.weight_kg, 0.01)
        return ExerciseSpec(
            exercise_id=ex.exercise_id,
            sets=set_count,
            weight=first_w,
            reps=per_set_reps[0] if isinstance(per_set_reps[0], int) else None,
            per_set_weights=per_set_weights,
            per_set_reps=per_set_reps,
            rest_sec=ex.rest_s,
            superset_group=ex.superset_group,
            notes=note_val.strip() if note_val else None,
            progression=False,
        )
    else:
        set_count = int(ex.sets)
        w_val = rnd_kg(ex.weight_kg, 0.01)
        if ex.pyramid:
            per_set_reps = list(ex.pyramid)
            per_set_weights = (
                [rnd_kg(w, 0.01) or 0.0 for w in ex.pyramid_weight] if ex.pyramid_weight else None
            )
            first_w = per_set_weights[0] if per_set_weights else w_val
            return ExerciseSpec(
                exercise_id=ex.exercise_id,
                sets=len(ex.pyramid),
                weight=first_w,
                reps=per_set_reps[0] if isinstance(per_set_reps[0], int) else None,
                per_set_weights=per_set_weights,
                per_set_reps=per_set_reps,
                rest_sec=ex.rest_s,
                superset_group=ex.superset_group,
                notes=note_val.strip() if note_val else None,
                progression=False,
            )
        return ExerciseSpec(
            exercise_id=ex.exercise_id,
            sets=set_count,
            reps=ex.reps if isinstance(ex.reps, int) else None,
            reps_min=ex.reps_min,
            reps_max=ex.reps_max,
            weight=w_val,
            per_set_weights=None,
            per_set_reps=None,
            rest_sec=ex.rest_s,
            superset_group=ex.superset_group,
            notes=note_val.strip() if note_val else None,
            progression=False,
        )


def _routine_ids_of(w: dict[str, Any]) -> list[str]:
    rids = w.get("routineIds")
    if isinstance(rids, list):
        return [str(x) for x in rids]
    rid = w.get("routineId")
    return [str(rid)] if rid else []


def _is_workout_done_for(state: dict[str, Any], queue: dict[str, Any], r_id: str) -> bool:
    routines = state.get("routines") or []
    r_obj = next((r for r in routines if isinstance(r, dict) and r.get("id") == r_id), None)
    r_name = str(r_obj.get("name") or "") if r_obj else ""

    since = queue.get("since") or 0
    strict = queue.get("strict") is True
    starts_on_val = queue.get("startsOn")
    starts_on: str = (
        str(starts_on_val)
        if isinstance(starts_on_val, str)
        else dt.datetime.fromtimestamp(since / 1000, dt.UTC).date().isoformat()
    )

    for w in state.get("workouts") or []:
        if not isinstance(w, dict):
            continue
        if r_id not in _routine_ids_of(w):
            continue
        w_start = w.get("start") or 0
        w_d = str(w.get("d") or "")
        name_parts = str(w.get("name") or "").split(" + ")
        if w_start >= since or (not strict and w_d >= starts_on and r_name in name_parts):
            return True
    return False


def _queue_of(state: dict[str, Any]) -> dict[str, Any] | None:
    q = state.get("queue")
    if not isinstance(q, dict) or not isinstance(q.get("ids"), list):
        return None
    routines = {r.get("id") for r in (state.get("routines") or []) if isinstance(r, dict)}
    seen: set[str] = set()
    ids: list[str] = []
    for x in q["ids"]:
        if x in routines and x not in seen:
            seen.add(x)
            ids.append(x)
    if not ids:
        return None
    starts_on = (
        q.get("startsOn")
        if isinstance(q.get("startsOn"), str)
        else dt.datetime.fromtimestamp((q.get("since") or 0) / 1000, dt.UTC).date().isoformat()
    )
    return {**q, "ids": ids, "startsOn": starts_on}


def _effective_routine_ids(state: dict[str, Any], iso: str, today_iso: str) -> list[str]:
    day_plan = state.get("dayPlan") or {}
    routines = state.get("routines") or []
    routine_ids = {r.get("id") for r in routines if isinstance(r, dict)}

    ov = day_plan.get(iso)
    if ov == "rest":
        return []

    q = _queue_of(state)

    pin = None
    if q and ov and ov in q["ids"]:
        pin = "done" if _is_workout_done_for(state, q, ov) else "open"

    if not pin and ov and ov in routine_ids:
        return [ov]

    d = dt.date.fromisoformat(iso)
    js_wd = (d.weekday() + 1) % 7

    week = state.get("week") or {}
    raw_week = week.get(str(js_wd)) or week.get(js_wd) or []
    weekday_ids = (
        [raw_week]
        if isinstance(raw_week, str)
        else (list(raw_week) if isinstance(raw_week, list) else [])
    )
    weekday = [rid for rid in weekday_ids if rid in routine_ids]

    q_next = None
    queue_live = False
    if q:
        remaining = [rid for rid in q["ids"] if not _is_workout_done_for(state, q, rid)]
        on = today_iso if today_iso > q["startsOn"] else q["startsOn"]

        active_pins = [
            {"iso": p_iso, "id": p_id}
            for p_iso, p_id in day_plan.items()
            if p_iso >= today_iso and p_id in remaining
        ]
        here = next((p["id"] for p in active_pins if p["iso"] == on), None)
        next_on = (
            here
            if here
            else next(
                (rid for rid in remaining if not any(p["id"] == rid for p in active_pins)), None
            )
        )

        if iso == on:
            q_next = next_on
        queue_live = iso == on and len(remaining) > 0

    q_pick = ov if pin == "open" else q_next
    if q_pick or queue_live:
        q_ids_set = set(q["ids"]) if q else set()
        own = [rid for rid in weekday if rid not in q_ids_set]
    else:
        own = weekday

    return [q_pick, *own] if q_pick else own


def _in_user_unit(spec: ExerciseSpec, state: dict[str, Any]) -> ExerciseSpec:
    """Planned weights arrive in kg; openGym stores them in the profile's unit."""
    if str(state.get("unit") or "kg").lower() != "lb":
        return spec

    def to_lb(w: float | Decimal | None) -> float | None:
        if w is None:
            return None
        return float((Decimal(str(w)) / LB_TO_KG).quantize(Decimal("0.1")))

    return dataclasses.replace(
        spec,
        weight=to_lb(spec.weight),
        per_set_weights=(
            [to_lb(w) or 0.0 for w in spec.per_set_weights]
            if spec.per_set_weights is not None
            else None
        ),
    )


def _raise_opengym_error(exc: Exception) -> NoReturn:
    """Map openGym client errors to clear assistant-facing ToolErrors."""
    if isinstance(exc, OpenGymAuthError):
        raise ToolError(
            "openGym session expired or unauthorized (401). "
            "Your link was preserved, but you must pair again: "
            "open the openGym web app, Settings -> 'Pair the mobile app', "
            "and call link_opengym(code)."
        ) from exc
    raise ToolError(f"openGym error: {exc}") from exc


def _get_client_for_subject(
    subject: str, settings: FitSettings, store: FitStore
) -> tuple[OpenGymClient, Any]:
    link = store.get_link(subject)
    if not link:
        raise ToolError(
            "You are not connected to an openGym account. Open the openGym web app, "
            "go to Settings -> 'Pair the mobile app', click 'Generate code', and call "
            "link_opengym(code) with the 8-character pairing code."
        )
    if not settings.opengym_url:
        raise ToolError("FIT_OPENGYM_URL is not configured on this server.")

    store.touch_last_used(subject)
    client = OpenGymClient(
        base_url=settings.opengym_url,
        token=link.token,
        transport=mock_transport_var.get(),
    )

    now = dt.datetime.now(dt.UTC)
    last_check = link.renewed_at or link.linked_at
    if last_check is not None:
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=dt.UTC)
        if (now - last_check) >= dt.timedelta(days=7):
            try:
                me_res = client.me()
                renewed = me_res.get("token")
                if renewed:
                    store.update_token(subject, str(renewed))
                    link = store.get_link(subject) or link
                    client.token = link.token
                else:
                    store.touch_renewed(subject)
            except OpenGymAuthError as exc:
                _raise_opengym_error(exc)
            except Exception as exc:
                log.warning("Background token renewal failed for %s: %s", subject, exc)

    return client, link


def register_fit_tools(server: MCPServer, settings: FitSettings, store: FitStore) -> None:
    """Register all fit tools on the MCPServer instance."""

    # 1. link_opengym
    @server.tool(
        name="link_opengym",
        description=(
            "Pair this assistant with your openGym account using the 8-character pairing code "
            "from Settings -> 'Pair the mobile app' in the openGym web app."
        ),
        annotations=WRITE,
    )
    @fit_audited
    def link_opengym(code: str) -> dict[str, Any]:
        subject = get_subject(settings)
        clean_code = code.strip().upper()
        if not clean_code or len(clean_code) != 8:
            raise ToolError("Pairing code must be an 8-character alphanumeric string.")
        if not settings.opengym_url:
            raise ToolError("FIT_OPENGYM_URL is not configured.")

        with OpenGymClient(settings.opengym_url, transport=mock_transport_var.get()) as client:
            try:
                res = client.pair_redeem(clean_code)
            except OpenGymAuthError as exc:
                raise ToolError("Invalid or expired openGym pairing code.") from exc
            except OpenGymError as exc:
                raise ToolError(f"Pairing failed: {exc}") from exc

        token = res.get("token")
        if not token:
            raise ToolError("openGym did not return a session token.")
        user = res.get("user") or {}
        user_id = str(user.get("id") or "")
        user_name = str(user.get("name") or "")

        store.save_link(subject, token, user_id=user_id, user_name=user_name)
        return {
            "status": "linked",
            "openGym_username": user_name,
            "openGym_user_id": user_id,
        }

    # 2. unlink_opengym
    @server.tool(
        name="unlink_opengym",
        description="Disconnect your openGym account from this assistant.",
        annotations=DESTRUCTIVE,
    )
    @fit_audited
    def unlink_opengym() -> dict[str, Any]:
        subject = get_subject(settings)
        deleted = store.delete_link(subject)
        return {"status": "unlinked" if deleted else "not_linked"}

    # 3. get_account
    @server.tool(
        name="get_account",
        description="Get openGym account profile, session status, and check token renewal.",
        annotations=READ,
    )
    @fit_audited
    def get_account() -> dict[str, Any]:
        subject = get_subject(settings)
        client, link = _get_client_for_subject(subject, settings, store)
        try:
            with client:
                me_res = client.me()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        renewed_token = me_res.get("token")
        if renewed_token:
            store.update_token(subject, str(renewed_token))
            link = store.get_link(subject) or link

        user = me_res.get("user") or {}
        return {
            "status": "connected",
            "openGym_user_id": user.get("id") or link.opengym_user_id,
            "openGym_username": user.get("name") or link.opengym_user_name,
            "linked_at": link.linked_at.isoformat(),
            "renewed_at": link.renewed_at.isoformat() if link.renewed_at else None,
            "last_used_at": link.last_used_at.isoformat() if link.last_used_at else None,
        }

    # 4. search_exercises
    @server.tool(
        name="search_exercises",
        description=(
            "Search the exercise catalogue and user custom exercises by name, "
            "muscle group, or equipment."
        ),
        annotations=READ,
    )
    @fit_audited
    def search_exercises(
        query: str | None = None,
        muscle: str | None = None,
        equipment: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ToolError("limit must be between 1 and 100.")
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)

        try:
            with client:
                data = client.get_data()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        state = data.get("state") or {}
        custom_ex = state.get("customEx") or []
        catalogue = fetch_catalogue(version=settings.opengym_version, use_cache=True)
        merged = merge_custom_exercises(catalogue, custom_ex)
        results = search_catalogue(merged, query=query, muscle=muscle, equipment=equipment)

        return {
            "count": len(results[:limit]),
            "exercises": [
                {
                    "id": str(ex.get("id")),
                    "name": str(ex.get("n") or ex.get("name") or ""),
                    "muscle_group": str(ex.get("mg") or ex.get("muscle_group") or ""),
                    "target": str(ex.get("tg") or ex.get("target") or ""),
                    "equipment": str(ex.get("eq") or ex.get("equipment") or ""),
                    "is_custom": bool(ex.get("custom") or str(ex.get("id", "")).startswith("c_")),
                }
                for ex in results[:limit]
            ],
        }

    # 5. get_training_history
    @server.tool(
        name="get_training_history",
        description=(
            "Get recent completed workout sessions with exercises and sets (weight, reps, rir). "
            "If exercise is specified, returns top set and e1RM progression trend."
        ),
        annotations=READ,
    )
    @fit_audited
    def get_training_history(
        days: int = 28,
        exercise: str | None = None,
    ) -> dict[str, Any]:
        if days < 1 or days > 365:
            raise ToolError("days must be between 1 and 365.")
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)

        try:
            with client:
                data = client.get_data()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        state = data.get("state") or {}
        sessions = normalize_workouts(state, tz=settings.tz)
        today = dt.datetime.now(settings.tz).date()
        cutoff = today - dt.timedelta(days=days - 1)

        recent = [s for s in sessions if s.local_date >= cutoff]
        recent.sort(key=lambda s: s.local_date)

        target_ex = exercise.strip().lower() if exercise else None

        if target_ex:
            history_rows: list[dict[str, Any]] = []
            for s in recent:
                matching_sets = [
                    st
                    for st in s.sets
                    if target_ex in st.exercise_id.lower() and not st.is_warmup and st.done
                ]
                if not matching_sets:
                    continue
                valid_sets = [
                    st for st in matching_sets if st.weight_kg is not None and (st.reps or 0) > 0
                ]
                top_set = max(
                    valid_sets,
                    key=lambda x: (
                        x.weight_kg or 0,
                        (x.weight_kg or 0) * (1 + (x.reps or 0) / Decimal("30")),
                    ),
                    default=None,
                )
                if top_set and top_set.weight_kg is not None and top_set.reps:
                    w = float(top_set.weight_kg)
                    r = int(top_set.reps)
                    # Epley formula for e1RM: w * (1 + r / 30)
                    e1rm = round(w * (1.0 + r / 30.0), 1)
                    history_rows.append(
                        {
                            "date": s.local_date.isoformat(),
                            "session_name": s.routine_name,
                            "top_weight_kg": rnd_kg(w, 0.5),
                            "reps": r,
                            "rir": float(top_set.rir) if top_set.rir is not None else None,
                            "e1rm_kg": rnd_kg(e1rm, 0.5),
                            "total_sets": len(matching_sets),
                        }
                    )
            return {
                "exercise": exercise,
                "days": days,
                "sessions_count": len(history_rows),
                "trend": history_rows,
            }

        # Full history summary
        formatted_sessions: list[dict[str, Any]] = []
        for s in recent:
            ex_map: dict[str, list[dict[str, Any]]] = {}
            for st in s.sets:
                ex_sets = ex_map.setdefault(st.exercise_id, [])
                ex_sets.append(
                    {
                        "set_no": st.set_no,
                        "weight_kg": rnd_kg(st.weight_kg, 0.5),
                        "reps": int(st.reps) if st.reps is not None else None,
                        "rir": float(st.rir) if st.rir is not None else None,
                        "rpe": float(st.rpe) if st.rpe is not None else None,
                        "warmup": st.is_warmup,
                        "done": st.done,
                    }
                )
            formatted_sessions.append(
                {
                    "id": s.external_id,
                    "date": s.local_date.isoformat(),
                    "name": s.routine_name,
                    "notes": s.notes,
                    "exercises": [
                        {"exercise_id": eid, "sets": sets_list} for eid, sets_list in ex_map.items()
                    ],
                }
            )

        return {
            "days": days,
            "sessions_count": len(formatted_sessions),
            "sessions": formatted_sessions,
        }

    # 6. get_routines
    @server.tool(
        name="get_routines",
        description="List all routine templates configured in the user's openGym account.",
        annotations=READ,
    )
    @fit_audited
    def get_routines() -> dict[str, Any]:
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)
        try:
            with client:
                data = client.get_data()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        state = data.get("state") or {}
        routines = read_routines(state)
        is_lb = str(state.get("unit") or "kg").lower() == "lb"

        def to_kg(w: float | Decimal | None) -> float | None:
            if w is None:
                return None
            if is_lb:
                return float((Decimal(str(w)) * LB_TO_KG).quantize(Decimal("0.01")))
            return float(Decimal(str(w)).quantize(Decimal("0.01")))

        return {
            "count": len(routines),
            "routines": [
                {
                    "id": r.id,
                    "name": r.name,
                    "exercise_count": r.exercise_count,
                    "exclude_from_progression": r.exclude_from_progression,
                    "exercises": [
                        {
                            "exercise_id": ex.id,
                            "sets": ex.sets,
                            "reps": ex.reps,
                            "reps_min": ex.reps_min,
                            "reps_max": ex.reps_max,
                            "reps_range": (
                                f"{ex.reps_min}-{ex.reps_max}"
                                if ex.reps_min and ex.reps_max
                                else None
                            ),
                            "weight_kg": to_kg(ex.weight),
                            "pyramid": ex.pyramid,
                            "pyramid_weight": (
                                [to_kg(w) for w in ex.pyramid_weight] if ex.pyramid_weight else None
                            ),
                            "rest_s": ex.rest_sec,
                            "superset_group": ex.superset_group,
                            "progression": ex.progression,
                            "note": ex.note,
                        }
                        for ex in r.exercises
                    ],
                }
                for r in routines
            ],
        }

    # 7. get_routine
    @server.tool(
        name="get_routine",
        description="Get full configuration of a specific openGym routine by its routine ID.",
        annotations=READ,
    )
    @fit_audited
    def get_routine(routine_id: str) -> dict[str, Any]:
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)
        try:
            with client:
                data = client.get_data()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        state = data.get("state") or {}
        routines = read_routines(state)
        match = next((r for r in routines if r.id == routine_id), None)
        if not match:
            raise ToolError(f"Routine '{routine_id}' not found.")

        is_lb = str(state.get("unit") or "kg").lower() == "lb"

        def to_kg(w: float | Decimal | None) -> float | None:
            if w is None:
                return None
            if is_lb:
                return float((Decimal(str(w)) * LB_TO_KG).quantize(Decimal("0.01")))
            return float(Decimal(str(w)).quantize(Decimal("0.01")))

        return {
            "id": match.id,
            "name": match.name,
            "exclude_from_progression": match.exclude_from_progression,
            "exercises": [
                {
                    "exercise_id": ex.id,
                    "sets": ex.sets,
                    "reps": ex.reps,
                    "reps_min": ex.reps_min,
                    "reps_max": ex.reps_max,
                    "weight_kg": to_kg(ex.weight),
                    "pyramid": ex.pyramid,
                    "pyramid_weight": (
                        [to_kg(w) for w in ex.pyramid_weight] if ex.pyramid_weight else None
                    ),
                    "rest_s": ex.rest_sec,
                    "superset_group": ex.superset_group,
                    "progression": ex.progression,
                    "note": ex.note,
                }
                for ex in match.exercises
            ],
        }

    # 8. get_planned
    @server.tool(
        name="get_planned",
        description=(
            "See what openGym will open on upcoming days "
            "(dayPlan, coach queue, and recurring week)."
        ),
        annotations=READ,
    )
    @fit_audited
    def get_planned(days: int = 14) -> dict[str, Any]:
        if days < 1 or days > 60:
            raise ToolError("days must be between 1 and 60.")
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)
        try:
            with client:
                data = client.get_data()
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        state = data.get("state") or {}
        day_plan = state.get("dayPlan") or {}
        routines_map = {r.id: r for r in read_routines(state)}

        today = dt.datetime.now(settings.tz).date()
        today_iso = today.isoformat()
        schedule_list: list[dict[str, Any]] = []

        weekday_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

        for i in range(days):
            d = today + dt.timedelta(days=i)
            iso = d.isoformat()
            wd_name = weekday_names[d.weekday()]

            effective_ids = _effective_routine_ids(state, iso, today_iso)
            ov = day_plan.get(iso)

            if not effective_ids:
                source = "dayPlan" if ov == "rest" else "none"
                schedule_list.append(
                    {
                        "date": iso,
                        "weekday": wd_name,
                        "planned": "rest",
                        "source": source,
                        "routines": [],
                    }
                )
            else:
                matched_routines = [
                    routines_map[rid] for rid in effective_ids if rid in routines_map
                ]
                primary = matched_routines[0] if matched_routines else None
                source = (
                    "dayPlan"
                    if (ov and ov in effective_ids)
                    else (
                        "queue"
                        if (
                            state.get("queue")
                            and effective_ids[0] in (state["queue"].get("ids") or [])
                        )
                        else "week"
                    )
                )
                schedule_list.append(
                    {
                        "date": iso,
                        "weekday": wd_name,
                        "planned": "routine",
                        "routine_id": primary.id if primary else effective_ids[0],
                        "routine_name": primary.name if primary else effective_ids[0],
                        "exercise_count": primary.exercise_count if primary else 0,
                        "routines": [
                            {
                                "routine_id": r.id,
                                "routine_name": r.name,
                                "exercise_count": r.exercise_count,
                            }
                            for r in matched_routines
                        ],
                        "source": source,
                    }
                )

        return {"days": days, "schedule": schedule_list}

    # 9. plan_session
    @server.tool(
        name="plan_session",
        description=(
            "Plan a dated workout session with explicit exercises, sets, reps, and weights. "
            "Applies excludeFromProgression=true so openGym opens the session with exact weights."
        ),
        annotations=WRITE,
    )
    @fit_audited
    def plan_session(
        date: str,
        name: str,
        exercises: list[PlanExercise],
        replace: bool = False,
    ) -> dict[str, Any]:
        target_date = _validate_date(date, settings.tz)
        if not name or not name.strip():
            raise ToolError("Session name cannot be empty.")
        if len(name.strip()) > 80:
            raise ToolError("Session name must be at most 80 characters.")
        if not exercises:
            raise ToolError("At least one exercise is required to plan a session.")
        if len(exercises) > 30:
            raise ToolError("At most 30 exercises can be planned in a session.")

        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)

        specs: list[ExerciseSpec] = [_build_exercise_spec(ex) for ex in exercises]
        iso_date = target_date.isoformat()
        new_routine_id = make_uid()

        def plan_mutator(state: dict[str, Any]) -> dict[str, Any]:
            day_plan = state.setdefault("dayPlan", {})
            existing = day_plan.get(iso_date)

            planned_here = {
                r.get("id")
                for r in state.get("routines") or []
                if isinstance(r, dict) and r.get(PLANNED_MARKER)
            }
            target_id = existing if (replace and existing in planned_here) else new_routine_id

            # Idempotency check: if date already points to routine id we are writing
            if (
                day_plan.get(iso_date) == target_id
                and not replace
                and any(
                    isinstance(r, dict) and r.get("id") == target_id
                    for r in state.get("routines") or []
                )
            ):
                return state

            if existing and not replace:
                raise ToolError(
                    f"A session is already planned for {iso_date}. "
                    "Use replace=true to overwrite it."
                )

            routine_spec = RoutineSpec(
                id=target_id,
                name=name.strip(),
                exercises=[_in_user_unit(e, state) for e in specs],
                exclude_from_progression=True,
            )
            r_id = add_or_update_routine(state, routine_spec)
            for routine in state.get("routines") or []:
                if isinstance(routine, dict) and routine.get("id") == r_id:
                    routine[PLANNED_MARKER] = iso_date
            plan_routine(state, r_id, date=iso_date)
            return state

        try:
            with client:
                client.mutate(plan_mutator)
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        return {
            "status": "planned",
            "date": iso_date,
            "session_name": name,
            "exercises": [
                {
                    "exercise_id": sp.exercise_id,
                    "sets": sp.sets,
                    "reps": sp.reps,
                    "weight_kg": sp.weight,
                    "per_set_weights": sp.per_set_weights,
                    "per_set_reps": sp.per_set_reps,
                }
                for sp in specs
            ],
        }

    # 10. update_routine
    @server.tool(
        name="update_routine",
        description="Update an existing routine definition (name, exercises, progression).",
        annotations=WRITE,
    )
    @fit_audited
    def update_routine(routine_id: str, changes: UpdateRoutineChanges) -> dict[str, Any]:
        if not routine_id:
            raise ToolError("routine_id is required.")
        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)

        def update_mutator(state: dict[str, Any]) -> dict[str, Any]:
            routines = state.setdefault("routines", [])
            target = next(
                (r for r in routines if isinstance(r, dict) and r.get("id") == routine_id),
                None,
            )
            if target is None:
                raise ToolError(f"Routine '{routine_id}' not found.")

            if not target.get(PLANNED_MARKER):
                raise ToolError(
                    f"Routine '{routine_id}' was not planned by this assistant; "
                    "plan a new session instead."
                )

            new_name = changes.name.strip() if changes.name else str(target.get("name") or "")
            new_notes = changes.notes.strip() if changes.notes else target.get("notes")
            exclude = (
                changes.exclude_from_progression
                if changes.exclude_from_progression is not None
                else target.get("excludeFromProgression", True)
            )

            if changes.exercises is not None:
                specs = [_build_exercise_spec(e) for e in changes.exercises]
                routine_spec = RoutineSpec(
                    id=routine_id,
                    name=new_name,
                    exercises=[_in_user_unit(e, state) for e in specs],
                    exclude_from_progression=bool(exclude),
                    notes=new_notes,
                )
                add_or_update_routine(state, routine_spec)
                for r in state.get("routines") or []:
                    if (
                        isinstance(r, dict)
                        and r.get("id") == routine_id
                        and not r.get(PLANNED_MARKER)
                    ):
                        r[PLANNED_MARKER] = target.get(PLANNED_MARKER)
            else:
                target["name"] = new_name
                if new_notes:
                    target["notes"] = new_notes
                if changes.exclude_from_progression is not None:
                    target["excludeFromProgression"] = bool(changes.exclude_from_progression)

            return state

        try:
            with client:
                client.mutate(update_mutator)
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        return {"status": "updated", "routine_id": routine_id}

    # 11. schedule_week
    @server.tool(
        name="schedule_week",
        description=(
            "Set the weekly routine schedule mapping weekdays ('mon'..'sun' or 0..6) to "
            "routine IDs (single routine ID, or list of routine IDs for days with "
            "multiple routines). "
            "Setting a weekday replaces whatever was previously scheduled for that day. "
            "Setting a weekday to null or 'rest' clears it."
        ),
        annotations=WRITE,
    )
    @fit_audited
    def schedule_week(schedule: dict[str, list[str] | str | None]) -> dict[str, Any]:
        if not schedule:
            raise ToolError("schedule dictionary cannot be empty.")

        day_map = {
            "mon": "1",
            "monday": "1",
            "1": "1",
            "tue": "2",
            "tuesday": "2",
            "2": "2",
            "wed": "3",
            "wednesday": "3",
            "3": "3",
            "thu": "4",
            "thursday": "4",
            "4": "4",
            "fri": "5",
            "friday": "5",
            "5": "5",
            "sat": "6",
            "saturday": "6",
            "6": "6",
            "sun": "0",
            "sunday": "0",
            "0": "0",
            "7": "0",
        }

        normalized_schedule: dict[str, list[str] | None] = {}
        for raw_k, raw_v in schedule.items():
            k_clean = str(raw_k).strip().lower()
            if k_clean not in day_map:
                raise ToolError(f"Unknown weekday '{raw_k}': use 'mon'..'sun' or day numbers 0..6.")
            target_day = day_map[k_clean]
            if raw_v is None:
                normalized_schedule[target_day] = None
            elif isinstance(raw_v, str):
                if raw_v.strip().lower() == "rest":
                    normalized_schedule[target_day] = None
                else:
                    normalized_schedule[target_day] = [raw_v.strip()]
            elif isinstance(raw_v, list):
                cleaned_list = [
                    str(x).strip() for x in raw_v if x and str(x).strip().lower() != "rest"
                ]
                normalized_schedule[target_day] = cleaned_list if cleaned_list else None
            else:
                raise ToolError(
                    f"Invalid schedule value for weekday '{raw_k}': "
                    "expected routine ID or list of routine IDs."
                )

        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)

        def week_mutator(state: dict[str, Any]) -> dict[str, Any]:
            week = state.setdefault("week", {})
            routines = state.get("routines") or []
            routine_ids = {r.get("id") for r in routines if isinstance(r, dict)}

            for day_idx, r_ids in normalized_schedule.items():
                if r_ids is None:
                    week.pop(day_idx, None)
                else:
                    for rid in r_ids:
                        if rid not in routine_ids:
                            raise ToolError(f"Routine ID '{rid}' not found in routines.")
                    week[day_idx] = r_ids
            return state

        try:
            with client:
                client.mutate(week_mutator)
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        return {"status": "scheduled", "updated_week": normalized_schedule}

    # 12. delete_planned
    @server.tool(
        name="delete_planned",
        description="Delete a planned workout for a specific date (removes from dayPlan).",
        annotations=DESTRUCTIVE,
    )
    @fit_audited
    def delete_planned(date: str) -> dict[str, Any]:
        target_date = _validate_date(date, settings.tz)
        iso_date = target_date.isoformat()

        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)
        was_rest = False

        def delete_mutator(state: dict[str, Any]) -> dict[str, Any]:
            nonlocal was_rest
            day_plan = state.setdefault("dayPlan", {})
            if day_plan.get(iso_date) == "rest":
                was_rest = True
                return state

            unplanned_id = day_plan.pop(iso_date, None)
            if unplanned_id is None:
                og_wd = (target_date.weekday() + 1) % 7
                week = state.get("week") or {}
                if str(og_wd) in week or og_wd in week:
                    day_plan[iso_date] = "rest"

            # Garbage collect unreferenced fitPlanned routines:
            # - not in dayPlan, week or queue
            # - whose planned date is in the past OR that delete_planned just unplanned
            ref_day_plan = {v for v in day_plan.values() if v and v != "rest"}
            ref_week: set[str] = set()
            for wk_val in (state.get("week") or {}).values():
                if isinstance(wk_val, list):
                    ref_week.update(wk_val)
                elif isinstance(wk_val, str):
                    ref_week.add(wk_val)
            q_ids: set[str] = set()
            queue = state.get("queue")
            if isinstance(queue, dict) and isinstance(queue.get("ids"), list):
                q_ids.update(queue["ids"])
            all_ref = ref_day_plan | ref_week | q_ids

            today_iso = dt.datetime.now(settings.tz).date().isoformat()
            routines = state.get("routines") or []
            state["routines"] = [
                r
                for r in routines
                if not (
                    isinstance(r, dict)
                    and r.get(PLANNED_MARKER)
                    and r.get("id") not in all_ref
                    and (
                        str(r.get(PLANNED_MARKER)) < today_iso
                        or r.get("id") == unplanned_id
                        or str(r.get(PLANNED_MARKER)) == iso_date
                    )
                )
            ]
            return state

        try:
            with client:
                client.mutate(delete_mutator)
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        if was_rest:
            return {
                "status": "unchanged",
                "date": iso_date,
                "message": f"{iso_date} is a rest day; override preserved.",
            }
        return {"status": "deleted", "date": iso_date}

    # 13. log_session
    @server.tool(
        name="log_session",
        description=(
            "Log a completed workout session directly into openGym for sessions the user tells "
            "the assistant about instead of logging in the app."
        ),
        annotations=WRITE,
    )
    @fit_audited
    def log_session(
        date: str,
        exercises: list[PlanExercise],
        notes: str | None = None,
    ) -> dict[str, Any]:
        target_date = _validate_date(date, settings.tz)
        if not exercises:
            raise ToolError("At least one exercise is required to log a session.")
        if len(exercises) > 30:
            raise ToolError("At most 30 exercises can be logged in a session.")
        if notes and len(notes) > 500:
            raise ToolError("Notes must be at most 500 characters.")

        subject = get_subject(settings)
        client, _ = _get_client_for_subject(subject, settings, store)
        iso_date = target_date.isoformat()
        workout_id = make_uid()

        def log_mutator(state: dict[str, Any]) -> dict[str, Any]:
            workouts = state.setdefault("workouts", [])
            # Idempotency check: skip append if workout_id already exists in document
            if any(isinstance(w, dict) and w.get("id") == workout_id for w in workouts):
                return state

            unit = str(state.get("unit") or "kg").lower()
            entries: list[dict[str, Any]] = []

            for ex in exercises:
                ex_id = ex.exercise_id
                raw_sets = ex.sets if isinstance(ex.sets, list) else []
                built_sets: list[dict[str, Any]] = []

                if raw_sets:
                    for s in raw_sets:
                        w_kg = float(s.weight_kg or 0.0)
                        if unit == "lb":
                            w_val = float((Decimal(str(w_kg)) / LB_TO_KG).quantize(Decimal("0.1")))
                        else:
                            w_val = float(Decimal(str(w_kg)).quantize(Decimal("0.1")))
                        reps_val = 0 if s.reps == "max" else int(s.reps)
                        rir = float(s.rir) if s.rir is not None else None
                        built_sets.append(
                            {
                                "w": w_val,
                                "r": reps_val,
                                "done": True,
                                "rir": rir,
                                "warm": s.warmup,
                            }
                        )
                else:
                    cnt = int(ex.sets) if isinstance(ex.sets, int) else 3
                    w_kg = float(ex.weight_kg or 0.0)
                    if unit == "lb":
                        w_val = float((Decimal(str(w_kg)) / LB_TO_KG).quantize(Decimal("0.1")))
                    else:
                        w_val = float(Decimal(str(w_kg)).quantize(Decimal("0.1")))
                    reps_val = int(ex.reps) if isinstance(ex.reps, int) else 10
                    for _ in range(cnt):
                        built_sets.append(
                            {
                                "w": w_val,
                                "r": reps_val,
                                "done": True,
                                "rir": None,
                                "warm": False,
                            }
                        )

                ex_entry: dict[str, Any] = {"id": ex_id, "sets": built_sets}
                note_val = ex.note or ex.notes
                if note_val:
                    ex_entry["note"] = note_val.strip()
                entries.append(ex_entry)

            workout_entry = {
                "id": workout_id,
                "d": iso_date,
                "entries": entries,
                "notes": notes.strip() if notes else None,
                "_ts": int(time.time() * 1000),
            }
            workouts.append(workout_entry)
            return state

        try:
            with client:
                client.mutate(log_mutator)
        except (OpenGymAuthError, OpenGymError) as exc:
            _raise_opengym_error(exc)

        return {
            "status": "logged",
            "workout_id": workout_id,
            "date": iso_date,
            "exercises_count": len(exercises),
        }
