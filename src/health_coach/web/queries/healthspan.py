"""Healthspan screen."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from health_coach.mcp_server import quality


def query_healthspan(conn: Connection, weeks: int = 26) -> dict[str, Any]:
    """Return healthspan summary, factor breakdown, and history sparkline data."""
    rows = conn.execute(
        text(
            "SELECT week_start, delta_years, pace, factors, factors_with_data, age, algo_version "
            "FROM healthspan_weekly ORDER BY week_start DESC LIMIT :w"
        ),
        {"w": weeks},
    ).all()

    if not rows:
        return {
            "has_enough_data": False,
            "latest": None,
            "history": [],
            "as_of": quality.as_of(conn),
        }

    asc_rows = list(reversed(rows))
    latest_row = asc_rows[-1]
    # Rows from before ALGO_VERSION 2 stored 0.0 for weeks without any data.
    weeks_with_data = sum(1 for r in asc_rows if r.factors_with_data > 0)
    has_enough_data = weeks_with_data >= 4 and latest_row.factors_with_data >= 4

    history = [
        {
            "week_start": r.week_start.isoformat(),
            "delta_years": float(r.delta_years) if r.delta_years is not None else None,
        }
        for r in asc_rows
        if r.factors_with_data > 0
    ]

    age_val = latest_row.age
    delta_val = float(latest_row.delta_years) if latest_row.delta_years is not None else None
    bio_age = (
        round(age_val + delta_val, 1) if age_val is not None and delta_val is not None else None
    )

    factors_data = latest_row.factors
    if isinstance(factors_data, str):
        try:
            factors_data = json.loads(factors_data)
        except Exception:
            factors_data = []

    latest = {
        "week_start": latest_row.week_start.isoformat(),
        "delta_years": delta_val,
        "pace": float(latest_row.pace) if latest_row.pace is not None else None,
        "age": age_val,
        "biological_age": bio_age,
        "factors_with_data": latest_row.factors_with_data,
        "factors": factors_data,
        "algo_version": latest_row.algo_version,
    }

    return {
        "has_enough_data": has_enough_data,
        "latest": latest,
        "history": history,
        "as_of": quality.as_of(conn),
    }
