"""The main screen: one day at a glance."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.scores import calculate_strain_from_load, recovery_zone
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import jsonable
from health_coach.web.queries._common import (
    CZECH_WEEKDAYS,
    _activity_scores,
    _activity_strains,
    _get_daily_score_row,
    _parse_date,
)


def query_day(conn: Connection, date_str: str | None = None) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    score_row = _get_daily_score_row(conn, target_date)

    vitals_row = (
        conn.execute(
            text(
                "SELECT resting_hr, hrv_rmssd_ms, breathing_rate, skin_temp_delta, spo2_avg "
                "FROM daily_vitals WHERE local_date = :d"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    activity_row = (
        conn.execute(
            text(
                "SELECT steps, active_zone_minutes, calories_out "
                "FROM daily_activity WHERE local_date = :d"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    # Recovery data
    recovery = score_row["recovery"] if score_row else None
    zone = recovery_zone(recovery) if recovery is not None else None
    components = score_row["recovery_components"] if score_row else None
    if isinstance(components, str):
        components = json.loads(components)
    flags = score_row["flags"] if score_row else []

    # Strain & plan
    strain = (
        float(score_row["strain"]) if score_row and score_row.get("strain") is not None else None
    )
    cardio_load_raw = (
        float(score_row["cardio_load"])
        if score_row and score_row.get("cardio_load") is not None
        else None
    )
    cardio_strain = (
        calculate_strain_from_load(cardio_load_raw) if cardio_load_raw is not None else None
    )
    muscular_score = (
        int(score_row["muscular_score"])
        if score_row and score_row.get("muscular_score") is not None
        else None
    )
    strain_target_low = (
        float(score_row["strain_target_low"])
        if score_row and score_row.get("strain_target_low") is not None
        else None
    )
    strain_target_high = (
        float(score_row["strain_target_high"])
        if score_row and score_row.get("strain_target_high") is not None
        else None
    )

    sleep_need_min = score_row["sleep_need_min"] if score_row else None
    sleep_actual_min = score_row["sleep_actual_min"] if score_row else None
    sleep_debt_min = score_row["sleep_debt_min"] if score_row else None
    sleep_perf = score_row["sleep_performance"] if score_row else None
    sleep_eff = score_row["sleep_efficiency"] if score_row else None
    planned_bedtime = score_row["planned_bedtime"] if score_row else None
    planned_wake = score_row["planned_wake"] if score_row else None

    # Activities from the sessions, with the strain the scores job computed for each
    activities: list[dict[str, Any]] = []
    strains = _activity_strains(score_row)
    scores = _activity_scores(score_row)
    st_rows = (
        conn.execute(
            text(
                "SELECT s.id, "
                "  coalesce(s.routine_name, s.day_name, 'Posilování') AS name, "
                "  s.start_ts, s.end_ts, "
                "  count(ss.id) FILTER ("
                "    WHERE NOT ss.is_warmup AND coalesce(ss.reps, 0) > 0"
                "  ) AS hard_sets, "
                "  round(sum(ss.weight_kg * ss.reps) FILTER ("
                "    WHERE NOT ss.is_warmup AND ss.weight_kg > 0 AND ss.reps > 0"
                "  ), 1) AS volume_kg "
                "FROM strength_sessions s "
                "LEFT JOIN strength_sets ss ON ss.session_id = s.id "
                "WHERE s.local_date = :d "
                "GROUP BY s.id, s.routine_name, s.day_name, s.start_ts, s.end_ts"
            ),
            {"d": target_date},
        )
        .mappings()
        .all()
    )
    for st in st_rows:
        activities.append(
            {
                "type": "strength",
                "name": st["name"] or "Posilování",
                "start_ts": jsonable(st["start_ts"]),
                "end_ts": jsonable(st["end_ts"]),
                "hard_sets": st["hard_sets"],
                "volume_kg": float(st["volume_kg"]) if st["volume_kg"] else 0.0,
                "strain": strains.get((True, st["start_ts"])),
                "score": scores.get((True, st["start_ts"])),
            }
        )

    ex_rows = (
        conn.execute(
            text(
                "SELECT id, activity_type, start_ts, end_ts, duration_min, "
                "       calories, distance_km, avg_hr "
                "FROM exercise_sessions WHERE local_date = :d AND deleted_at IS NULL"
            ),
            {"d": target_date},
        )
        .mappings()
        .all()
    )
    for ex in ex_rows:
        dist_km = round(float(ex["distance_km"]), 1) if ex["distance_km"] is not None else None
        activities.append(
            {
                "type": ex["activity_type"] or "cardio",
                "name": (ex["activity_type"] or "Aktivita").capitalize(),
                "start_ts": jsonable(ex["start_ts"]),
                "end_ts": jsonable(ex["end_ts"]),
                "duration_min": ex["duration_min"],
                "calories": ex["calories"],
                "distance_km": dist_km,
                "avg_hr": ex["avg_hr"],
                "strain": strains.get((False, ex["start_ts"])),
            }
        )
    activities.sort(key=lambda a: a["start_ts"] or "")

    return {
        "date": target_date.isoformat(),
        "weekday": CZECH_WEEKDAYS[target_date.weekday()],
        "scores": {
            "recovery": recovery,
            "recovery_zone": zone,
            "components": components,
            "flags": flags,
            "strain": strain,
            "cardio_strain": cardio_strain,
            "muscular_score": muscular_score,
            "strain_target_low": strain_target_low,
            "strain_target_high": strain_target_high,
            "sleep_need_min": sleep_need_min,
            "sleep_actual_min": sleep_actual_min,
            "sleep_debt_min": sleep_debt_min,
            "sleep_performance": sleep_perf,
            "sleep_efficiency": sleep_eff,
            "planned_bedtime": jsonable(planned_bedtime),
            "planned_wake": jsonable(planned_wake),
        },
        "vitals": {
            "resting_hr": vitals_row["resting_hr"] if vitals_row else None,
            "hrv_rmssd_ms": (
                float(vitals_row["hrv_rmssd_ms"])
                if vitals_row and vitals_row["hrv_rmssd_ms"] is not None
                else None
            ),
            "breathing_rate": (
                float(vitals_row["breathing_rate"])
                if vitals_row and vitals_row["breathing_rate"] is not None
                else None
            ),
            "skin_temp_delta": (
                float(vitals_row["skin_temp_delta"])
                if vitals_row and vitals_row["skin_temp_delta"] is not None
                else None
            ),
            "spo2_avg": (
                float(vitals_row["spo2_avg"])
                if vitals_row and vitals_row["spo2_avg"] is not None
                else None
            ),
        },
        "activity": {
            "steps": activity_row["steps"] if activity_row else None,
            "active_minutes": activity_row["active_zone_minutes"] if activity_row else None,
            "calories_out": activity_row["calories_out"] if activity_row else None,
        },
        "activities": activities,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 2. /api/recovery
# -----------------------------------------------------------------------------
