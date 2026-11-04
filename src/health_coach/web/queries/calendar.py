"""Calendar screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.scores import recovery_zone
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import today
from health_coach.web.queries._common import CZECH_MONTHS


def query_calendar(conn: Connection, month_str: str | None = None) -> dict[str, Any]:
    if not month_str:
        now_d = today()
        year = now_d.year
        month = now_d.month
    else:
        parts = month_str.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValueError(f"Invalid month format: {month_str!r}, expected YYYY-MM")
        year = int(parts[0])
        month = int(parts[1])
        if not (1 <= month <= 12):
            raise ValueError(f"Month out of range (1..12): {month}")

    # First and last day of month
    start_date = dt.date(year, month, 1)
    if month == 12:
        end_date = dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    else:
        end_date = dt.date(year, month + 1, 1) - dt.timedelta(days=1)

    # Query scores
    scores_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, strain, sleep_actual_min, sleep_debt_min "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": end_date},
        )
        .mappings()
        .all()
    )
    scores_map = {r["local_date"]: r for r in scores_rows}

    # Query workouts
    st_count = conn.execute(
        text("SELECT count(*) FROM strength_sessions WHERE local_date BETWEEN :s AND :e"),
        {"s": start_date, "e": end_date},
    ).scalar_one()

    ex_counts = (
        conn.execute(
            text(
                "SELECT activity_type, count(*) AS cnt "
                "FROM exercise_sessions WHERE local_date BETWEEN :s AND :e AND deleted_at IS NULL "
                "GROUP BY activity_type ORDER BY cnt DESC"
            ),
            {"s": start_date, "e": end_date},
        )
        .mappings()
        .all()
    )

    cells: list[dict[str, Any]] = []
    # Leading padding days for start of month (Monday = 0)
    lead_days = start_date.weekday()
    for _ in range(lead_days):
        cells.append(
            {
                "day": None,
                "date": None,
                "has_data": False,
                "recovery": None,
                "recovery_zone": None,
                "strain": None,
                "sleep_hours": None,
            }
        )

    curr_d = start_date
    rec_values: list[int] = []
    sleep_hours_list: list[float] = []
    strain_values: list[float] = []
    last_sleep_debt = 0
    max_strain_val = 0.0
    max_strain_date: str | None = None

    while curr_d <= end_date:
        sc = scores_map.get(curr_d)
        rec = sc["recovery"] if sc and sc["recovery"] is not None else None
        st = float(sc["strain"]) if sc and sc["strain"] is not None else None
        sl_m = sc["sleep_actual_min"] if sc and sc["sleep_actual_min"] is not None else None
        sl_h = round(sl_m / 60.0, 1) if sl_m is not None else None

        if rec is not None:
            rec_values.append(rec)
        if st is not None:
            strain_values.append(st)
            if st > max_strain_val:
                max_strain_val = st
                max_strain_date = f"{curr_d.day}. {curr_d.month}."
        if sl_h is not None:
            sleep_hours_list.append(sl_h)
        if sc and sc.get("sleep_debt_min") is not None:
            last_sleep_debt = sc["sleep_debt_min"]

        has_data = bool(rec is not None or st is not None or sl_h is not None)
        cells.append(
            {
                "day": curr_d.day,
                "date": curr_d.isoformat(),
                "has_data": has_data,
                "recovery": rec,
                "recovery_zone": recovery_zone(rec),
                "strain": st,
                "sleep_hours": sl_h,
            }
        )
        curr_d += dt.timedelta(days=1)

    green_count = sum(1 for v in rec_values if v >= 67)
    yellow_count = sum(1 for v in rec_values if 34 <= v < 67)
    red_count = sum(1 for v in rec_values if v < 34)

    avg_rec = round(sum(rec_values) / len(rec_values)) if rec_values else None
    avg_sleep = (
        round(sum(sleep_hours_list) / len(sleep_hours_list), 1) if sleep_hours_list else None
    )
    avg_strain = round(sum(strain_values) / len(strain_values), 1) if strain_values else None

    # Workouts breakdown
    workouts_breakdown: list[dict[str, Any]] = []
    if st_count > 0:
        workouts_breakdown.append({"name": "posilování", "count": st_count})
    for ex in ex_counts:
        act = ex["activity_type"] or "kardio"
        name_cz = "chůze" if act == "walking" else ("běh" if act == "running" else act)
        workouts_breakdown.append({"name": name_cz, "count": ex["cnt"]})

    total_workouts = st_count + sum(ex["cnt"] for ex in ex_counts)

    return {
        "month": f"{year:04d}-{month:02d}",
        "month_label": f"{CZECH_MONTHS[month]} {year}",
        "cells": cells,
        "stats": {
            "avg_recovery": avg_rec,
            "green_days": green_count,
            "yellow_days": yellow_count,
            "red_days": red_count,
            "avg_sleep_hours": avg_sleep,
            "sleep_debt_end_min": last_sleep_debt,
            "avg_strain": avg_strain,
            "max_strain": max_strain_val if max_strain_val > 0 else None,
            "max_strain_date": max_strain_date,
            "workouts_total": total_workouts,
            "workouts_breakdown": workouts_breakdown,
        },
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 8. /api/journal
# -----------------------------------------------------------------------------
