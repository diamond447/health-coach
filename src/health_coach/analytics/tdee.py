"""Adaptive TDEE estimation from caloric intake and weight trend change."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

CALORIES_PER_KG_FAT = 7700.0


@dataclass(frozen=True)
class TdeeResult:
    avg_intake: float | None
    trend_change_kg: float | None
    tdee: float | None
    confidence: str  # "high", "medium", "low", "none"
    logged_days: int
    weigh_ins: int


def calculate_tdee(
    window_days: int,
    logged_daily_kcals: Sequence[float],
    start_trend_kg: float | None,
    end_trend_kg: float | None,
    weigh_ins: int,
) -> TdeeResult:
    """Calculate adaptive TDEE over a window.

    tdee = avg_intake - trend_change_kg * 7700 / window_days

    Confidence rules:
    - "none" if logged_days < 7 or weigh_ins < 4 (tdee null)
    - "high" if logged_days >= 0.85 * window and weigh_ins >= 0.5 * window
    - "medium" if logged_days >= 0.7 * window and weigh_ins >= 0.3 * window
    - else "low"
    """
    logged_days = len(logged_daily_kcals)
    avg_intake = round(sum(logged_daily_kcals) / logged_days, 1) if logged_days > 0 else None

    trend_change_kg = (
        round(end_trend_kg - start_trend_kg, 2)
        if (start_trend_kg is not None and end_trend_kg is not None)
        else None
    )

    if logged_days < 7 or weigh_ins < 4 or start_trend_kg is None or end_trend_kg is None:
        return TdeeResult(
            avg_intake=avg_intake,
            trend_change_kg=trend_change_kg,
            tdee=None,
            confidence="none",
            logged_days=logged_days,
            weigh_ins=weigh_ins,
        )

    if logged_days >= 0.85 * window_days and weigh_ins >= 0.5 * window_days:
        confidence = "high"
    elif logged_days >= 0.7 * window_days and weigh_ins >= 0.3 * window_days:
        confidence = "medium"
    else:
        confidence = "low"

    assert avg_intake is not None and trend_change_kg is not None
    tdee = avg_intake - (trend_change_kg * CALORIES_PER_KG_FAT / window_days)

    return TdeeResult(
        avg_intake=avg_intake,
        trend_change_kg=trend_change_kg,
        tdee=round(tdee, 1),
        confidence=confidence,
        logged_days=logged_days,
        weigh_ins=weigh_ins,
    )


def estimate_from_db(
    conn: Connection, day: dt.date, window_days: int
) -> tuple[TdeeResult, dt.date, dt.date]:
    """Estimate for the window of `window_days` days ending the day before `day`.

    The trend change is measured from the evening before the window (latest trend on or
    before start - 1) to its last day, so it spans exactly `window_days` days.
    """
    end = day - dt.timedelta(days=1)
    start = end - dt.timedelta(days=window_days - 1)
    kcals = [
        float(k)
        for k in conn.execute(
            text(
                "SELECT kcal FROM v_nutrition_daily "
                "WHERE local_date BETWEEN :s AND :e AND kcal IS NOT NULL"
            ),
            {"s": start, "e": end},
        ).scalars()
    ]
    trend_sql = text(
        "SELECT trend_kg FROM v_weight_trend WHERE local_date <= :d "
        "ORDER BY local_date DESC LIMIT 1"
    )
    end_trend = conn.execute(trend_sql, {"d": end}).scalar()
    start_trend = conn.execute(trend_sql, {"d": start - dt.timedelta(days=1)}).scalar()
    weigh_ins = conn.execute(
        text(
            "SELECT count(*) FROM v_body_daily "
            "WHERE weight_kg IS NOT NULL AND local_date BETWEEN :s AND :e"
        ),
        {"s": start, "e": end},
    ).scalar_one()
    result = calculate_tdee(
        window_days=window_days,
        logged_daily_kcals=kcals,
        start_trend_kg=float(start_trend) if start_trend is not None else None,
        end_trend_kg=float(end_trend) if end_trend is not None else None,
        weigh_ins=weigh_ins,
    )
    return result, start, end
