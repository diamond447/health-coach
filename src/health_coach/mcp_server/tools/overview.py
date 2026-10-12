"""Group 3 (first part): daily overview, weekly summary, weight trend."""

import datetime as dt
import re
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import Connection, text

from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import (
    READ,
    audited,
    date_range,
    jsonable,
    rnd,
    tabular,
    today,
)
from health_coach.mcp_server.tools.discovery import current_targets

DateArg = Annotated[dt.date | None, Field(description="YYYY-MM-DD, local date")]

DAILY_COLUMNS = [
    "local_date",
    "steps",
    "active_zone_minutes",
    "calories_out",
    "resting_hr",
    "hrv_rmssd_ms",
    "sleep_min",
    "sleep_efficiency",
    "sleep_score",
    "kcal_in",
    "target_kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "nutrition_entries",
    "weight_kg",
    "energy",
    "soreness",
    "stress",
    "motivation",
    "strength_sessions",
    "hard_sets",
    "tonnage_kg",
    "exercise_min",
    "exercise_types",
]


def get_daily_overview(start: DateArg = None, end: DateArg = None) -> dict[str, Any]:
    """One row per day (default: last 7 days): activity, vitals, sleep, intake vs target,
    weight, check-in and training. Empty cells mean no data for that day."""
    s, e = date_range(start, end)
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT {', '.join(DAILY_COLUMNS)} FROM v_daily "  # noqa: S608
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": s, "e": e},
        ).all()
        return {
            **tabular(rows, DAILY_COLUMNS),
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


def get_weight_trend(
    days: Annotated[int, Field(ge=7, le=400, description="How many days back")] = 56,
) -> dict[str, Any]:
    """Daily weigh-ins with 7-day average, smoothed trend, weekly rate of change and how
    the current rate compares with the target band of the current phase."""
    since = today() - dt.timedelta(days=days - 1)
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT local_date, weight_kg, avg_7d_kg, trend_kg, weekly_rate_kg "
                "FROM v_weight_trend WHERE local_date >= :since ORDER BY local_date"
            ),
            {"since": since},
        ).all()
        targets = current_targets(conn, today())
        result: dict[str, Any] = tabular(rows)
        latest = rows[-1] if rows else None
        result["current"] = {
            "trend_kg": rnd(latest.trend_kg, 0.1) if latest else None,
            "weekly_rate_kg": jsonable(latest.weekly_rate_kg) if latest else None,
            "target_band_kg": (
                [targets.get("weekly_rate_min_kg"), targets.get("weekly_rate_max_kg")]
                if targets
                else None
            ),
            "phase": targets.get("phase") if targets else None,
        }
        result["as_of"] = quality.as_of(conn)
        result["warnings"] = quality.logging_warnings(conn)
    return result


_ISO_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def _week_bounds(iso_week: str | None) -> tuple[dt.date, dt.date, str]:
    if iso_week is None:
        last_monday = today() - dt.timedelta(days=today().weekday() + 7)
        start = last_monday
    else:
        m = _ISO_WEEK.match(iso_week)
        if not m:
            raise ToolError("iso_week must look like 2026-W41")
        start = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    year, week, _ = start.isocalendar()
    return start, start + dt.timedelta(days=6), f"{year}-W{week:02d}"


_WEEK_AGG = """
SELECT count(*) FILTER (WHERE kcal_in IS NOT NULL) AS days_logged,
       round(avg(kcal_in)) AS kcal_avg,
       round(avg(protein_g)) AS protein_avg_g,
       round(avg(steps)) AS steps_avg,
       round(avg(sleep_min)) AS sleep_avg_min,
       round(avg(resting_hr)) AS resting_hr_avg,
       round(avg(hrv_rmssd_ms), 1) AS hrv_avg_ms,
       sum(strength_sessions) AS strength_sessions,
       sum(hard_sets) AS hard_sets,
       sum(exercise_min) AS exercise_min,
       count(*) FILTER (WHERE kcal_in BETWEEN target_kcal * 0.9 AND target_kcal * 1.1)
           AS days_kcal_on_target,
       count(*) FILTER (WHERE protein_g >= target_protein_g) AS days_protein_on_target,
       round(avg(energy), 1) AS energy_avg,
       round(avg(soreness), 1) AS soreness_avg
FROM v_daily WHERE local_date BETWEEN :s AND :e
"""


