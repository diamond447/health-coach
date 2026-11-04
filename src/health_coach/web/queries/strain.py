"""Strain screen: day strain, activities and heart-rate curve."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.scores import calculate_strain_from_load
from health_coach.config import get_settings
from health_coach.mcp_server import quality
from health_coach.profile import load_profile
from health_coach.web.queries._common import (
    CZECH_WEEKDAYS,
    _activity_scores,
    _activity_strains,
    _get_daily_score_row,
    _parse_date,
)


def query_strain(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    settings = get_settings()
    tz = settings.tz

    score_row = _get_daily_score_row(conn, target_date)
    strain = (
        float(score_row["strain"]) if score_row and score_row.get("strain") is not None else None
    )
    cardio_load = (
        float(score_row["cardio_load"])
        if score_row and score_row.get("cardio_load") is not None
        else None
    )
    muscular_load = (
        float(score_row["muscular_load"])
        if score_row and score_row.get("muscular_load") is not None
        else None
    )
    cardio_strain = calculate_strain_from_load(cardio_load) if cardio_load is not None else None
    muscular_score = (
        int(score_row["muscular_score"])
        if score_row and score_row.get("muscular_score") is not None
        else None
    )
    zone_minutes = score_row["zone_minutes"] if score_row else None
    if isinstance(zone_minutes, str):
        zone_minutes = json.loads(zone_minutes)

    # Rest and HR max from inputs JSON or defaults
    inputs_data = score_row["inputs"] if score_row and score_row.get("inputs") else None
    if isinstance(inputs_data, str):
        inputs_data = json.loads(inputs_data)
    rest_hr = float(inputs_data.get("rest_hr", 60.0)) if isinstance(inputs_data, dict) else 60.0
    fallback_hr_max = load_profile(conn, settings).effective_hr_max(target_date.year)
    hr_max = (
        float(inputs_data.get("hr_max", fallback_hr_max))
        if isinstance(inputs_data, dict)
        else float(fallback_hr_max)
    )
    hrr = max(1.0, hr_max - rest_hr)

    # HR zones boundaries
    zones_def = [
        {
            "name": "Zóna 1",
            "min_hr": round(rest_hr + 0.50 * hrr),
            "max_hr": round(rest_hr + 0.60 * hrr),
            "color": "#7FA6C9",
            "key": "Z1",
        },
        {
            "name": "Zóna 2",
            "min_hr": round(rest_hr + 0.60 * hrr),
            "max_hr": round(rest_hr + 0.70 * hrr),
            "color": "#4D9BE8",
            "key": "Z2",
        },
        {
            "name": "Zóna 3",
            "min_hr": round(rest_hr + 0.70 * hrr),
            "max_hr": round(rest_hr + 0.80 * hrr),
            "color": "#3D7CF0",
            "key": "Z3",
        },
        {
            "name": "Zóna 4",
            "min_hr": round(rest_hr + 0.80 * hrr),
            "max_hr": round(rest_hr + 0.90 * hrr),
            "color": "#FF9A4D",
            "key": "Z4",
        },
        {
            "name": "Zóna 5",
            "min_hr": round(rest_hr + 0.90 * hrr),
            "max_hr": round(hr_max),
            "color": "#FF5A5F",
            "key": "Z5",
        },
    ]
    for z in zones_def:
        z["minutes"] = (zone_minutes or {}).get(z["key"], 0)

    # Heart rate series aggregated into 5-minute buckets
    day_start = dt.datetime.combine(target_date, dt.time.min, tz)
    day_end = dt.datetime.combine(target_date + dt.timedelta(days=1), dt.time.min, tz)

    hr_buckets = (
        conn.execute(
            text(
                "SELECT to_timestamp(floor(extract(epoch from ts) / 300) * 300) "
                "         at time zone 'UTC' as bucket, "
                "       round(avg(bpm)) as bpm "
                "FROM heart_rate_samples "
                "WHERE ts >= :day_start AND ts < :day_end "
                "GROUP BY bucket ORDER BY bucket"
            ),
            {"day_start": day_start, "day_end": day_end},
        )
        .mappings()
        .all()
    )

    hr_points: list[dict[str, Any]] = []
    max_hr_sample = 0
    for b in hr_buckets:
        b_dt = b["bucket"]
        # Convert to local time
        if b_dt.tzinfo is None:
            b_dt = b_dt.replace(tzinfo=dt.UTC)
        local_b = b_dt.astimezone(tz)
        minute_of_day = local_b.hour * 60 + local_b.minute
        bpm_val = int(b["bpm"])
        if bpm_val > max_hr_sample:
            max_hr_sample = bpm_val
        hr_points.append(
            {
                "time": f"{local_b.hour:02d}:{local_b.minute:02d}",
                "minute": minute_of_day,
                "bpm": bpm_val,
            }
        )

    # Workout windows (exercise_sessions and strength_sessions)
    workout_windows: list[dict[str, Any]] = []
    st_sessions = (
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
                "  ), 1) AS volume_kg, "
                "  round(avg(10 - ss.rir) FILTER ("
                "    WHERE NOT ss.is_warmup AND ss.rir IS NOT NULL"
                "  ), 1) AS mean_rpe "
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

    activities: list[dict[str, Any]] = []
    strains = _activity_strains(score_row)
    scores = _activity_scores(score_row)
    for st in st_sessions:
        st_start = st["start_ts"].astimezone(tz) if st["start_ts"] else None
        st_end = st["end_ts"].astimezone(tz) if st["end_ts"] else None
        if st_start and st_end:
            workout_windows.append(
                {
                    "start_minute": st_start.hour * 60 + st_start.minute,
                    "end_minute": st_end.hour * 60 + st_end.minute,
                    "name": st["name"] or "Posilování",
                }
            )
        activities.append(
            {
                "type": "strength",
                "name": st["name"] or "Posilování",
                "start_time": f"{st_start.hour:02d}:{st_start.minute:02d}" if st_start else None,
                "end_time": f"{st_end.hour:02d}:{st_end.minute:02d}" if st_end else None,
                "hard_sets": st["hard_sets"],
                "volume_kg": float(st["volume_kg"]) if st["volume_kg"] else 0.0,
                "mean_rpe": float(st["mean_rpe"]) if st["mean_rpe"] else None,
                "strain": strains.get((True, st["start_ts"])),
                "score": scores.get((True, st["start_ts"])),
            }
        )

    ex_sessions = (
        conn.execute(
            text(
                "SELECT id, activity_type, start_ts, end_ts, duration_min, "
                "       distance_km, avg_hr, max_hr "
                "FROM exercise_sessions WHERE local_date = :d AND deleted_at IS NULL"
            ),
            {"d": target_date},
        )
        .mappings()
        .all()
    )
    for ex in ex_sessions:
        ex_start = ex["start_ts"].astimezone(tz) if ex["start_ts"] else None
        ex_end = ex["end_ts"].astimezone(tz) if ex["end_ts"] else None
        if ex_start and ex_end:
            workout_windows.append(
                {
                    "start_minute": ex_start.hour * 60 + ex_start.minute,
                    "end_minute": ex_end.hour * 60 + ex_end.minute,
                    "name": (ex["activity_type"] or "Aktivita").capitalize(),
                }
            )
        activities.append(
            {
                "type": ex["activity_type"] or "cardio",
                "name": (ex["activity_type"] or "Aktivita").capitalize(),
                "start_time": f"{ex_start.hour:02d}:{ex_start.minute:02d}" if ex_start else None,
                "end_time": f"{ex_end.hour:02d}:{ex_end.minute:02d}" if ex_end else None,
                "duration_min": ex["duration_min"],
                "distance_km": (
                    round(float(ex["distance_km"]), 1) if ex["distance_km"] is not None else None
                ),
                "avg_hr": ex["avg_hr"],
                "max_hr": ex["max_hr"],
                "strain": strains.get((False, ex["start_ts"])),
            }
        )
    activities.sort(key=lambda a: a["start_time"] or "")

    # Last trailing days strain
    week_start = target_date - dt.timedelta(days=days - 1)
    week_strains_rows = (
        conn.execute(
            text(
                "SELECT local_date, strain, cardio_load, muscular_score FROM daily_scores "
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_strain_map = {r["local_date"]: r for r in week_strains_rows}

    week_strains: list[dict[str, Any]] = []
    w_d = week_start
    sum_strain = 0.0
    cnt_strain = 0
    while w_d <= target_date:
        row = week_strain_map.get(w_d)
        st_val = float(row["strain"]) if row and row.get("strain") is not None else None
        cl_val = float(row["cardio_load"]) if row and row.get("cardio_load") is not None else None
        cs_val = calculate_strain_from_load(cl_val) if cl_val is not None else None
        ms_val = (
            int(row["muscular_score"]) if row and row.get("muscular_score") is not None else None
        )
        if st_val is not None:
            sum_strain += st_val
            cnt_strain += 1
        week_strains.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "strain": st_val,
                "cardio_strain": cs_val,
                "muscular_score": ms_val,
            }
        )
        w_d += dt.timedelta(days=1)

    avg_week_strain = round(sum_strain / cnt_strain, 1) if cnt_strain > 0 else None

    return {
        "date": target_date.isoformat(),
        "strain": strain,
        "cardio_strain": cardio_strain,
        "cardio_load": cardio_load,
        "muscular_load": muscular_load,
        "muscular_score": muscular_score,
        "strain_target_low": float(score_row["strain_target_low"])
        if score_row and score_row.get("strain_target_low") is not None
        else None,
        "strain_target_high": float(score_row["strain_target_high"])
        if score_row and score_row.get("strain_target_high") is not None
        else None,
        "recovery": score_row["recovery"] if score_row else None,
        "rest_hr": round(rest_hr),
        "hr_max": round(hr_max),
        "peak_hr": max_hr_sample or (round(hr_max) if hr_points else None),
        "zones": zones_def,
        "hr_points": hr_points,
        "workout_windows": workout_windows,
        "activities": activities,
        "week_strains": week_strains,
        "avg_week_strain": avg_week_strain,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 5. /api/nutrition
# -----------------------------------------------------------------------------
