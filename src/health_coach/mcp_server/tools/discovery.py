"""Group 1: context and discovery."""

import datetime as dt
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import text

from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import DATA_NOTE, READ, audited, jsonable, rnd, tabular, today

# One-line descriptions for get_schema. Views carry their own COMMENT in the database.
TABLE_DOCS: dict[str, str] = {
    "daily_activity": "Per day: steps, distance, active and zone minutes, calories out, floors.",
    "daily_vitals": "Per day: resting HR, HRV (RMSSD), SpO2, breathing rate, skin temp delta.",
    "heart_rate_samples": "Intraday heart rate (ts, bpm). Large: always aggregate by time.",
    "sleep_sessions": "Sleep sessions; local_date is the wake-up date, is_main=false for naps.",
    "sleep_stages": "Stage intervals per sleep session (deep, light, rem, awake).",
    "exercise_sessions": "Workouts from the watch or logged by hand (BJJ, climbing, cycling...).",
    "body_metrics": "Weight, body fat, waist readings with source; several per day possible.",
    "foods": "Personal food library with macros per 100 g.",
    "nutrition_entries": "Eaten items with macros copied at logging time; meal and confidence.",
    "checkins": "Subjective daily check-in: energy, soreness, stress, motivation 1-5.",
    "exercises": "openGym exercise catalogue cache with primary/secondary muscles.",
    "strength_sessions": "Gym sessions mirrored from openGym.",
    "strength_sets": "Sets of each strength session: reps, weight_kg, rir, warm-up flag.",
    "targets": "Versioned nutrition targets; current = latest effective_from <= today.",
    "goals": "Goals such as 'bench 100 kg x 5' with deadline and status.",
    "coach_log": "Coach memory: decisions, observations, plans, reviews, notes, questions.",
    "tdee_estimates": "Nightly adaptive TDEE estimates with confidence.",
    "sync_state": "Last sync per source and data type, errors.",
}

EXAMPLES: dict[str, list[str]] = {
    "v_daily": [
        "SELECT local_date, kcal_in, protein_g, weight_kg, sleep_min, resting_hr "
        "FROM v_daily WHERE local_date >= current_date - 13 ORDER BY local_date",
    ],
    "v_weight_trend": [
        "SELECT local_date, trend_kg, weekly_rate_kg FROM v_weight_trend "
        "ORDER BY local_date DESC LIMIT 14",
    ],
    "heart_rate_samples": [
        "SELECT date_trunc('hour', ts) AS hour, "
        "round(avg(bpm)) AS avg_bpm, max(bpm) FROM heart_rate_samples "
        "WHERE ts >= now() - interval '1 day' GROUP BY 1 ORDER BY 1",
    ],
    "strength_sets": [
        "SELECT s.local_date, x.name, ss.set_no, ss.reps, ss.weight_kg, ss.rir "
        "FROM strength_sets ss JOIN strength_sessions s ON s.id = ss.session_id "
        "JOIN exercises x ON x.id = ss.exercise_id "
        "WHERE x.name ILIKE '%bench%' ORDER BY s.local_date DESC, ss.set_no LIMIT 50",
    ],
    "v_exercise_e1rm": [
        "SELECT local_date, e1rm_kg FROM v_exercise_e1rm WHERE exercise ILIKE '%squat%' "
        "ORDER BY local_date",
    ],
}

_COLUMNS_SQL = """
SELECT c.table_name, c.column_name, c.data_type, c.udt_name,
       col_description(format('%I.%I', c.table_schema, c.table_name)::regclass,
                       c.ordinal_position) AS comment
FROM information_schema.columns c
WHERE c.table_schema = 'public' AND c.table_name <> 'alembic_version'
ORDER BY c.table_name, c.ordinal_position
"""

_RELATIONS_SQL = """
SELECT c.relname AS name,
       CASE c.relkind WHEN 'v' THEN 'view' ELSE 'table' END AS kind,
       obj_description(c.oid, 'pg_class') AS comment
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v')
  AND has_table_privilege(c.oid, 'SELECT') AND c.relname <> 'alembic_version'
ORDER BY kind DESC, c.relname
"""


