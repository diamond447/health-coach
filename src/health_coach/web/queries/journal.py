"""Journal screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.journal import compute_journal_insights
from health_coach.config import get_settings
from health_coach.journal import BEHAVIOR_LABELS, JOURNAL_OPTIONS, WEB_LOG_WINDOW_DAYS
from health_coach.mcp_server import quality
from health_coach.web.queries._common import _parse_date


def query_journal(
    conn: Connection,
    days: int = 60,
    date_str: str | None = None,
    can_write: bool | None = None,
    log_date_str: str | None = None,
) -> dict[str, Any]:
    """Entries of one evening plus the habit insights.

    date_str is the screen's today, where the insights end. log_date_str picks the evening
    shown, yesterday's by default; it must lie between date_str and WEB_LOG_WINDOW_DAYS
    before it (the days the app can edit), otherwise ValueError.
    """
    target_date = _parse_date(date_str)
    start_date = target_date - dt.timedelta(days=days)
    min_log_date = target_date - dt.timedelta(days=WEB_LOG_WINDOW_DAYS)
    if log_date_str:
        log_date = _parse_date(log_date_str)
        if log_date > target_date:
            raise ValueError("log_date cannot be in the future")
        if log_date < min_log_date:
            raise ValueError(f"log_date cannot be older than {WEB_LOG_WINDOW_DAYS} days")
    else:
        log_date = target_date - dt.timedelta(days=1)

    # 1. Entries of the evening shown
    day_rows = (
        conn.execute(
            text(
                "SELECT behavior, amount, note, source, created_at "
                "FROM journal_entries "
                "WHERE local_date = :d AND deleted_at IS NULL "
                "ORDER BY id"
            ),
            {"d": log_date},
        )
        .mappings()
        .all()
    )

    logged_time: str | None = None
    entries: dict[str, dict[str, Any]] = {}
    for r in day_rows:
        b = r["behavior"]
        entries[b] = {
            "behavior": b,
            "name": BEHAVIOR_LABELS.get(b, b.replace("_", " ").capitalize()),
            "amount": float(r["amount"]) if r["amount"] is not None else None,
            "note": r["note"],
            "active": True,
        }
        if r["created_at"]:
            tz = get_settings().tz
            local_ts = r["created_at"].astimezone(tz)
            logged_time = f"{local_ts.hour:02d}:{local_ts.minute:02d}"

    # 2. Insights over lookback days
    entry_rows = conn.execute(
        text(
            "SELECT local_date, behavior FROM journal_entries "
            "WHERE local_date >= :s AND local_date < :today AND deleted_at IS NULL "
            "ORDER BY local_date"
        ),
        {"s": start_date, "today": target_date},
    ).all()

    score_rows = conn.execute(
        text(
            "SELECT local_date, recovery FROM daily_scores "
            "WHERE local_date > :s AND local_date <= :today AND recovery IS NOT NULL"
        ),
        {"s": start_date, "today": target_date},
    ).all()

    rec_by_date = {r.local_date: r.recovery for r in score_rows}
    res = compute_journal_insights(entry_rows, rec_by_date, min_days=5)
    data = res.to_dict()

    insights_formatted: list[dict[str, Any]] = []
    for item in data["insights"]:
        b = item["behavior"]
        diff = round(item["difference_pp"])
        insights_formatted.append(
            {
                "behavior": b,
                "name": BEHAVIOR_LABELS.get(b, b.replace("_", " ").capitalize()),
                "difference_pp": diff,
                "with_count": item["with_count"],
                "without_count": item["without_count"],
            }
        )
    # Sort by absolute difference
    insights_formatted.sort(key=lambda x: abs(x["difference_pp"]), reverse=True)

    insufficient_formatted: list[dict[str, Any]] = []
    for item in data["insufficient"]:
        b = item["behavior"]
        insufficient_formatted.append(
            {
                "behavior": b,
                "name": BEHAVIOR_LABELS.get(b, b.replace("_", " ").capitalize()),
                "with_count": item["with_count"],
                "without_count": item["without_count"],
            }
        )

    if can_write is None:
        can_write = get_settings().web_journal_database_url is not None and bool(
            get_settings().web_allowed_users
        )

    return {
        "date": target_date.isoformat(),
        "log_date": log_date.isoformat(),
        "min_log_date": min_log_date.isoformat(),
        "max_log_date": target_date.isoformat(),
        "logged_time": logged_time,
        "entries": list(entries.values()),
        "insights": insights_formatted,
        "insufficient": insufficient_formatted,
        "can_write": can_write,
        "options": JOURNAL_OPTIONS,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 9. /api/report
# -----------------------------------------------------------------------------
