"""Journal screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.journal import compute_journal_insights
from health_coach.config import get_settings
from health_coach.journal import BEHAVIOR_LABELS, JOURNAL_OPTIONS
from health_coach.mcp_server import quality
from health_coach.web.queries._common import CZECH_WEEKDAYS, _parse_date


def query_journal(
    conn: Connection,
    days: int = 60,
    date_str: str | None = None,
    can_write: bool | None = None,
) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    yesterday_date = target_date - dt.timedelta(days=1)
    start_date = target_date - dt.timedelta(days=days)

    # 1. Yesterday's entries
    y_rows = (
        conn.execute(
            text(
                "SELECT behavior, amount, note, source, created_at "
                "FROM journal_entries "
                "WHERE local_date = :d AND deleted_at IS NULL "
                "ORDER BY id"
            ),
            {"d": yesterday_date},
        )
        .mappings()
        .all()
    )

    logged_time: str | None = None
    y_map: dict[str, dict[str, Any]] = {}
    for r in y_rows:
        b = r["behavior"]
        y_map[b] = {
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

    # Build yesterday list with active + some known inactive behaviors for chip display
    yesterday_chips: list[dict[str, Any]] = list(y_map.values())

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
        "yesterday_date": yesterday_date.isoformat(),
        "yesterday_weekday": CZECH_WEEKDAYS[yesterday_date.weekday()],
        "logged_time": logged_time,
        "yesterday": yesterday_chips,
        "insights": insights_formatted,
        "insufficient": insufficient_formatted,
        "can_write": can_write,
        "log_date": yesterday_date.isoformat(),
        "options": JOURNAL_OPTIONS,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 9. /api/report
# -----------------------------------------------------------------------------
