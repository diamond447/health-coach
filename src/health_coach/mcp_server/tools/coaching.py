"""Group 6: coaching state (targets, coach log, goals)."""

import datetime as dt
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import text

from health_coach.db.engine import Role, get_engine
from health_coach.db.models import CoachLogKind, GoalStatus, Phase
from health_coach.mcp_server.common import (
    DATA_NOTE,
    READ,
    UPSERT,
    WRITE,
    audited,
    jsonable,
    tabular,
    today,
)
from health_coach.mcp_server.tools.discovery import current_targets

COACH_LOG_COLUMNS = ["id", "ts", "kind", "title", "body", "tags", "related_from", "related_to"]


def get_targets(
    date: Annotated[
        dt.date | None,
        Field(description="Date to look up targets for (YYYY-MM-DD); defaults to today"),
    ] = None,
) -> dict[str, Any]:
    """Retrieve active nutrition and activity targets for a date and the full target history."""
    d = date or today()
    with get_engine(Role.ro).connect() as conn:
        current = current_targets(conn, d)
        rows = conn.execute(
            text(
                "SELECT id, effective_from, phase, kcal, protein_g, protein_max_g, carbs_g, fat_g, "
                "steps, weekly_rate_min_kg, weekly_rate_max_kg, reason, created_at "
                "FROM targets ORDER BY effective_from DESC, id DESC"
            )
        ).all()
        return {
            "current": current,
            "history": tabular(rows),
        }


def set_targets(
    effective_from: Annotated[
        dt.date, Field(description="Date from which these targets apply (YYYY-MM-DD)")
    ],
    phase: Annotated[Phase, Field(description="Phase: bulk, cut, maintenance, or deload")],
    kcal: Annotated[int, Field(ge=500, le=10000, description="Daily kcal target")],
    protein_g: Annotated[
        int, Field(ge=0, le=500, description="Daily protein target in grams (minimum)")
    ],
    reason: Annotated[str, Field(description="Coaching rationale for this target update")],
    protein_max_g: Annotated[
        int | None, Field(ge=0, le=500, description="Optional protein ceiling in grams")
    ] = None,
    carbs_g: Annotated[
        int | None, Field(ge=0, le=1000, description="Daily carbohydrate target in grams")
    ] = None,
    fat_g: Annotated[
        int | None, Field(ge=0, le=500, description="Daily fat target in grams")
    ] = None,
    steps: Annotated[
        int | None, Field(ge=0, le=100000, description="Daily step count target")
    ] = None,
    weekly_rate_min_kg: Annotated[
        float | None,
        Field(ge=-2.0, le=2.0, description="Minimum wanted weekly weight rate change in kg"),
    ] = None,
    weekly_rate_max_kg: Annotated[
        float | None,
        Field(ge=-2.0, le=2.0, description="Maximum wanted weekly weight rate change in kg"),
    ] = None,
) -> dict[str, Any]:
    """Set a new version of nutrition and activity targets.

    Also records a decision entry in the coach log with the rationale and diff against
    the previous targets in the same transaction.
    """
    if not reason.strip():
        raise ToolError("reason cannot be empty")
    if protein_max_g is not None and protein_max_g < protein_g:
        raise ToolError("protein_max_g cannot be less than protein_g")
    if (
        weekly_rate_min_kg is not None
        and weekly_rate_max_kg is not None
        and weekly_rate_min_kg > weekly_rate_max_kg
    ):
        raise ToolError("weekly_rate_min_kg cannot be greater than weekly_rate_max_kg")

    phase_val = phase.value if hasattr(phase, "value") else str(phase)

    with get_engine(Role.rw).begin() as conn:
        prev = conn.execute(
            text(
                "SELECT phase, kcal, protein_g, protein_max_g, carbs_g, fat_g, steps, "
                "weekly_rate_min_kg, weekly_rate_max_kg FROM targets "
                "ORDER BY effective_from DESC, id DESC LIMIT 1"
            )
        ).first()

        new_vals: list[tuple[str, Any]] = [
            ("phase", phase_val),
            ("kcal", kcal),
            ("protein_g", protein_g),
            ("protein_max_g", protein_max_g),
            ("carbs_g", carbs_g),
            ("fat_g", fat_g),
            ("steps", steps),
            ("weekly_rate_min_kg", weekly_rate_min_kg),
            ("weekly_rate_max_kg", weekly_rate_max_kg),
        ]

        if prev is not None:
            changes = []
            for field, val in new_vals:
                old_val = getattr(prev, field)
                if old_val is not None and hasattr(old_val, "value"):
                    old_val = old_val.value
                elif old_val is not None and field in ("weekly_rate_min_kg", "weekly_rate_max_kg"):
                    old_val = float(old_val)
                if old_val != val:
                    changes.append(f"{field}: {old_val} -> {val}")
            changes_str = (
                "\n".join(f"- {c}" for c in changes)
                if changes
                else "No numeric changes vs previous"
            )
            log_body = f"{reason.strip()}\n\nChanged values vs previous version:\n{changes_str}"
        else:
            log_body = f"{reason.strip()}\n\nInitial targets set."

        log_title = f"Targets from {effective_from}: {phase_val} {kcal} kcal"

        target_row = conn.execute(
            text(
                "INSERT INTO targets (effective_from, phase, kcal, protein_g, protein_max_g, "
                "carbs_g, fat_g, steps, weekly_rate_min_kg, weekly_rate_max_kg, reason, source) "
                "VALUES (:d, :phase, :kcal, :protein_g, :protein_max_g, :carbs_g, :fat_g, "
                ":steps, :rate_min, :rate_max, :reason, 'chat') RETURNING id"
            ),
            {
                "d": effective_from,
                "phase": phase_val,
                "kcal": kcal,
                "protein_g": protein_g,
                "protein_max_g": protein_max_g,
                "carbs_g": carbs_g,
                "fat_g": fat_g,
                "steps": steps,
                "rate_min": weekly_rate_min_kg,
                "rate_max": weekly_rate_max_kg,
                "reason": reason.strip(),
            },
        ).one()

        log_row = conn.execute(
            text(
                "INSERT INTO coach_log (kind, title, body, tags, related_from, source) "
                "VALUES ('decision', :title, :body, ARRAY['targets']::text[], :related_from, "
                "'chat') RETURNING id"
            ),
            {
                "title": log_title,
                "body": log_body,
                "related_from": effective_from,
            },
        ).one()

    return {"target_id": target_row.id, "coach_log_id": log_row.id}


