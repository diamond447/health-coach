"""Database queries for the healthstats web API.

Connects with Role.ro only. All dates are local calendar dates in HC_TIMEZONE.
Missing data returns None / empty lists; endpoints never manufacture fake values.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.journal import compute_journal_insights
from health_coach.analytics.recovery import calculate_acute_chronic
from health_coach.analytics.scores import recovery_zone
from health_coach.analytics.tdee import estimate_from_db
from health_coach.config import get_settings
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import jsonable, today
from health_coach.mcp_server.tools.discovery import current_targets

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

BEHAVIOR_LABELS: dict[str, str] = {
    "alcohol": "Alkohol",
    "sauna": "Sauna",
    "caffeine_late": "Kofein po 14:00",
    "late_meal": "Jídlo < 2 h před spaním",
    "screen_in_bed": "Mobil v posteli",
    "stretching": "Strečink večer",
    "meditation": "Meditace",
    "cold_exposure": "Chladová terapie",
    "reading": "Čtení místo mobilu",
    "nap": "Zdřímnutí",
    "high_stress": "Vysoký stres",
    "illness": "Nemoc",
    "travel": "Cestování",
    "sex": "Sex",
    "magnesium": "Hořčík večer",
}

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

    # Activities list
    activities: list[dict[str, Any]] = []
    if score_row and score_row.get("activities"):
        raw_acts = score_row["activities"]
        if isinstance(raw_acts, str):
            raw_acts = json.loads(raw_acts)
        if isinstance(raw_acts, list):
            activities = raw_acts

    # If daily_scores activities is empty, check exercise_sessions and strength_sessions
    if not activities:
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
                    "strain": None,
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
                    "strain": None,
                }
            )

    return {
        "date": target_date.isoformat(),
        "weekday": CZECH_WEEKDAYS[target_date.weekday()],
        "scores": {
            "recovery": recovery,
            "recovery_zone": zone,
            "components": components,
            "flags": flags,
            "strain": strain,
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


def query_recovery(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    start_date = target_date - dt.timedelta(days=days - 1)

    # Daily vitals and daily_scores for baseline extraction
    vitals_rows = (
        conn.execute(
            text(
                "SELECT local_date, resting_hr, hrv_rmssd_ms, breathing_rate, "
                "       skin_temp_delta, spo2_avg "
                "FROM daily_vitals WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    vitals_map = {r["local_date"]: r for r in vitals_rows}

    scores_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, recovery_z, recovery_components, flags, inputs "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    scores_map = {r["local_date"]: r for r in scores_rows}

    hrv_series: list[dict[str, Any]] = []
    rhr_series: list[dict[str, Any]] = []

    curr_d = start_date
    latest_hrv_band: list[float] | None = None
    latest_rhr_band: list[float] | None = None

    while curr_d <= target_date:
        v = vitals_map.get(curr_d)
        sc = scores_map.get(curr_d)

        # Baseline parsing from inputs JSONB
        inputs_data = sc["inputs"] if sc and sc.get("inputs") else None
        if isinstance(inputs_data, str):
            inputs_data = json.loads(inputs_data)

        baselines = inputs_data.get("baselines", {}) if isinstance(inputs_data, dict) else {}

        # HRV band = exp(center +- scale)
        hrv_band_lo: float | None = None
        hrv_band_hi: float | None = None
        if baselines.get("hrv"):
            c, s = baselines["hrv"]
            hrv_band_lo = round(math.exp(c - s), 1)
            hrv_band_hi = round(math.exp(c + s), 1)
            latest_hrv_band = [hrv_band_lo, hrv_band_hi]

        # RHR band = center +- scale
        rhr_band_lo: float | None = None
        rhr_band_hi: float | None = None
        if baselines.get("rhr"):
            c, s = baselines["rhr"]
            rhr_band_lo = round(c - s, 1)
            rhr_band_hi = round(c + s, 1)
            latest_rhr_band = [rhr_band_lo, rhr_band_hi]

        hrv_val = float(v["hrv_rmssd_ms"]) if v and v["hrv_rmssd_ms"] is not None else None
        rhr_val = float(v["resting_hr"]) if v and v["resting_hr"] is not None else None

        hrv_series.append(
            {
                "date": curr_d.isoformat(),
                "val": hrv_val,
                "band_lo": hrv_band_lo,
                "band_hi": hrv_band_hi,
            }
        )
        rhr_series.append(
            {
                "date": curr_d.isoformat(),
                "val": rhr_val,
                "band_lo": rhr_band_lo,
                "band_hi": rhr_band_hi,
            }
        )
        curr_d += dt.timedelta(days=1)

    today_sc = scores_map.get(target_date)
    today_v = vitals_map.get(target_date)

    recovery = today_sc["recovery"] if today_sc else None
    zone = recovery_zone(recovery) if recovery is not None else None
    recovery_z = (
        float(today_sc["recovery_z"])
        if today_sc and today_sc.get("recovery_z") is not None
        else None
    )

    components = today_sc["recovery_components"] if today_sc else None
    if isinstance(components, str):
        components = json.loads(components)
    flags = today_sc["flags"] if today_sc else []

    # Czech summary text matching zone
    summary: str
    if zone == "green":
        summary = "Tělo je připravené na zátěž. HRV je nad tvým normálem a klidový tep pod ním."
    elif zone == "yellow":
        summary = "Běžný stav organismu. Můžeš udržovat obvyklou tréninkovou zátěž."
    elif zone == "red":
        summary = (
            "Organismus vykazuje známky přetížení nebo únavy. "
            "Doporučujeme klidový režim nebo lehkou regeneraci."
        )
    else:
        summary = "Recovery se počítá po synchronizaci noci a alespoň 7 dnech měření."

    return {
        "date": target_date.isoformat(),
        "recovery": recovery,
        "zone": zone,
        "recovery_z": recovery_z,
        "summary": summary,
        "components": components or [],
        "flags": flags,
        "current_hrv": float(today_v["hrv_rmssd_ms"])
        if today_v and today_v["hrv_rmssd_ms"] is not None
        else None,
        "current_rhr": float(today_v["resting_hr"])
        if today_v and today_v["resting_hr"] is not None
        else None,
        "hrv_band": latest_hrv_band,
        "rhr_band": latest_rhr_band,
        "hrv_series": hrv_series,
        "rhr_series": rhr_series,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 3. /api/sleep
# -----------------------------------------------------------------------------


def query_sleep(conn: Connection, date_str: str | None = None) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    settings = get_settings()

    # Main sleep session for the night ending on target_date
    main_session = (
        conn.execute(
            text(
                "SELECT id, start_ts, end_ts, duration_min, time_in_bed_min, efficiency "
                "FROM sleep_sessions "
                "WHERE local_date = :d AND is_main = true "
                "ORDER BY start_ts DESC LIMIT 1"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    # Fallback to any sleep session if no is_main
    if not main_session:
        main_session = (
            conn.execute(
                text(
                    "SELECT id, start_ts, end_ts, duration_min, time_in_bed_min, efficiency "
                    "FROM sleep_sessions WHERE local_date = :d "
                    "ORDER BY duration_min DESC NULLS LAST LIMIT 1"
                ),
                {"d": target_date},
            )
            .mappings()
            .first()
        )

    stages_list: list[dict[str, Any]] = []
    wake_count = 0
    stage_totals: dict[str, int] = {"awake": 0, "rem": 0, "light": 0, "deep": 0}

    if main_session:
        stg_rows = (
            conn.execute(
                text(
                    "SELECT stage, start_ts, end_ts "
                    "FROM sleep_stages WHERE session_id = :sid ORDER BY start_ts"
                ),
                {"sid": main_session["id"]},
            )
            .mappings()
            .all()
        )

        for s in stg_rows:
            stg_name = s["stage"]
            dur_sec = int((s["end_ts"] - s["start_ts"]).total_seconds())
            dur_m = round(dur_sec / 60)
            stages_list.append(
                {
                    "stage": stg_name,
                    "start_ts": jsonable(s["start_ts"]),
                    "end_ts": jsonable(s["end_ts"]),
                    "duration_sec": dur_sec,
                    "duration_min": dur_m,
                }
            )
            if stg_name in stage_totals:
                stage_totals[stg_name] += dur_m
            if stg_name == "awake":
                wake_count += 1

    # Sleep score and need from daily_scores
    score_row = _get_daily_score_row(conn, target_date)

    # Base need from app_settings or settings
    base_setting = conn.execute(
        text("SELECT value FROM app_settings WHERE key = 'sleep_need_base_min'")
    ).scalar()
    base_need = int(base_setting) if base_setting is not None else settings.sleep_need_base_min

    # Strain bonus from strain on day D-1
    prev_d = target_date - dt.timedelta(days=1)
    prev_score = _get_daily_score_row(conn, prev_d)
    prev_strain = (
        float(prev_score["strain"]) if prev_score and prev_score.get("strain") is not None else None
    )
    strain_bonus_min = round(max(0.0, prev_strain - 7.0) * 3) if prev_strain is not None else 0

    # Naps credit from naps on day D-1
    nap_mins = conn.execute(
        text(
            "SELECT coalesce(sum(duration_min), 0) FROM sleep_sessions "
            "WHERE local_date = :d AND is_main = false"
        ),
        {"d": prev_d},
    ).scalar_one()
    nap_credit_min = int(nap_mins)

    sleep_debt_min = (
        score_row["sleep_debt_min"]
        if score_row and score_row.get("sleep_debt_min") is not None
        else 0
    )
    sleep_need_min = (
        score_row["sleep_need_min"]
        if score_row and score_row.get("sleep_need_min") is not None
        else (base_need + sleep_debt_min + strain_bonus_min - nap_credit_min)
    )

    # Last 7 nights
    week_start = target_date - dt.timedelta(days=6)
    week_scores = (
        conn.execute(
            text(
                "SELECT local_date, sleep_actual_min, sleep_need_min, sleep_performance "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_map = {r["local_date"]: r for r in week_scores}

    week_list: list[dict[str, Any]] = []
    w_d = week_start
    while w_d <= target_date:
        w_sc = week_map.get(w_d)
        actual = (
            w_sc["sleep_actual_min"] if w_sc and w_sc.get("sleep_actual_min") is not None else None
        )
        need = w_sc["sleep_need_min"] if w_sc and w_sc.get("sleep_need_min") is not None else None
        week_list.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "actual_min": actual,
                "need_min": need,
                "performance": w_sc["sleep_performance"] if w_sc else None,
            }
        )
        w_d += dt.timedelta(days=1)

    # Tonight's plan
    tonight_plan = {
        "planned_bedtime": jsonable(score_row["planned_bedtime"]) if score_row else None,
        "planned_wake": jsonable(score_row["planned_wake"]) if score_row else None,
        "sleep_need_min": score_row["sleep_need_min"] if score_row else base_need,
        "today_strain": float(score_row["strain"])
        if score_row and score_row.get("strain") is not None
        else None,
        "today_strain_bonus_min": (
            round(max(0.0, float(score_row["strain"]) - 7.0) * 3)
            if score_row and score_row.get("strain") is not None
            else 0
        ),
    }

    return {
        "date": target_date.isoformat(),
        "session": {
            "start_ts": jsonable(main_session["start_ts"]) if main_session else None,
            "end_ts": jsonable(main_session["end_ts"]) if main_session else None,
            "duration_min": main_session["duration_min"] if main_session else None,
            "time_in_bed_min": main_session["time_in_bed_min"] if main_session else None,
            "efficiency": main_session["efficiency"] if main_session else None,
            "wake_count": wake_count,
        },
        "performance": score_row["sleep_performance"] if score_row else None,
        "consistency": score_row["sleep_consistency"] if score_row else None,
        "stages": stages_list,
        "stage_totals": stage_totals,
        "need_breakdown": {
            "base_need_min": base_need,
            "debt_min": sleep_debt_min,
            "prev_strain": prev_strain,
            "strain_bonus_min": strain_bonus_min,
            "nap_credit_min": nap_credit_min,
            "total_need_min": sleep_need_min,
        },
        "week": week_list,
        "tonight_plan": tonight_plan,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 4. /api/strain
# -----------------------------------------------------------------------------


def query_strain(conn: Connection, date_str: str | None = None) -> dict[str, Any]:
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
    zone_minutes = score_row["zone_minutes"] if score_row else None
    if isinstance(zone_minutes, str):
        zone_minutes = json.loads(zone_minutes)

    # Rest and HR max from inputs JSON or defaults
    inputs_data = score_row["inputs"] if score_row and score_row.get("inputs") else None
    if isinstance(inputs_data, str):
        inputs_data = json.loads(inputs_data)
    rest_hr = float(inputs_data.get("rest_hr", 60.0)) if isinstance(inputs_data, dict) else 60.0
    hr_max = (
        float(inputs_data.get("hr_max", settings.effective_hr_max()))
        if isinstance(inputs_data, dict)
        else float(settings.effective_hr_max())
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
            }
        )

    # Last 7 days strain
    week_start = target_date - dt.timedelta(days=6)
    week_strains_rows = (
        conn.execute(
            text(
                "SELECT local_date, strain FROM daily_scores "
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_strain_map = {r["local_date"]: r["strain"] for r in week_strains_rows}

    week_strains: list[dict[str, Any]] = []
    w_d = week_start
    sum_strain = 0.0
    cnt_strain = 0
    while w_d <= target_date:
        val = week_strain_map.get(w_d)
        f_val = float(val) if val is not None else None
        if f_val is not None:
            sum_strain += f_val
            cnt_strain += 1
        week_strains.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "strain": f_val,
            }
        )
        w_d += dt.timedelta(days=1)

    avg_week_strain = round(sum_strain / cnt_strain, 1) if cnt_strain > 0 else None

    return {
        "date": target_date.isoformat(),
        "strain": strain,
        "cardio_load": cardio_load,
        "muscular_load": muscular_load,
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


def query_nutrition(conn: Connection, date_str: str | None = None) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    settings = get_settings()
    tz = settings.tz

    # Targets in force
    targets = current_targets(conn, target_date)

    # Totals on target_date
    totals_row = (
        conn.execute(
            text(
                "SELECT round(sum(kcal)) AS kcal, "
                "       round(sum(protein_g), 1) AS protein_g, "
                "       round(sum(carbs_g), 1) AS carbs_g, "
                "       round(sum(fat_g), 1) AS fat_g, "
                "       round(sum(fiber_g), 1) AS fiber_g "
                "FROM nutrition_entries WHERE local_date = :d AND deleted_at IS NULL"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    kcal = float(totals_row["kcal"]) if totals_row and totals_row["kcal"] is not None else 0.0
    protein_g = (
        float(totals_row["protein_g"])
        if totals_row and totals_row["protein_g"] is not None
        else 0.0
    )
    carbs_g = (
        float(totals_row["carbs_g"]) if totals_row and totals_row["carbs_g"] is not None else 0.0
    )
    fat_g = float(totals_row["fat_g"]) if totals_row and totals_row["fat_g"] is not None else 0.0
    fiber_g = (
        float(totals_row["fiber_g"]) if totals_row and totals_row["fiber_g"] is not None else 0.0
    )

    t_kcal = targets.get("kcal") if targets else None
    target_kcal = float(t_kcal) if t_kcal is not None else None
    t_prot = targets.get("protein_g") if targets else None
    target_protein = float(t_prot) if t_prot is not None else None
    t_carbs = targets.get("carbs_g") if targets else None
    target_carbs = float(t_carbs) if t_carbs is not None else None
    t_fat = targets.get("fat_g") if targets else None
    target_fat = float(t_fat) if t_fat is not None else None
    t_fiber = targets.get("fiber_g") if targets else None
    target_fiber = float(t_fiber) if t_fiber is not None else None

    # Meals grouped by meal type
    meal_entries = (
        conn.execute(
            text(
                "SELECT id, meal, description AS name, grams, kcal, "
                "       protein_g, carbs_g, fat_g, fiber_g, ts AS logged_at "
                "FROM nutrition_entries WHERE local_date = :d AND deleted_at IS NULL "
                "ORDER BY ts ASC, id ASC"
            ),
            {"d": target_date},
        )
        .mappings()
        .all()
    )

    meals_dict: dict[str, dict[str, Any]] = {}
    last_logged_time: str | None = None

    for m in meal_entries:
        m_key = m["meal"] or "other"
        if m_key not in meals_dict:
            meals_dict[m_key] = {
                "key": m_key,
                "name": MEAL_LABELS.get(m_key, m_key.capitalize()),
                "time": None,
                "kcal": 0,
                "items": [],
            }
        m_logged = m["logged_at"]
        if m_logged:
            local_logged = m_logged.astimezone(tz)
            time_str = f"{local_logged.hour:02d}:{local_logged.minute:02d}"
            meals_dict[m_key]["time"] = time_str
            last_logged_time = time_str

        item_kcal = round(float(m["kcal"] or 0))
        meals_dict[m_key]["kcal"] += item_kcal
        meals_dict[m_key]["items"].append(
            {
                "name": m["name"],
                "protein_g": float(m["protein_g"]) if m["protein_g"] else 0.0,
                "kcal": item_kcal,
            }
        )

    meals_list = list(meals_dict.values())

    # TDEE estimate (14 days window)
    tdee_res, _, _ = estimate_from_db(conn, target_date, window_days=14)
    tdee = tdee_res.tdee

    balance = round(kcal - tdee) if tdee is not None else None

    # 14-day mean balance
    past_14_start = target_date - dt.timedelta(days=13)
    past_14_kcals = conn.execute(
        text(
            "SELECT avg(kcal) FROM v_nutrition_daily "
            "WHERE local_date BETWEEN :s AND :e AND kcal IS NOT NULL"
        ),
        {"s": past_14_start, "e": target_date},
    ).scalar()
    avg_14_intake = float(past_14_kcals) if past_14_kcals is not None else None
    mean_14_balance = (
        round(avg_14_intake - tdee) if avg_14_intake is not None and tdee is not None else None
    )
    expected_weekly_change = (
        round(mean_14_balance * 7.0 / 7700.0, 2) if mean_14_balance is not None else None
    )

    # Actual weight trend rate
    wt_rate = conn.execute(
        text(
            "SELECT weekly_rate_kg FROM v_weight_trend WHERE local_date <= :d "
            "ORDER BY local_date DESC LIMIT 1"
        ),
        {"d": target_date},
    ).scalar()
    actual_weekly_change = float(wt_rate) if wt_rate is not None else None

    # Last 7 days kcal with protein hit
    week_start = target_date - dt.timedelta(days=6)
    week_rows = (
        conn.execute(
            text(
                "SELECT local_date, kcal, protein_g, target_kcal, target_protein_g "
                "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_map = {r["local_date"]: r for r in week_rows}

    week_list: list[dict[str, Any]] = []
    w_d = week_start
    protein_hits = 0
    while w_d <= target_date:
        r = week_map.get(w_d)
        d_kcal = float(r["kcal"]) if r and r["kcal"] is not None else None
        d_prot = float(r["protein_g"]) if r and r["protein_g"] is not None else None
        d_target_prot = (
            float(r["target_protein_g"])
            if r and r["target_protein_g"] is not None
            else target_protein
        )
        hit = bool(d_prot is not None and d_target_prot is not None and d_prot >= d_target_prot)
        if hit:
            protein_hits += 1
        week_list.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "kcal": d_kcal,
                "protein_hit": hit,
            }
        )
        w_d += dt.timedelta(days=1)

    return {
        "date": target_date.isoformat(),
        "kcal": round(kcal),
        "target_kcal": round(target_kcal) if target_kcal else None,
        "remaining_kcal": round(target_kcal - kcal) if target_kcal else None,
        "phase": targets.get("phase") if targets else None,
        "weekly_rate_target_kg": (targets.get("weekly_rate_min_kg") if targets else None),
        "macros": [
            {
                "name": "Bílkoviny",
                "val": protein_g,
                "target": target_protein,
                "unit": "g",
                "color": "#FF8A65",
            },
            {
                "name": "Sacharidy",
                "val": carbs_g,
                "target": target_carbs,
                "unit": "g",
                "color": "#F5C542",
            },
            {"name": "Tuky", "val": fat_g, "target": target_fat, "unit": "g", "color": "#4D9BE8"},
            {
                "name": "Vláknina",
                "val": fiber_g,
                "target": target_fiber,
                "unit": "g",
                "color": "#5FE39E",
            },
        ],
        "meals": meals_list,
        "meals_count": len(meals_list),
        "last_logged_time": last_logged_time,
        "energy_balance": {
            "intake": round(kcal),
            "tdee": round(tdee) if tdee else None,
            "balance": balance,
            "mean_14_balance": mean_14_balance,
            "expected_weekly_change": expected_weekly_change,
            "actual_weekly_change": actual_weekly_change,
        },
        "week": week_list,
        "protein_hits_days": protein_hits,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 6. /api/trends
# -----------------------------------------------------------------------------


def query_trends(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    start_date = target_date - dt.timedelta(days=days - 1)

    # 1. Daily scores
    sc_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, strain, sleep_actual_min, sleep_performance "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    sc_map = {r["local_date"]: r for r in sc_rows}

    # 2. Vitals
    vt_rows = (
        conn.execute(
            text(
                "SELECT local_date, resting_hr, hrv_rmssd_ms "
                "FROM daily_vitals WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    vt_map = {r["local_date"]: r for r in vt_rows}

    # 3. Weight trend
    wt_rows = (
        conn.execute(
            text(
                "SELECT local_date, weight_kg, avg_7d_kg, trend_kg, weekly_rate_kg "
                "FROM v_weight_trend WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    wt_map = {r["local_date"]: r for r in wt_rows}

    # 4. Nutrition
    nt_rows = (
        conn.execute(
            text(
                "SELECT local_date, kcal, protein_g, target_kcal "
                "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    nt_map = {r["local_date"]: r for r in nt_rows}

    # 5. Acute:chronic workload calculation
    # Query 28 days of daily load or strain
    acwr_28_start = target_date - dt.timedelta(days=27)
    past_28_strains = (
        conn.execute(
            text(
                "SELECT strain FROM daily_scores "
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": acwr_28_start, "e": target_date},
        )
        .scalars()
        .all()
    )
    strain_loads = [float(s) for s in past_28_strains if s is not None]
    acwr = calculate_acute_chronic(strain_loads)

    # Compile daily points
    rec_points: list[dict[str, Any]] = []
    hrv_points: list[dict[str, Any]] = []
    rhr_points: list[dict[str, Any]] = []
    sleep_points: list[dict[str, Any]] = []
    strain_points: list[dict[str, Any]] = []
    weight_points: list[dict[str, Any]] = []
    kcal_points: list[dict[str, Any]] = []

    curr_d = start_date
    targets = current_targets(conn, target_date)
    target_kcal_val = targets.get("kcal") if targets else 2400

    while curr_d <= target_date:
        sc = sc_map.get(curr_d)
        vt = vt_map.get(curr_d)
        wt = wt_map.get(curr_d)
        nt = nt_map.get(curr_d)

        r_val = sc["recovery"] if sc and sc["recovery"] is not None else None
        rec_points.append({"date": curr_d.isoformat(), "val": r_val})

        hrv_val = float(vt["hrv_rmssd_ms"]) if vt and vt["hrv_rmssd_ms"] is not None else None
        hrv_points.append({"date": curr_d.isoformat(), "val": hrv_val})

        rhr_val = float(vt["resting_hr"]) if vt and vt["resting_hr"] is not None else None
        rhr_points.append({"date": curr_d.isoformat(), "val": rhr_val})

        sl_val = sc["sleep_actual_min"] if sc and sc["sleep_actual_min"] is not None else None
        sl_perf = sc["sleep_performance"] if sc and sc["sleep_performance"] is not None else None
        sleep_points.append({"date": curr_d.isoformat(), "val": sl_val, "perf": sl_perf})

        st_val = float(sc["strain"]) if sc and sc["strain"] is not None else None
        strain_points.append({"date": curr_d.isoformat(), "val": st_val})

        w_raw = float(wt["weight_kg"]) if wt and wt["weight_kg"] is not None else None
        w_avg = float(wt["avg_7d_kg"]) if wt and wt["avg_7d_kg"] is not None else None
        weight_points.append({"date": curr_d.isoformat(), "raw": w_raw, "avg": w_avg})

        k_val = float(nt["kcal"]) if nt and nt["kcal"] is not None else None
        p_val = float(nt["protein_g"]) if nt and nt["protein_g"] is not None else None
        kcal_points.append({"date": curr_d.isoformat(), "val": k_val, "protein": p_val})

        curr_d += dt.timedelta(days=1)

    # Averages
    valid_recs = [p["val"] for p in rec_points if p["val"] is not None]
    avg_rec = round(sum(valid_recs) / len(valid_recs)) if valid_recs else None
    green_recs = sum(1 for v in valid_recs if v >= 67)

    valid_hrvs = [p["val"] for p in hrv_points if p["val"] is not None]
    avg_hrv = round(sum(valid_hrvs) / len(valid_hrvs), 1) if valid_hrvs else None

    valid_rhrs = [p["val"] for p in rhr_points if p["val"] is not None]
    avg_rhr = round(sum(valid_rhrs) / len(valid_rhrs), 1) if valid_rhrs else None

    valid_sleeps = [p["val"] for p in sleep_points if p["val"] is not None]
    avg_sleep_m = round(sum(valid_sleeps) / len(valid_sleeps)) if valid_sleeps else None
    valid_perfs = [p["perf"] for p in sleep_points if p["perf"] is not None]
    avg_perf = round(sum(valid_perfs) / len(valid_perfs)) if valid_perfs else None

    valid_strains = [p["val"] for p in strain_points if p["val"] is not None]
    avg_strain = round(sum(valid_strains) / len(valid_strains), 1) if valid_strains else None

    valid_weights = [p["avg"] for p in weight_points if p["avg"] is not None]
    last_weight = valid_weights[-1] if valid_weights else None
    weight_rate = None
    if len(valid_weights) >= 7:
        weight_rate = round(valid_weights[-1] - valid_weights[-7], 2)
    elif len(valid_weights) >= 2:
        weight_rate = round(valid_weights[-1] - valid_weights[0], 2)

    valid_kcals = [p["val"] for p in kcal_points if p["val"] is not None]
    avg_kcal = round(sum(valid_kcals) / len(valid_kcals)) if valid_kcals else None
    valid_proteins = [p["protein"] for p in kcal_points if p["protein"] is not None]
    avg_protein = round(sum(valid_proteins) / len(valid_proteins)) if valid_proteins else None

    return {
        "days": days,
        "date": target_date.isoformat(),
        "recovery": {
            "avg": avg_rec,
            "green_count": green_recs,
            "series": rec_points,
        },
        "hrv": {
            "avg": avg_hrv,
            "series": hrv_points,
        },
        "rhr": {
            "avg": avg_rhr,
            "series": rhr_points,
        },
        "sleep": {
            "avg_min": avg_sleep_m,
            "avg_perf": avg_perf,
            "series": sleep_points,
        },
        "strain": {
            "avg": avg_strain,
            "acwr": acwr,
            "series": strain_points,
        },
        "weight": {
            "last": last_weight,
            "rate": weight_rate,
            "series": weight_points,
        },
        "kcal": {
            "avg": avg_kcal,
            "avg_protein": avg_protein,
            "target": target_kcal_val,
            "series": kcal_points,
        },
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 7. /api/calendar
# -----------------------------------------------------------------------------


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
        cells.append({"day": None, "has_data": False})

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


def query_journal(conn: Connection, days: int = 60, date_str: str | None = None) -> dict[str, Any]:
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

    return {
        "date": target_date.isoformat(),
        "yesterday_date": yesterday_date.isoformat(),
        "yesterday_weekday": CZECH_WEEKDAYS[yesterday_date.weekday()],
        "logged_time": logged_time,
        "yesterday": yesterday_chips,
        "insights": insights_formatted,
        "insufficient": insufficient_formatted,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 9. /api/report
# -----------------------------------------------------------------------------


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
                    "       round(avg(sleep_actual_min)) AS avg_sleep, "
                    "       round(avg(sleep_consistency)) AS avg_consist "
                    "FROM daily_scores WHERE local_date BETWEEN :s AND :e"
                ),
                {"s": s, "e": e},
            )
            .mappings()
            .first()
        )

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