def _week_stats(conn: Connection, start: dt.date, end: dt.date) -> dict[str, Any]:
    agg = dict(conn.execute(text(_WEEK_AGG), {"s": start, "e": end}).one()._mapping)
    trend = conn.execute(
        text(
            "SELECT (SELECT trend_kg FROM v_weight_trend WHERE local_date <= :e "
            "        ORDER BY local_date DESC LIMIT 1) AS end_trend, "
            "       (SELECT trend_kg FROM v_weight_trend WHERE local_date < :s "
            "        ORDER BY local_date DESC LIMIT 1) AS start_trend, "
            "       (SELECT count(*) FROM v_weight_trend WHERE local_date BETWEEN :s AND :e) "
            "        AS weigh_ins"
        ),
        {"s": start, "e": end},
    ).one()
    agg["weigh_ins"] = trend.weigh_ins
    agg["weight_change_kg"] = (
        rnd(trend.end_trend - trend.start_trend, 0.01)
        if trend.end_trend is not None and trend.start_trend is not None
        else None
    )
    agg["kcal_avg"] = rnd(agg["kcal_avg"], 10)
    return {k: jsonable(v) for k, v in agg.items()}


def get_weekly_summary(
    iso_week: Annotated[
        str | None, Field(description="ISO week like 2026-W41; default last full week")
    ] = None,
) -> dict[str, Any]:
    """Averages and totals of one ISO week vs targets and vs the previous week: intake,
    protein, weight trend change, sleep, resting HR, HRV, steps, hard sets per muscle,
    other sports minutes, adherence and new e1RM records."""
    start, end, label = _week_bounds(iso_week)
    prev_start, prev_end = start - dt.timedelta(days=7), start - dt.timedelta(days=1)
    with get_engine(Role.ro).connect() as conn:
        week = _week_stats(conn, start, end)
        prev = _week_stats(conn, prev_start, prev_end)
        delta = {
            k: round(week[k] - prev[k], 2)
            for k in week
            if isinstance(week[k], int | float) and isinstance(prev[k], int | float)
        }
        muscles = conn.execute(
            text(
                "SELECT muscle, hard_sets FROM v_strength_volume_weekly "
                "WHERE week_start = :s ORDER BY hard_sets DESC"
            ),
            {"s": start},
        ).all()
        sports = conn.execute(
            text(
                "SELECT activity_type, count(*) AS sessions, sum(duration_min) AS minutes "
                "FROM exercise_sessions WHERE deleted_at IS NULL "
                "AND local_date BETWEEN :s AND :e GROUP BY 1 ORDER BY 3 DESC"
            ),
            {"s": start, "e": end},
        ).all()
        records = conn.execute(
            text(
                "SELECT w.exercise, w.local_date, w.weight_kg, w.reps, w.e1rm_kg, "
                "       prev.best AS previous_best_kg "
                "FROM v_exercise_e1rm w "
                "JOIN LATERAL (SELECT max(e1rm_kg) AS best FROM v_exercise_e1rm p "
                "              WHERE p.exercise_id = w.exercise_id AND p.local_date < :s) prev "
                "  ON true "
                "WHERE w.local_date BETWEEN :s AND :e AND w.e1rm_kg > prev.best "
                "ORDER BY w.e1rm_kg - prev.best DESC"
            ),
            {"s": start, "e": end},
        ).all()
        targets = current_targets(conn, end)
        warnings = quality.logging_warnings(conn, end)
    return {
        "iso_week": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "targets": targets,
        "week": week,
        "previous_week": prev,
        "delta": delta,
        "hard_sets_per_muscle": tabular(muscles),
        "other_sports": tabular(sports),
        "e1rm_records": tabular(records),
        "warnings": warnings,
    }


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(get_daily_overview))
    server.tool(annotations=READ)(audited(get_weekly_summary))
    server.tool(annotations=READ)(audited(get_weight_trend))
