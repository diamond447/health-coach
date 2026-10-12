"""Data freshness and completeness checks shared by tools (the `warnings` field)."""

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.mcp_server.common import jsonable, today

STALE_AFTER = dt.timedelta(hours=24)
INTERNAL_SOURCE = "worker"
MIN_LOGGED_DAYS_PER_WEEK = 5

_AS_OF_SQL = """
SELECT greatest(
    (SELECT max(updated_at) FROM daily_activity),
    (SELECT max(updated_at) FROM daily_vitals),
    (SELECT max(updated_at) FROM sleep_sessions),
    (SELECT max(updated_at) FROM exercise_sessions),
    (SELECT max(updated_at) FROM body_metrics),
    (SELECT max(updated_at) FROM nutrition_entries),
    (SELECT max(updated_at) FROM checkins),
    (SELECT max(updated_at) FROM strength_sessions)
)
"""


def as_of(conn: Connection) -> Any:
    """Timestamp of the latest data change, for the `as_of` field."""
    return jsonable(conn.execute(text(_AS_OF_SQL)).scalar())


def sync_warnings(conn: Connection) -> list[str]:
    warnings = []
    rows = conn.execute(
        text("SELECT source, data_type, last_success_at, last_error, error_count FROM sync_state")
    ).all()
    if not rows:
        warnings.append("no sync has run yet: wearable and openGym data may be missing")
    now = dt.datetime.now(dt.UTC)
    stale_sources: dict[str, dt.datetime | None] = {}
    for r in rows:
        if r.error_count >= 3:
            warnings.append(f"{r.source}/{r.data_type} failing ({r.error_count}x): {r.last_error}")
        # Internal jobs (source "worker") and backfill progress are not data sources.
        if r.source == INTERNAL_SOURCE or r.data_type.endswith(":backfill"):
            continue
        last = stale_sources.get(r.source)
        if r.last_success_at and (last is None or r.last_success_at > last):
            stale_sources[r.source] = r.last_success_at
        else:
            stale_sources.setdefault(r.source, None)
    for source, last in stale_sources.items():
        if last is None or now - last > STALE_AFTER:
            when = jsonable(last) if last else "never"
            warnings.append(f"{source} data is stale (last successful sync: {when})")
    return warnings


def logging_warnings(conn: Connection, end: dt.date | None = None) -> list[str]:
    end = end or today()
    start = end - dt.timedelta(days=6)
    logged = conn.execute(
        text(
            "SELECT count(DISTINCT local_date) FROM nutrition_entries "
            "WHERE deleted_at IS NULL AND local_date BETWEEN :s AND :e"
        ),
        {"s": start, "e": end},
    ).scalar_one()
    weigh_ins = conn.execute(
        text(
            "SELECT count(*) FROM v_body_daily "
            "WHERE weight_kg IS NOT NULL AND local_date BETWEEN :s AND :e"
        ),
        {"s": start, "e": end},
    ).scalar_one()
    warnings = []
    if logged < MIN_LOGGED_DAYS_PER_WEEK:
        warnings.append(
            f"nutrition logged on {logged} of the last 7 days: "
            "intake totals and TDEE are unreliable"
        )
    if weigh_ins < 3:
        warnings.append(f"only {weigh_ins} weigh-ins in the last 7 days: weight trend is uncertain")
    return warnings


def all_warnings(conn: Connection) -> list[str]:
    return sync_warnings(conn) + logging_warnings(conn)
