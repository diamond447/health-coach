"""Group: habit/behaviour journaling and sleep settings."""

import datetime as dt
import json
import re
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import text

from health_coach.analytics.journal import compute_journal_insights
from health_coach.config import get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server.common import (
    DESTRUCTIVE,
    READ,
    UPSERT,
    audited,
    date_range,
    jsonable,
    today,
)

KNOWN_BEHAVIORS: tuple[tuple[str, str], ...] = (
    ("alcohol", "Standard drinks consumed (amount = standard drinks)"),
    ("caffeine_late", "Caffeine consumed after 14:00"),
    ("late_meal", "Meal consumed less than 2 hours before bed"),
    ("screen_in_bed", "Screen use while in bed"),
    ("sauna", "Sauna session"),
    ("cold_exposure", "Cold shower, plunge or ice bath"),
    ("stretching", "Stretching or mobility work"),
    ("meditation", "Meditation or breathwork"),
    ("reading", "Reading before sleep"),
    ("nap", "Daytime nap"),
    ("high_stress", "Unusually high stress day"),
    ("illness", "Acute illness, cold, or infection"),
    ("travel", "Travel or significant time zone shift"),
    ("sex", "Sexual activity"),
    ("magnesium", "Magnesium supplement before bed"),
)

BEHAVIOR_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
ALARM_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")


class JournalEntryItem(BaseModel):
    behavior: Annotated[
        str,
        Field(
            description=(
                "Behavior key in snake_case (e.g. alcohol, sauna, magnesium). "
                "Must match ^[a-z][a-z0-9_]{1,39}$."
            )
        ),
    ]
    amount: Annotated[
        float | Decimal | None,
        Field(
            default=None,
            ge=0,
            le=9999.99,
            description="Optional amount (e.g. standard drinks, cups).",
        ),
    ] = None
    note: Annotated[str | None, Field(default=None, description="Optional note or context.")] = None


