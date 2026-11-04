"""Helpers and labels shared by the screen queries."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import Connection, text

from health_coach.mcp_server.common import today

CZECH_WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
CZECH_MONTHS = [
    "",
    "Leden",
    "Únor",
    "Březen",
    "Duben",
    "Květen",
    "Červen",
    "Červenec",
    "Srpen",
    "Září",
    "Říjen",
    "Listopad",
    "Prosinec",
]


MUSCLE_LABELS: dict[str, str] = {
    "chest": "Hrudník",
    "back": "Záda",
    "lats": "Záda",
    "upper_back": "Záda",
    "quads": "Nohy",
    "hamstrings": "Nohy",
    "glutes": "Hýždě",
    "calves": "Lýtka",
    "shoulders": "Ramena",
    "biceps": "Biceps",
    "triceps": "Triceps",
    "forearms": "Předloktí",
    "core": "Břicho",
    "abs": "Břicho",
}

MEAL_LABELS: dict[str, str] = {
    "breakfast": "Snídaně",
    "lunch": "Oběd",
    "dinner": "Večeře",
    "snack": "Svačina",
    "post_workout": "Po tréninku",
    "pre_workout": "Před tréninkem",
    "other": "Ostatní",
}


def _parse_date(date_str: str | None) -> dt.date:
    """Parse YYYY-MM-DD or default to today in HC_TIMEZONE.

    Raises ValueError on malformed date string.
    """
    if not date_str:
        return today()
    parts = date_str.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError(f"Invalid date format {date_str!r}, expected YYYY-MM-DD")
    return dt.date.fromisoformat(date_str)


def _get_daily_score_row(conn: Connection, d: dt.date) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("SELECT * FROM daily_scores WHERE local_date = :d"),
            {"d": d},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# -----------------------------------------------------------------------------
# 1. /api/day
# -----------------------------------------------------------------------------


def _activity_strains(
    score_row: dict[str, Any] | None,
) -> dict[tuple[bool, dt.datetime], float]:
    """Strain per activity from daily_scores.activities, keyed by (is strength, start)."""
    raw = score_row.get("activities") if score_row else None
    if isinstance(raw, str):
        raw = json.loads(raw)
    strains: dict[tuple[bool, dt.datetime], float] = {}
    for act in raw if isinstance(raw, list) else []:
        if act.get("start") and act.get("strain") is not None:
            key = (act.get("kind") == "strength", dt.datetime.fromisoformat(act["start"]))
            strains[key] = float(act["strain"])
    return strains


def _activity_scores(
    score_row: dict[str, Any] | None,
) -> dict[tuple[bool, dt.datetime], float]:
    """Score per activity from daily_scores.activities, keyed by (is strength, start)."""
    raw = score_row.get("activities") if score_row else None
    if isinstance(raw, str):
        raw = json.loads(raw)
    scores: dict[tuple[bool, dt.datetime], float] = {}
    for act in raw if isinstance(raw, list) else []:
        if act.get("start") and act.get("score") is not None:
            key = (act.get("kind") == "strength", dt.datetime.fromisoformat(act["start"]))
            scores[key] = float(act["score"])
    return scores