def read_coach_log(
    kind: Annotated[
        CoachLogKind | None,
        Field(description="Filter by kind: decision, observation, plan, review, note, question"),
    ] = None,
    tag: Annotated[str | None, Field(description="Filter by tag (exact match)")] = None,
    search: Annotated[
        str | None, Field(description="Search text in title and body (case-insensitive)")
    ] = None,
    since: Annotated[
        dt.date | None, Field(description="Return entries created on or after date")
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Max entries to return (default 20, max 100)")
    ] = 20,
) -> dict[str, Any]:
    """Read entries from the coach's persistent memory (newest first).

    Claude should check recent entries at the start of conversations and when
    re-evaluating past decisions.
    """
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit}

    if kind is not None:
        clauses.append("kind = :kind")
        params["kind"] = kind.value if hasattr(kind, "value") else str(kind)
    if tag is not None:
        clauses.append(":tag = ANY(tags)")
        params["tag"] = tag
    if search is not None:
        clauses.append("(title ILIKE :search OR body ILIKE :search)")
        params["search"] = f"%{search}%"
    if since is not None:
        clauses.append("(ts AT TIME ZONE current_setting('TimeZone'))::date >= :since")
        params["since"] = since

    where = " AND ".join(clauses)
    query = text(
        f"SELECT {', '.join(COACH_LOG_COLUMNS)} FROM coach_log "  # noqa: S608
        f"WHERE {where} ORDER BY ts DESC, id DESC LIMIT :limit"
    )

    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(query, params).all()
        return {
            **tabular(rows, COACH_LOG_COLUMNS),
            "note": DATA_NOTE,
        }


def write_coach_log(
    kind: Annotated[
        CoachLogKind,
        Field(description="Kind: decision, observation, plan, review, note, or question"),
    ],
    title: Annotated[str, Field(description="Short summary title")],
    body: Annotated[str, Field(description="Detailed notes or rationale")],
    tags: Annotated[list[str] | None, Field(description="Tags for categorization")] = None,
    related_from: Annotated[
        dt.date | None, Field(description="Start date of the observation/plan range")
    ] = None,
    related_to: Annotated[
        dt.date | None, Field(description="End date of the observation/plan range")
    ] = None,
) -> dict[str, Any]:
    """Write an entry to Claude's long-term coach memory."""
    if not title.strip():
        raise ToolError("title cannot be empty")
    if not body.strip():
        raise ToolError("body cannot be empty")

    kind_val = kind.value if hasattr(kind, "value") else str(kind)
    tags_list = tags or []

    with get_engine(Role.rw).begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO coach_log (kind, title, body, tags, related_from, related_to, source) "
                "VALUES (:kind, :title, :body, :tags, :rf, :rt, 'chat') RETURNING id"
            ),
            {
                "kind": kind_val,
                "title": title.strip(),
                "body": body.strip(),
                "tags": tags_list,
                "rf": related_from,
                "rt": related_to,
            },
        ).one()
    return {"id": row.id}