def log_journal(
    entries: Annotated[
        list[JournalEntryItem],
        Field(
            description=(
                "List of behavior entries: [{behavior, amount?, note?}]. Known behaviors: "
                + ", ".join(f"{k} ({desc})" for k, desc in KNOWN_BEHAVIORS)
                + ". Other snake_case keys matching ^[a-z][a-z0-9_]{1,39}$ are allowed."
            )
        ),
    ],
    date: Annotated[
        dt.date | None,
        Field(
            description=(
                "Date the behaviour happened (YYYY-MM-DD, local date); "
                "defaults to yesterday (the evening before the night it may affect)."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Log or update evening behaviours and habits for a given date.

    Upserts per (local_date, behavior); date defaults to yesterday because people log the evening
    before. Returns all active entries for the day.
    """
    if not entries:
        raise ToolError("entries list cannot be empty")

    validated_items: list[tuple[str, Decimal | None, str | None]] = []
    for e in entries:
        b = e.behavior.strip()
        if not BEHAVIOR_RE.match(b):
            raise ToolError(f"invalid behavior key {b!r}: must match ^[a-z][a-z0-9_]{{1,39}}$")
        amt = Decimal(str(e.amount)) if e.amount is not None else None
        n = e.note.strip() if e.note else None
        validated_items.append((b, amt, n))

    target_date = date or (today() - dt.timedelta(days=1))

    with get_engine(Role.rw).begin() as conn:
        for b, amt, n in validated_items:
            conn.execute(
                text(
                    "INSERT INTO journal_entries (local_date, behavior, amount, note, source) "
                    "VALUES (:ld, :b, :amt, :note, 'chat') "
                    "ON CONFLICT (local_date, behavior) WHERE deleted_at IS NULL DO UPDATE SET "
                    "amount = EXCLUDED.amount, "
                    "note = EXCLUDED.note, "
                    "updated_at = now()"
                ),
                {"ld": target_date, "b": b, "amt": amt, "note": n},
            )

        rows = conn.execute(
            text(
                "SELECT id, local_date, behavior, amount, note, source, created_at, updated_at "
                "FROM journal_entries "
                "WHERE local_date = :ld AND deleted_at IS NULL "
                "ORDER BY id"
            ),
            {"ld": target_date},
        ).all()

    return {
        "local_date": jsonable(target_date),
        "entries": [{k: jsonable(v) for k, v in r._mapping.items()} for r in rows],
    }


def get_journal(
    start: Annotated[
        dt.date | None,
        Field(description="Start date (YYYY-MM-DD); defaults to 14 days ago"),
    ] = None,
    end: Annotated[
        dt.date | None,
        Field(description="End date (YYYY-MM-DD); defaults to today"),
    ] = None,
) -> dict[str, Any]:
    """Retrieve logged journal entries for a date range (defaults to the last 14 days)."""
    s, e = date_range(start, end, default_days=14)
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, local_date, behavior, amount, note, source, created_at, updated_at "
                "FROM journal_entries "
                "WHERE local_date BETWEEN :s AND :e AND deleted_at IS NULL "
                "ORDER BY local_date, id"
            ),
            {"s": s, "e": e},
        ).all()
    return {
        "start": jsonable(s),
        "end": jsonable(e),
        "entries": [{k: jsonable(v) for k, v in r._mapping.items()} for r in rows],
    }


def delete_journal_entry(
    entry_id: Annotated[int, Field(description="ID of the journal entry to delete")],
) -> dict[str, Any]:
    """Soft delete a journal entry by ID."""
    with get_engine(Role.rw).begin() as conn:
        res = conn.execute(
            text(
                "UPDATE journal_entries SET deleted_at = now(), updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL RETURNING id"
            ),
            {"id": entry_id},
        ).first()
        if res is None:
            raise ToolError(f"journal entry {entry_id} not found")
    return {"deleted": True, "id": entry_id}


def get_journal_insights(
    days: Annotated[
        int,
        Field(
            ge=7,
            le=365,
            description="Lookback window in days (defaults to 60 days).",
        ),
    ] = 60,
) -> dict[str, Any]:
    """Analyze the observed relationship between evening behaviours and next-day recovery.

    For each behaviour, computes mean recovery on the day AFTER the behaviour day
    with vs without it, difference in percentage points, and counts. Only behaviours
    with >= 5 days with and >= 5 days without are reported; others are listed under
    insufficient with their counts. Unlogged days do not count as 'without'.
    """
    current_today = today()
    start_date = current_today - dt.timedelta(days=days)

    with get_engine(Role.ro).connect() as conn:
        entry_rows = conn.execute(
            text(
                "SELECT local_date, behavior FROM journal_entries "
                "WHERE local_date >= :s AND local_date < :today AND deleted_at IS NULL "
                "ORDER BY local_date"
            ),
            {"s": start_date, "today": current_today},
        ).all()
        score_rows = conn.execute(
            text(
                "SELECT local_date, recovery FROM daily_scores "
                "WHERE local_date > :s AND local_date <= :today AND recovery IS NOT NULL"
            ),
            {"s": start_date, "today": current_today},
        ).all()

    recovery_by_date = {r.local_date: r.recovery for r in score_rows}
    res = compute_journal_insights(entry_rows, recovery_by_date)
    data = res.to_dict()

    return {
        "days": days,
        "start": jsonable(start_date),
        "end": jsonable(current_today - dt.timedelta(days=1)),
        "logged_days": len(set(r.local_date for r in entry_rows)),
        "insights": data["insights"],
        "insufficient": data["insufficient"],
    }


def set_sleep_settings(
    base_need_min: Annotated[
        int | None,
        Field(
            ge=360,
            le=600,
            description="Baseline sleep need in minutes (360-600, i.e. 6 to 10 hours).",
        ),
    ] = None,
    alarm_time: Annotated[
        str | None,
        Field(
            description="Fixed target wake-up alarm time in 'HH:MM' 24-hour format (e.g. '06:30').",
        ),
    ] = None,
    clear_alarm: Annotated[
        bool,
        Field(
            description=(
                "Set to true to clear the fixed alarm time and revert to median recent wake times."
            ),
        ),
    ] = False,
) -> dict[str, Any]:
    """Configure sleep scoring settings (baseline sleep need and optional fixed alarm time)."""
    if base_need_min is None and alarm_time is None and not clear_alarm:
        raise ToolError(
            "at least one of base_need_min, alarm_time, or clear_alarm must be specified"
        )
    if clear_alarm and alarm_time is not None:
        raise ToolError("cannot specify both alarm_time and clear_alarm=True")

    if base_need_min is not None and not (360 <= base_need_min <= 600):
        raise ToolError("base_need_min must be between 360 and 600 minutes")

    formatted_alarm: str | None = None
    if alarm_time is not None:
        raw = alarm_time.strip()
        if not ALARM_RE.match(raw):
            raise ToolError(
                f"alarm_time {alarm_time!r} must be in 'HH:MM' 24-hour format (e.g. '06:30')"
            )
        parts = raw.split(":")
        h, min_val = int(parts[0]), int(parts[1])
        formatted_alarm = f"{h:02d}:{min_val:02d}"

    with get_engine(Role.rw).begin() as conn:
        if base_need_min is not None:
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES ('sleep_need_base_min', CAST(:val AS jsonb), now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                ),
                {"val": json.dumps(base_need_min)},
            )
        if formatted_alarm is not None:
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES ('alarm_time', CAST(:val AS jsonb), now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                ),
                {"val": json.dumps(formatted_alarm)},
            )
        elif clear_alarm:
            conn.execute(
                text(
                    "INSERT INTO app_settings (key, value, updated_at) "
                    "VALUES ('alarm_time', 'null'::jsonb, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                )
            )

    return get_sleep_settings()


def get_sleep_settings() -> dict[str, Any]:
    """Retrieve current sleep scoring settings (baseline need and optional fixed alarm time)."""
    with get_engine(Role.ro).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT key, value FROM app_settings "
                "WHERE key IN ('sleep_need_base_min', 'alarm_time')"
            )
        ).all()
    settings_map = {r.key: r.value for r in rows}
    base_need = (
        settings_map.get("sleep_need_base_min")
        if settings_map.get("sleep_need_base_min") is not None
        else get_settings().sleep_need_base_min
    )
    alarm = settings_map.get("alarm_time")
    return {
        "sleep_need_base_min": base_need,
        "alarm_time": alarm,
    }


def register(server: MCPServer) -> None:
    server.tool(annotations=UPSERT)(audited(log_journal))
    server.tool(annotations=READ)(audited(get_journal))
    server.tool(annotations=DESTRUCTIVE)(audited(delete_journal_entry))
    server.tool(annotations=READ)(audited(get_journal_insights))
    server.tool(annotations=UPSERT)(audited(set_sleep_settings))
    server.tool(annotations=READ)(audited(get_sleep_settings))