def _type(row: Any) -> str:
    if row.data_type == "ARRAY":
        return str(row.udt_name).lstrip("_") + "[]"
    if row.data_type == "USER-DEFINED":
        return f"enum {row.udt_name}"
    return str(row.data_type).replace("timestamp with time zone", "timestamptz")


def get_schema(
    table: Annotated[str | None, Field(description="Table or view name for full detail.")] = None,
) -> dict[str, Any]:
    """List readable tables and views, or show one in detail with example queries.

    Start with the v_* views; they join and clean the raw tables. Timestamps are
    timestamptz; local_date columns are calendar days in the user's time zone, which
    is also the session TimeZone (so CURRENT_DATE is the user's today).
    """
    with get_engine(Role.ro).connect() as conn:
        relations = {r.name: r for r in conn.execute(text(_RELATIONS_SQL)).all()}
        columns = conn.execute(text(_COLUMNS_SQL)).all()

    def describe(name: str) -> str:
        return relations[name].comment or TABLE_DOCS.get(name, "")

    table_name = table
    if table_name is None:
        cols_by_rel: dict[str, list[str]] = {}
        for c in columns:
            if c.table_name in relations:
                cols_by_rel.setdefault(c.table_name, []).append(c.column_name)
        return {
            "relations": [
                {
                    "name": name,
                    "kind": rel.kind,
                    "description": describe(name),
                    "columns": cols_by_rel.get(name, []),
                }
                for name, rel in relations.items()
            ],
            "hint": "Call get_schema(table=...) for types, column notes and example queries.",
        }

    if table_name not in relations:
        raise ToolError(f"unknown or unreadable relation {table_name!r}")
    return {
        "name": table_name,
        "kind": relations[table_name].kind,
        "description": describe(table_name),
        "columns": [
            {"name": c.column_name, "type": _type(c), **({"note": c.comment} if c.comment else {})}
            for c in columns
            if c.table_name == table_name
        ],
        "examples": EXAMPLES.get(table_name, []),
    }


_COVERAGE = {
    "activity": ("daily_activity", "local_date", ""),
    "vitals": ("daily_vitals", "local_date", ""),
    "heart_rate": ("heart_rate_samples", "(ts AT TIME ZONE current_setting('TimeZone'))::date", ""),
    "sleep": ("sleep_sessions", "local_date", ""),
    "exercise": ("exercise_sessions", "local_date", "deleted_at IS NULL"),
    "weight": ("body_metrics", "local_date", "deleted_at IS NULL AND weight_kg IS NOT NULL"),
    "nutrition": ("nutrition_entries", "local_date", "deleted_at IS NULL"),
    "checkins": ("checkins", "local_date", ""),
    "strength": ("strength_sessions", "local_date", ""),
}


def get_data_coverage() -> dict[str, Any]:
    """Per data type: first and last date, days with data in the last 30 days, plus
    the sync status per source. Use it to judge how much to trust an analysis."""
    since = today() - dt.timedelta(days=29)
    rows = []
    with get_engine(Role.ro).connect() as conn:
        for name, (tbl, day_expr, where) in _COVERAGE.items():
            cond = f"WHERE {where}" if where else ""
            # Identifiers come from the constant above, never from input.
            r = conn.execute(
                text(
                    f"SELECT min({day_expr}) AS first, max({day_expr}) AS last, "  # noqa: S608
                    f"count(DISTINCT {day_expr}) FILTER (WHERE {day_expr} >= :since) AS days_30 "
                    f"FROM {tbl} {cond}"
                ),
                {"since": since},
            ).one()
            rows.append({"data_type": name, "first": r.first, "last": r.last, "days_30": r.days_30})
        sync = conn.execute(
            text(
                "SELECT source, data_type, last_success_at, last_error, error_count "
                "FROM sync_state ORDER BY source, data_type"
            )
        ).all()
        warnings = quality.sync_warnings(conn)
    return {
        "coverage": tabular(rows),
        "sync": tabular(sync),
        "warnings": warnings,
    }