def manage_goal(
    action: Annotated[
        Literal["create", "update", "close"],
        Field(description="Action to perform: create, update, or close"),
    ],
    goal_id: Annotated[int | None, Field(description="Goal ID (required for update/close)")] = None,
    name: Annotated[str | None, Field(description="Goal name, e.g. 'Bench 100 kg x 5'")] = None,
    metric: Annotated[str | None, Field(description="Metric tracked, e.g. 'e1rm_kg'")] = None,
    target_value: Annotated[float | None, Field(description="Target numerical value")] = None,
    deadline: Annotated[dt.date | None, Field(description="Deadline date (YYYY-MM-DD)")] = None,
    status: Annotated[
        GoalStatus | None, Field(description="Goal status: open, achieved, abandoned")
    ] = None,
    notes: Annotated[str | None, Field(description="Optional notes or reflection")] = None,
) -> dict[str, Any]:
    """Create, update, or close a fitness or nutrition goal."""
    with get_engine(Role.rw).begin() as conn:
        if action == "create":
            if not name or not name.strip():
                raise ToolError("name is required to create a goal")
            if not metric or not metric.strip():
                raise ToolError("metric is required to create a goal")
            st = (status or GoalStatus.open).value
            row = conn.execute(
                text(
                    "INSERT INTO goals (name, metric, target_value, deadline, status, notes, "
                    "source) VALUES (:name, :metric, :tv, :deadline, :status, :notes, 'chat') "
                    "RETURNING id, name, metric, target_value, deadline, status, notes, closed_at"
                ),
                {
                    "name": name.strip(),
                    "metric": metric.strip(),
                    "tv": target_value,
                    "deadline": deadline,
                    "status": st,
                    "notes": notes,
                },
            ).one()
            return {k: jsonable(v) for k, v in row._mapping.items()}

        if goal_id is None:
            raise ToolError(f"goal_id is required to {action} a goal")

        existing = conn.execute(
            text("SELECT id, status, closed_at FROM goals WHERE id = :id"), {"id": goal_id}
        ).first()
        if existing is None:
            raise ToolError(f"goal {goal_id} not found")

        if action == "update":
            st_val = status.value if status is not None else None
            row = conn.execute(
                text(
                    "UPDATE goals SET "
                    "name = COALESCE(:name, name), "
                    "metric = COALESCE(:metric, metric), "
                    "target_value = COALESCE(:tv, target_value), "
                    "deadline = COALESCE(:deadline, deadline), "
                    "status = COALESCE(:status, status), "
                    "notes = COALESCE(:notes, notes), "
                    "closed_at = CASE "
                    "  WHEN :status IN ('achieved', 'abandoned') AND closed_at IS NULL THEN now() "
                    "  WHEN :status = 'open' THEN NULL "
                    "  ELSE closed_at "
                    "END, "
                    "updated_at = now() "
                    "WHERE id = :id "
                    "RETURNING id, name, metric, target_value, deadline, status, notes, closed_at"
                ),
                {
                    "id": goal_id,
                    "name": name.strip() if name is not None else None,
                    "metric": metric.strip() if metric is not None else None,
                    "tv": target_value,
                    "deadline": deadline,
                    "status": st_val,
                    "notes": notes,
                },
            ).one()
            return {k: jsonable(v) for k, v in row._mapping.items()}

        if action == "close":
            close_status = status or GoalStatus.achieved
            if close_status not in (GoalStatus.achieved, GoalStatus.abandoned):
                raise ToolError("close status must be achieved or abandoned")
            row = conn.execute(
                text(
                    "UPDATE goals SET "
                    "status = :status, "
                    "closed_at = now(), "
                    "notes = COALESCE(:notes, notes), "
                    "updated_at = now() "
                    "WHERE id = :id "
                    "RETURNING id, name, metric, target_value, deadline, status, notes, closed_at"
                ),
                {
                    "id": goal_id,
                    "status": close_status.value,
                    "notes": notes,
                },
            ).one()
            return {k: jsonable(v) for k, v in row._mapping.items()}

        raise ToolError(f"unknown action {action!r}")


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(get_targets))
    server.tool(annotations=WRITE)(audited(set_targets))
    server.tool(annotations=READ)(audited(read_coach_log))
    server.tool(annotations=WRITE)(audited(write_coach_log))
    server.tool(annotations=UPSERT)(audited(manage_goal))
