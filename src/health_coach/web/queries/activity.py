"""Activity screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.mcp_server import quality
from health_coach.mcp_server.tools.discovery import current_targets
from health_coach.web.queries._common import _parse_date


def query_activity(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    start_date = target_date - dt.timedelta(days=days - 1)

    act_rows = (
        conn.execute(
            text(
                "SELECT local_date, steps, active_zone_minutes, calories_out "
                "FROM daily_activity WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    act_map = {r["local_date"]: r for r in act_rows}

    targets = current_targets(conn, target_date)
    step_target = targets.get("steps") if targets else None

    steps_series: list[dict[str, Any]] = []
    active_series: list[dict[str, Any]] = []
    calories_series: list[dict[str, Any]] = []

    curr_d = start_date
    while curr_d <= target_date:
        r = act_map.get(curr_d)
        st = r["steps"] if r and r.get("steps") is not None else None
        act = r["active_zone_minutes"] if r and r.get("active_zone_minutes") is not None else None
        cal = r["calories_out"] if r and r.get("calories_out") is not None else None

        d_str = curr_d.isoformat()
        steps_series.append({"date": d_str, "val": st})
        active_series.append({"date": d_str, "val": act})
        calories_series.append({"date": d_str, "val": cal})
        curr_d += dt.timedelta(days=1)

    valid_steps = [s["val"] for s in steps_series if s["val"] is not None]
    avg_steps = round(sum(valid_steps) / len(valid_steps)) if valid_steps else None

    valid_act = [s["val"] for s in active_series if s["val"] is not None]
    avg_active = round(sum(valid_act) / len(valid_act)) if valid_act else None

    valid_cal = [s["val"] for s in calories_series if s["val"] is not None]
    avg_cal = round(sum(valid_cal) / len(valid_cal)) if valid_cal else None

    return {
        "date": target_date.isoformat(),
        "days": days,
        "steps": {
            "avg": avg_steps,
            "target": step_target,
            "series": steps_series,
        },
        "active_minutes": {
            "avg": avg_active,
            "series": active_series,
        },
        "calories_out": {
            "avg": avg_cal,
            "series": calories_series,
        },
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 3. /api/sleep
# -----------------------------------------------------------------------------