SNAPSHOT_DAILY_COLUMNS = [
    "local_date",
    "kcal_in",
    "protein_g",
    "weight_kg",
    "steps",
    "sleep_min",
    "resting_hr",
    "hrv_rmssd_ms",
    "hard_sets",
    "exercise_min",
    "exercise_types",
    "energy",
    "soreness",
]


def current_targets(conn: Any, day: dt.date) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT effective_from, phase, kcal, protein_g, protein_max_g, carbs_g, fat_g, steps, "
            "weekly_rate_min_kg, weekly_rate_max_kg, reason FROM targets "
            "WHERE effective_from <= :d ORDER BY effective_from DESC, id DESC LIMIT 1"
        ),
        {"d": day},
    ).first()
    return {k: jsonable(v) for k, v in row._mapping.items()} if row else None


def weight_status(conn: Any, targets: dict[str, Any] | None) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT local_date, weight_kg, avg_7d_kg, trend_kg, weekly_rate_kg "
            "FROM v_weight_trend ORDER BY local_date DESC LIMIT 1"
        )
    ).first()
    if row is None:
        return None
    status: dict[str, Any] = {
        "last_weigh_in": jsonable(row.local_date),
        "weight_kg": rnd(row.weight_kg, 0.1),
        "avg_7d_kg": rnd(row.avg_7d_kg, 0.1),
        "trend_kg": rnd(row.trend_kg, 0.1),
        "weekly_rate_kg": jsonable(row.weekly_rate_kg),
    }
    lo = targets.get("weekly_rate_min_kg") if targets else None
    hi = targets.get("weekly_rate_max_kg") if targets else None
    if row.weekly_rate_kg is not None and lo is not None and hi is not None:
        rate = float(row.weekly_rate_kg)
        status["rate_vs_target"] = "below" if rate < lo else "above" if rate > hi else "in band"
    return status


def get_context_snapshot() -> dict[str, Any]:
    """Start every conversation with this. Compact overview: current phase and targets,
    last 7 days, weight trend, latest TDEE estimate, recovery, recent coach log, open
    goals and data-quality warnings."""
    day = today()
    with get_engine(Role.ro).connect() as conn:
        targets = current_targets(conn, day)
        daily = conn.execute(
            text(
                f"SELECT {', '.join(SNAPSHOT_DAILY_COLUMNS)} FROM v_daily "  # noqa: S608
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": day - dt.timedelta(days=6), "e": day},
        ).all()
        tdee = conn.execute(
            text(
                "SELECT local_date, window_days, tdee, avg_intake, confidence FROM tdee_estimates "
                "ORDER BY local_date DESC, window_days LIMIT 1"
            )
        ).first()
        from health_coach.mcp_server.tools.analytics import get_recovery_snapshot

        recovery = get_recovery_snapshot(conn, day)
        log = conn.execute(
            text(
                "SELECT id, ts, kind, title, left(body, 300) AS body, tags FROM coach_log "
                "ORDER BY ts DESC LIMIT 5"
            )
        ).all()
        goals = conn.execute(
            text(
                "SELECT id, name, metric, target_value, deadline FROM goals "
                "WHERE status = 'open' ORDER BY deadline NULLS LAST"
            )
        ).all()
        snapshot = {
            "today": day.isoformat(),
            "targets": targets,
            "weight": weight_status(conn, targets),
            "last_7_days": tabular(daily, SNAPSHOT_DAILY_COLUMNS),
            "tdee": {k: jsonable(v) for k, v in tdee._mapping.items()} if tdee else None,
            "recovery_today": recovery,
            "coach_log_recent": tabular(log),
            "open_goals": tabular(goals),
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
            "note": DATA_NOTE,
        }
    if targets is None:
        snapshot["warnings"].append("no targets set yet: use set_targets")
    return snapshot


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(get_context_snapshot))
    server.tool(annotations=READ)(audited(get_schema))
    server.tool(annotations=READ)(audited(get_data_coverage))
