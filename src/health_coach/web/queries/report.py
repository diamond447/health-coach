"""Weekly and monthly report."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.scores import calculate_strain_from_load, recovery_zone
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import jsonable
from health_coach.web.queries._common import CZECH_WEEKDAYS, MUSCLE_LABELS, _parse_date


def query_report(
    conn: Connection,
    period: str = "week",
    end_str: str | None = None,
) -> dict[str, Any]:
    if period not in ("week", "month"):
        raise ValueError(f"Invalid period: {period!r}, expected 'week' or 'month'")
    end_date = _parse_date(end_str)
    length = 7 if period == "week" else 30

    curr_start = end_date - dt.timedelta(days=length - 1)
    prev_end = curr_start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=length - 1)

    # Helper for period stats
    def _period_stats(s: dt.date, e: dt.date) -> dict[str, Any]:
        sc = (
            conn.execute(
                text(
                    "SELECT round(avg(recovery)) AS avg_rec, "
                    "       round(avg(strain), 1) AS avg_strain, "
                    "       round(avg(muscular_score), 1) AS avg_muscular, "
                    "       round(avg(sleep_actual_min)) AS avg_sleep, "
                    "       round(avg(sleep_consistency)) AS avg_consist "
                    "FROM daily_scores WHERE local_date BETWEEN :s AND :e"
                ),
                {"s": s, "e": e},
            )
            .mappings()
            .first()
        )

        cl_rows = (
            conn.execute(
                text(
                    "SELECT cardio_load FROM daily_scores "
                    "WHERE local_date BETWEEN :s AND :e AND cardio_load IS NOT NULL"
                ),
                {"s": s, "e": e},
            )
            .scalars()
            .all()
        )
        cardio_strains = [calculate_strain_from_load(float(cl)) for cl in cl_rows]
        avg_cardio = round(sum(cardio_strains) / len(cardio_strains), 1) if cardio_strains else None

        nt = (
            conn.execute(
                text(
                    "SELECT round(avg(kcal)) AS avg_kcal, "
                    "       count(*) FILTER ("
                    "         WHERE protein_g >= target_protein_g"
                    "       ) AS protein_hit_days "
                    "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e"
                ),
                {"s": s, "e": e},
            )
            .mappings()
            .first()
        )

        wt_last = conn.execute(
            text(
                "SELECT avg_7d_kg FROM v_weight_trend "
                "WHERE local_date <= :e ORDER BY local_date DESC LIMIT 1"
            ),
            {"e": e},
        ).scalar()

        debt = conn.execute(
            text(
                "SELECT sleep_debt_min FROM daily_scores "
                "WHERE local_date <= :e AND sleep_debt_min IS NOT NULL "
                "ORDER BY local_date DESC LIMIT 1"
            ),
            {"e": e},
        ).scalar()

        return {
            "avg_rec": float(sc["avg_rec"]) if sc and sc["avg_rec"] is not None else None,
            "avg_strain": float(sc["avg_strain"]) if sc and sc["avg_strain"] is not None else None,
            "avg_cardio": avg_cardio,
            "avg_muscular": float(sc["avg_muscular"])
            if sc and sc["avg_muscular"] is not None
            else None,
            "avg_sleep": float(sc["avg_sleep"]) if sc and sc["avg_sleep"] is not None else None,
            "avg_consist": float(sc["avg_consist"])
            if sc and sc["avg_consist"] is not None
            else None,
            "avg_kcal": float(nt["avg_kcal"]) if nt and nt["avg_kcal"] is not None else None,
            "protein_hit_days": nt["protein_hit_days"] if nt else 0,
            "weight_avg": float(wt_last) if wt_last is not None else None,
            "debt_min": int(debt) if debt is not None else 0,
        }

    curr = _period_stats(curr_start, end_date)
    prev = _period_stats(prev_start, prev_end)

    # Compute deltas
    def _delta(c_val: float | None, p_val: float | None) -> float | None:
        if c_val is not None and p_val is not None:
            return round(c_val - p_val, 1)
        return None

    # Daily recovery in current period
    daily_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, sleep_actual_min FROM daily_scores "
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": curr_start, "e": end_date},
        )
        .mappings()
        .all()
    )

    daily_rec: list[dict[str, Any]] = []
    best_row: dict[str, Any] | None = None
    worst_row: dict[str, Any] | None = None

    for r in daily_rows:
        rec = r["recovery"]
        daily_rec.append(
            {
                "date": r["local_date"].isoformat(),
                "weekday": CZECH_WEEKDAYS[r["local_date"].weekday()],
                "recovery": rec,
                "zone": recovery_zone(rec),
            }
        )
        if rec is not None:
            if best_row is None or rec > (best_row["recovery"] or 0):
                best_row = dict(r)
            if worst_row is None or rec < (worst_row["recovery"] or 100):
                worst_row = dict(r)

    # Hard sets per muscle
    muscle_rows = (
        conn.execute(
            text(
                "WITH hard AS ( "
                "    SELECT ss.id, x.primary_muscles, x.secondary_muscles "
                "    FROM strength_sets ss "
                "    JOIN strength_sessions s ON s.id = ss.session_id "
                "    JOIN exercises x ON x.id = ss.exercise_id "
                "    WHERE NOT ss.is_warmup "
                "      AND coalesce(ss.reps, 0) > 0 "
                "      AND (ss.rir IS NULL OR ss.rir <= 4) "
                "      AND s.local_date BETWEEN :s AND :e "
                "), m AS ( "
                "    SELECT unnest(primary_muscles) AS muscle, 1.0 AS weight FROM hard "
                "    UNION ALL "
                "    SELECT unnest(secondary_muscles), 0.5 FROM hard "
                ") "
                "SELECT muscle, round(sum(weight)) AS sets FROM m "
                "GROUP BY muscle ORDER BY sets DESC"
            ),
            {"s": curr_start, "e": end_date},
        )
        .mappings()
        .all()
    )

    workout_count = conn.execute(
        text("SELECT count(*) FROM strength_sessions WHERE local_date BETWEEN :s AND :e"),
        {"s": curr_start, "e": end_date},
    ).scalar_one()

    muscles_list: list[dict[str, Any]] = [
        {
            "muscle": MUSCLE_LABELS.get(r["muscle"], r["muscle"].capitalize()),
            "sets": int(r["sets"]),
        }
        for r in muscle_rows
    ]

    # Latest coach log of kind 'review'
    review_row = (
        conn.execute(
            text(
                "SELECT id, ts, title, body FROM coach_log "
                "WHERE kind = 'review' ORDER BY ts DESC LIMIT 1"
            )
        )
        .mappings()
        .first()
    )

    coach_review = (
        {
            "id": review_row["id"],
            "ts": jsonable(review_row["ts"]),
            "title": review_row["title"],
            "body": review_row["body"],
        }
        if review_row
        else None
    )

    return {
        "period": period,
        "start": curr_start.isoformat(),
        "end": end_date.isoformat(),
        "tiles": {
            "recovery": {"val": curr["avg_rec"], "delta": _delta(curr["avg_rec"], prev["avg_rec"])},
            "strain": {
                "val": curr["avg_strain"],
                "delta": _delta(curr["avg_strain"], prev["avg_strain"]),
                "cardio_avg": curr["avg_cardio"],
                "muscular_avg": curr["avg_muscular"],
            },
            "sleep_min": {
                "val": curr["avg_sleep"],
                "delta": _delta(curr["avg_sleep"], prev["avg_sleep"]),
                "debt_min": curr["debt_min"],
            },
            "consistency": {
                "val": curr["avg_consist"],
                "delta": _delta(curr["avg_consist"], prev["avg_consist"]),
            },
            "kcal": {
                "val": curr["avg_kcal"],
                "delta": _delta(curr["avg_kcal"], prev["avg_kcal"]),
                "protein_hit_days": curr["protein_hit_days"],
                "total_days": length,
            },
            "weight": {
                "val": curr["weight_avg"],
                "delta": _delta(curr["weight_avg"], prev["weight_avg"]),
            },
        },
        "daily_recovery": daily_rec,
        "best_day": {
            "date": best_row["local_date"].isoformat(),
            "weekday": CZECH_WEEKDAYS[best_row["local_date"].weekday()],
            "recovery": best_row["recovery"],
            "sleep_min": best_row["sleep_actual_min"],
        }
        if best_row
        else None,
        "worst_day": {
            "date": worst_row["local_date"].isoformat(),
            "weekday": CZECH_WEEKDAYS[worst_row["local_date"].weekday()],
            "recovery": worst_row["recovery"],
            "sleep_min": worst_row["sleep_actual_min"],
        }
        if worst_row
        else None,
        "muscles": muscles_list,
        "workouts_count": workout_count,
        "coach_review": coach_review,
        "as_of": quality.as_of(conn),
    }
