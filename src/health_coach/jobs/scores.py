"""Worker job for daily WHOOP-style scores (recovery, strain, sleep)."""

import datetime as dt
import json
import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from health_coach.analytics.scores import (
    ALGO_VERSION,
    DEFAULT_RESTING_HR,
    FLOOR_BREATHING_RATE,
    FLOOR_LN_HRV,
    FLOOR_RHR,
    FLOOR_SKIN_TEMP,
    ExerciseSessionData,
    SleepNightData,
    StrengthSessionData,
    StrengthSetData,
    calculate_bedtime_plan,
    calculate_day_strain,
    calculate_muscular_caps,
    calculate_recovery,
    calculate_sleep_consistency,
    calculate_sleep_debt,
    calculate_sleep_need,
    robust_baseline,
)
from health_coach.analytics.sleep import sleep_midpoint_minutes
from health_coach.config import get_settings
from health_coach.ingest import state
from health_coach.jobs.runner import run_job
from health_coach.profile import Profile, load_profile, profile_from

log = logging.getLogger(__name__)

_UPSERT_DAILY_SCORE = """
INSERT INTO daily_scores (
    local_date, recovery, recovery_z, recovery_components, flags,
    strain, cardio_load, muscular_load, zone_minutes, activities,
    strain_target_low, strain_target_high, sleep_need_min,
    sleep_actual_min, sleep_debt_min, sleep_performance,
    sleep_efficiency, sleep_consistency, planned_bedtime,
    planned_wake, inputs, algo_version, source
) VALUES (
    :local_date, :recovery, :recovery_z, CAST(:recovery_components AS jsonb),
    :flags, :strain, :cardio_load, :muscular_load, CAST(:zone_minutes AS jsonb),
    CAST(:activities AS jsonb), :strain_target_low, :strain_target_high,
    :sleep_need_min, :sleep_actual_min, :sleep_debt_min, :sleep_performance,
    :sleep_efficiency, :sleep_consistency, :planned_bedtime, :planned_wake,
    CAST(:inputs AS jsonb), :algo_version, 'worker'
) ON CONFLICT (local_date) DO UPDATE SET
    recovery = EXCLUDED.recovery,
    recovery_z = EXCLUDED.recovery_z,
    recovery_components = EXCLUDED.recovery_components,
    flags = EXCLUDED.flags,
    strain = EXCLUDED.strain,
    cardio_load = EXCLUDED.cardio_load,
    muscular_load = EXCLUDED.muscular_load,
    zone_minutes = EXCLUDED.zone_minutes,
    activities = EXCLUDED.activities,
    strain_target_low = EXCLUDED.strain_target_low,
    strain_target_high = EXCLUDED.strain_target_high,
    sleep_need_min = EXCLUDED.sleep_need_min,
    sleep_actual_min = EXCLUDED.sleep_actual_min,
    sleep_debt_min = EXCLUDED.sleep_debt_min,
    sleep_performance = EXCLUDED.sleep_performance,
    sleep_efficiency = EXCLUDED.sleep_efficiency,
    sleep_consistency = EXCLUDED.sleep_consistency,
    planned_bedtime = EXCLUDED.planned_bedtime,
    planned_wake = EXCLUDED.planned_wake,
    inputs = EXCLUDED.inputs,
    algo_version = EXCLUDED.algo_version,
    updated_at = now()
"""


@dataclass(frozen=True)
class _VitalsContext:
    hrv_ms: float | None
    rhr: float | None
    breathing_rate: float | None
    skin_temp_delta: float | None
    spo2_avg: float | None
    prev_rhr: float | None
    prev_rmssd: float | None
    hrv_baseline: tuple[float, float] | None
    rhr_baseline: tuple[float, float] | None
    breathing_baseline: tuple[float, float] | None
    skin_temp_baseline: tuple[float, float] | None
    rest_hr_anchor: float


def _load_vitals(
    conn: Connection,
    day: dt.date,
    prev_day: dt.date,
    d30: dt.date,
    d6: dt.date,
) -> _VitalsContext:
    baseline_rows = conn.execute(
        text(
            "SELECT local_date, resting_hr, hrv_rmssd_ms, breathing_rate, skin_temp_delta "
            "FROM daily_vitals WHERE local_date BETWEEN :d30 AND :d1 "
            "ORDER BY local_date"
        ),
        {"d30": d30, "d1": prev_day},
    ).all()

    hrv_vals = [
        math.log(float(r.hrv_rmssd_ms))
        for r in baseline_rows
        if r.hrv_rmssd_ms is not None and float(r.hrv_rmssd_ms) > 0
    ]
    rhr_vals = [float(r.resting_hr) for r in baseline_rows if r.resting_hr is not None]
    br_vals = [float(r.breathing_rate) for r in baseline_rows if r.breathing_rate is not None]
    temp_vals = [float(r.skin_temp_delta) for r in baseline_rows if r.skin_temp_delta is not None]

    hrv_baseline = robust_baseline(hrv_vals, floor=FLOOR_LN_HRV)
    rhr_baseline = robust_baseline(rhr_vals, floor=FLOOR_RHR)
    breathing_baseline = robust_baseline(br_vals, floor=FLOOR_BREATHING_RATE)
    skin_temp_baseline = robust_baseline(temp_vals, floor=FLOOR_SKIN_TEMP)

    vitals_row = conn.execute(
        text(
            "SELECT resting_hr, hrv_rmssd_ms, breathing_rate, skin_temp_delta, spo2_avg "
            "FROM daily_vitals WHERE local_date = :d"
        ),
        {"d": day},
    ).first()

    prev_vitals_row = conn.execute(
        text("SELECT resting_hr, hrv_rmssd_ms FROM daily_vitals WHERE local_date = :d"),
        {"d": prev_day},
    ).first()

    rhr_7d_rows = (
        conn.execute(
            text(
                "SELECT resting_hr FROM daily_vitals "
                "WHERE local_date BETWEEN :d6 AND :d AND resting_hr IS NOT NULL"
            ),
            {"d6": d6, "d": day},
        )
        .scalars()
        .all()
    )
    rest_hr_anchor = (
        float(statistics.median([float(x) for x in rhr_7d_rows]))
        if rhr_7d_rows
        else DEFAULT_RESTING_HR
    )

    return _VitalsContext(
        hrv_ms=float(vitals_row.hrv_rmssd_ms) if vitals_row and vitals_row.hrv_rmssd_ms else None,
        rhr=float(vitals_row.resting_hr)
        if vitals_row and vitals_row.resting_hr is not None
        else None,
        breathing_rate=(
            float(vitals_row.breathing_rate)
            if vitals_row and vitals_row.breathing_rate is not None
            else None
        ),
        skin_temp_delta=(
            float(vitals_row.skin_temp_delta)
            if vitals_row and vitals_row.skin_temp_delta is not None
            else None
        ),
        spo2_avg=(
            float(vitals_row.spo2_avg) if vitals_row and vitals_row.spo2_avg is not None else None
        ),
        prev_rhr=(
            float(prev_vitals_row.resting_hr)
            if prev_vitals_row and prev_vitals_row.resting_hr is not None
            else None
        ),
        prev_rmssd=(
            float(prev_vitals_row.hrv_rmssd_ms)
            if prev_vitals_row and prev_vitals_row.hrv_rmssd_ms is not None
            else None
        ),
        hrv_baseline=hrv_baseline,
        rhr_baseline=rhr_baseline,
        breathing_baseline=breathing_baseline,
        skin_temp_baseline=skin_temp_baseline,
        rest_hr_anchor=rest_hr_anchor,
    )


@dataclass(frozen=True)
class _SleepContext:
    has_main_sleep: bool
    actual_min: int | None
    efficiency_val: int | None
    sleep_debt: int
    sleep_need: int
    sleep_perf: int | None
    consistency_val: int | None
    debt_history: list[SleepNightData]
    today_naps: int
    recent_effs: list[float]
    recent_wakes: list[dt.time]


def _load_sleep(
    conn: Connection,
    day: dt.date,
    prev_day: dt.date,
    d14: dt.date,
    d6: dt.date,
    d13: dt.date,
    tz: ZoneInfo,
    base_need: int,
    is_today: bool,
) -> _SleepContext:
    main_sleep = conn.execute(
        text(
            "SELECT id, duration_min, time_in_bed_min, efficiency, start_ts, end_ts "
            "FROM sleep_sessions WHERE local_date = :d AND is_main "
            "ORDER BY duration_min DESC LIMIT 1"
        ),
        {"d": day},
    ).first()

    actual_min = int(main_sleep.duration_min) if main_sleep else None
    efficiency_val = None
    if main_sleep:
        if main_sleep.efficiency is not None:
            efficiency_val = int(main_sleep.efficiency)
        elif main_sleep.time_in_bed_min and main_sleep.time_in_bed_min > 0:
            efficiency_val = round(main_sleep.duration_min / main_sleep.time_in_bed_min * 100)

    prev_naps = conn.execute(
        text(
            "SELECT coalesce(sum(duration_min), 0) FROM sleep_sessions "
            "WHERE local_date = :prev_d AND NOT is_main"
        ),
        {"prev_d": prev_day},
    ).scalar_one()

    prev_strain_val = conn.execute(
        text("SELECT strain FROM daily_scores WHERE local_date = :prev_d"),
        {"prev_d": prev_day},
    ).scalar_one_or_none()

    # Sleep debt history: k = 1..14 nights ending on D-14..D-1
    # Use DISTINCT ON (local_date) so a date with two main sessions counts once (longest)
    debt_rows = conn.execute(
        text(
            "SELECT DISTINCT ON (s.local_date) s.local_date, s.duration_min, d.sleep_need_min "
            "FROM sleep_sessions s "
            "LEFT JOIN daily_scores d ON d.local_date = s.local_date "
            "WHERE s.local_date BETWEEN :d14 AND :d1 AND s.is_main "
            "ORDER BY s.local_date, s.duration_min DESC"
        ),
        {"d14": d14, "d1": prev_day},
    ).all()

    debt_history = [
        SleepNightData(
            k=(day - r.local_date).days,
            need=r.sleep_need_min,
            actual=r.duration_min,
        )
        for r in debt_rows
    ]
    sleep_debt = calculate_sleep_debt(debt_history, base_need=base_need)

    sleep_need = calculate_sleep_need(
        base=base_need,
        debt=sleep_debt,
        prev_strain=float(prev_strain_val) if prev_strain_val is not None else None,
        prev_naps=int(prev_naps),
    )

    sleep_perf = min(100, round(actual_min / sleep_need * 100)) if actual_min is not None else None

    # Consistency: SD of midpoints of last 7 main sleeps (D-6 to D)
    consistency_rows = conn.execute(
        text(
            "SELECT start_ts, end_ts FROM sleep_sessions "
            "WHERE local_date BETWEEN :d6 AND :d AND is_main "
            "ORDER BY local_date"
        ),
        {"d6": d6, "d": day},
    ).all()

    midpoints = [
        sleep_midpoint_minutes(r.start_ts, r.end_ts, tz)
        for r in consistency_rows
        if r.start_ts and r.end_ts
    ]
    consistency_val = calculate_sleep_consistency(midpoints)

    today_naps = 0
    recent_effs: list[float] = []
    recent_wakes: list[dt.time] = []
    if is_today:
        today_naps = conn.execute(
            text(
                "SELECT coalesce(sum(duration_min), 0) FROM sleep_sessions "
                "WHERE local_date = :d AND NOT is_main"
            ),
            {"d": day},
        ).scalar_one()

        recent_eff_rows = conn.execute(
            text(
                "SELECT efficiency, duration_min, time_in_bed_min FROM sleep_sessions "
                "WHERE local_date BETWEEN :d6 AND :d AND is_main"
            ),
            {"d6": d6, "d": day},
        ).all()
        for r in recent_eff_rows:
            if r.efficiency is not None:
                recent_effs.append(float(r.efficiency))
            elif r.time_in_bed_min and r.time_in_bed_min > 0:
                recent_effs.append(round(r.duration_min / r.time_in_bed_min * 100))

        recent_wake_rows = (
            conn.execute(
                text(
                    "SELECT end_ts FROM sleep_sessions "
                    "WHERE local_date BETWEEN :d13 AND :d AND is_main"
                ),
                {"d13": d13, "d": day},
            )
            .scalars()
            .all()
        )
        recent_wakes = [r.astimezone(tz).time() for r in recent_wake_rows if r]

    return _SleepContext(
        has_main_sleep=main_sleep is not None,
        actual_min=actual_min,
        efficiency_val=efficiency_val,
        sleep_debt=sleep_debt,
        sleep_need=sleep_need,
        sleep_perf=sleep_perf,
        consistency_val=consistency_val,
        debt_history=debt_history,
        today_naps=int(today_naps),
        recent_effs=recent_effs,
        recent_wakes=recent_wakes,
    )


def _load_hr_minutes(
    conn: Connection,
    day: dt.date,
    tz: ZoneInfo,
) -> list[tuple[dt.datetime, float]]:
    day_start = dt.datetime.combine(day, dt.time(0, 0), tz)
    day_end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), tz)
    hr_minute_rows = conn.execute(
        text(
            "SELECT date_trunc('minute', ts) AS minute_ts, "
            "       round(avg(bpm)::numeric, 1) AS avg_bpm "
            "FROM heart_rate_samples "
            "WHERE ts >= :start_ts AND ts < :end_ts "
            "GROUP BY 1 ORDER BY 1"
        ),
        {"start_ts": day_start, "end_ts": day_end},
    ).all()
    return [(r.minute_ts, float(r.avg_bpm)) for r in hr_minute_rows]


def _load_exercise(
    conn: Connection,
    day: dt.date,
) -> list[ExerciseSessionData]:
    ex_rows = conn.execute(
        text(
            "SELECT id, activity_type, start_ts, end_ts, duration_min, avg_hr, max_hr "
            "FROM exercise_sessions WHERE deleted_at IS NULL AND local_date = :d "
            "ORDER BY start_ts"
        ),
        {"d": day},
    ).all()
    return [
        ExerciseSessionData(
            id=r.id,
            kind="exercise",
            name=r.activity_type,
            start_ts=r.start_ts,
            end_ts=r.end_ts,
            duration_min=r.duration_min,
            avg_hr=r.avg_hr,
            max_hr=r.max_hr,
        )
        for r in ex_rows
    ]


def _load_strength(
    conn: Connection,
    day: dt.date,
    prev_day: dt.date,
    d30: dt.date,
) -> tuple[list[StrengthSessionData], tuple[float, float]]:
    st_rows = conn.execute(
        text(
            "SELECT id, routine_name, day_name, start_ts, end_ts FROM strength_sessions "
            "WHERE local_date = :d ORDER BY start_ts"
        ),
        {"d": day},
    ).all()

    st_session_ids = [r.id for r in st_rows]
    st_sets_by_session: dict[int, list[StrengthSetData]] = {}
    if st_session_ids:
        sets_rows = conn.execute(
            text(
                "SELECT session_id, set_no, reps, weight_kg, rir, rpe, is_warmup "
                "FROM strength_sets WHERE session_id = ANY(:ids) "
                "ORDER BY session_id, set_no"
            ),
            {"ids": st_session_ids},
        ).all()
        for s in sets_rows:
            st_sets_by_session.setdefault(s.session_id, []).append(
                StrengthSetData(
                    reps=float(s.reps) if s.reps is not None else None,
                    weight_kg=float(s.weight_kg) if s.weight_kg is not None else None,
                    rir=float(s.rir) if s.rir is not None else None,
                    rpe=float(s.rpe) if s.rpe is not None else None,
                    is_warmup=bool(s.is_warmup),
                )
            )

    strength_sessions = [
        StrengthSessionData(
            id=r.id,
            name=r.routine_name or r.day_name or "Strength",
            start_ts=r.start_ts,
            end_ts=r.end_ts,
            duration_min=None,
            sets=st_sets_by_session.get(r.id, []),
        )
        for r in st_rows
    ]

    hist_st_rows = conn.execute(
        text(
            "SELECT ss.id, ss.routine_name, ss.day_name, ss.start_ts, ss.end_ts, "
            "       st.reps, st.weight_kg, st.rir, st.rpe, st.is_warmup "
            "FROM strength_sessions ss "
            "JOIN strength_sets st ON st.session_id = ss.id "
            "WHERE ss.local_date BETWEEN :d30 AND :d1 "
            "ORDER BY ss.id, st.set_no"
        ),
        {"d30": d30, "d1": prev_day},
    ).all()

    hist_st_map: dict[int, StrengthSessionData] = {}
    for r in hist_st_rows:
        if r.id not in hist_st_map:
            hist_st_map[r.id] = StrengthSessionData(
                id=r.id,
                name=r.routine_name or r.day_name or "Strength",
                start_ts=r.start_ts,
                end_ts=r.end_ts,
                sets=[],
            )
        hist_st_map[r.id].sets.append(
            StrengthSetData(
                reps=float(r.reps) if r.reps is not None else None,
                weight_kg=float(r.weight_kg) if r.weight_kg is not None else None,
                rir=float(r.rir) if r.rir is not None else None,
                rpe=float(r.rpe) if r.rpe is not None else None,
                is_warmup=bool(r.is_warmup),
            )
        )

    caps = calculate_muscular_caps(list(hist_st_map.values()))
    return strength_sessions, caps


def load_app_settings(conn: Connection) -> dict[str, Any]:
    """Read app_settings into a dict."""
    rows = conn.execute(text("SELECT key, value FROM app_settings")).all()
    return {r.key: r.value for r in rows}


def compute_scores(
    engine: Engine,
    day: dt.date,
    base_need_min: int | None = None,
    alarm_time: dt.time | None = None,
    profile: Profile | None = None,
) -> None:
    """Compute and upsert daily score row for local_date `day`."""
    settings = get_settings()
    if profile is None:
        with engine.connect() as conn:
            profile = load_profile(conn, settings)
    tz = settings.tz
    today = dt.datetime.now(tz).date()
    is_today = day == today
    base_need = base_need_min if base_need_min is not None else settings.sleep_need_base_min

    prev_day = day - dt.timedelta(days=1)
    d30 = day - dt.timedelta(days=30)
    d14 = day - dt.timedelta(days=14)
    d6 = day - dt.timedelta(days=6)
    d13 = day - dt.timedelta(days=13)

    with engine.begin() as conn:
        vitals = _load_vitals(conn, day, prev_day, d30, d6)
        sleep = _load_sleep(conn, day, prev_day, d14, d6, d13, tz, base_need, is_today)
        minute_hr = _load_hr_minutes(conn, day, tz)
        exercise_sessions = _load_exercise(conn, day)
        strength_sessions, caps = _load_strength(conn, day, prev_day, d30)

        # Recovery calculation
        rec_result = calculate_recovery(
            hrv_rmssd=vitals.hrv_ms,
            resting_hr=vitals.rhr,
            breathing_rate=vitals.breathing_rate,
            skin_temp_delta=vitals.skin_temp_delta,
            spo2_avg=vitals.spo2_avg,
            sleep_performance=float(sleep.sleep_perf) if sleep.sleep_perf is not None else None,
            hrv_baseline=vitals.hrv_baseline,
            rhr_baseline=vitals.rhr_baseline,
            breathing_baseline=vitals.breathing_baseline,
            skin_temp_baseline=vitals.skin_temp_baseline,
            prev_rhr=vitals.prev_rhr,
            prev_rmssd=vitals.prev_rmssd,
        )

        # Day strain calculation
        hr_max = float(profile.effective_hr_max(day.year))
        has_strain_data = bool(minute_hr or strength_sessions)
        if has_strain_data:
            strain_res = calculate_day_strain(
                minute_hr=minute_hr,
                rest_hr=vitals.rest_hr_anchor,
                hr_max=hr_max,
                sex=profile.sex,
                exercise_sessions=exercise_sessions,
                strength_sessions=strength_sessions,
                caps=caps,
            )
            strain_val: float | None = strain_res.strain
            cardio_val: float | None = strain_res.cardio_load
            muscular_val: float | None = strain_res.muscular_load
            zones_val: str | None = json.dumps(strain_res.zone_minutes)
            activities_val: str | None = json.dumps(strain_res.activities)
        else:
            strain_val = None
            cardio_val = None
            muscular_val = None
            zones_val = None
            activities_val = None

        # Bedtime plan (tonight)
        planned_bedtime = None
        planned_wake = None
        if is_today:
            extended_debt_history = list(sleep.debt_history)
            if sleep.actual_min is not None:
                extended_debt_history = [
                    SleepNightData(k=n.k + 1, need=n.need, actual=n.actual)
                    for n in sleep.debt_history
                ]
                extended_debt_history.insert(
                    0, SleepNightData(k=1, need=sleep.sleep_need, actual=sleep.actual_min)
                )

            debt_tonight = calculate_sleep_debt(extended_debt_history, base_need=base_need)

            planned_bedtime, planned_wake = calculate_bedtime_plan(
                today_date=day,
                tz=tz,
                base_need=base_need,
                debt_with_last_night=debt_tonight,
                today_strain=strain_val,
                today_naps=sleep.today_naps,
                recent_efficiencies=sleep.recent_effs,
                recent_wake_times=sleep.recent_wakes,
                alarm_time=alarm_time,
            )

        # Inputs JSON payload
        inputs_payload = {
            "rest_hr": vitals.rest_hr_anchor,
            "hr_max": hr_max,
            "baselines": {
                "hrv": vitals.hrv_baseline,
                "rhr": vitals.rhr_baseline,
                "breathing_rate": vitals.breathing_baseline,
                "skin_temp": vitals.skin_temp_baseline,
            },
            "caps": {
                "cap_vol": caps[0],
                "cap_srpe": caps[1],
            },
        }

        conn.execute(
            text(_UPSERT_DAILY_SCORE),
            {
                "local_date": day,
                "recovery": rec_result.score if rec_result else None,
                "recovery_z": rec_result.z if rec_result else None,
                "recovery_components": (json.dumps(rec_result.components) if rec_result else None),
                "flags": rec_result.flags if rec_result else [],
                "strain": strain_val,
                "cardio_load": cardio_val,
                "muscular_load": muscular_val,
                "zone_minutes": zones_val,
                "activities": activities_val,
                "strain_target_low": (rec_result.strain_target_low if rec_result else None),
                "strain_target_high": (rec_result.strain_target_high if rec_result else None),
                "sleep_need_min": sleep.sleep_need,
                "sleep_actual_min": sleep.actual_min if sleep.has_main_sleep else None,
                "sleep_debt_min": sleep.sleep_debt if sleep.has_main_sleep else None,
                "sleep_performance": sleep.sleep_perf if sleep.has_main_sleep else None,
                "sleep_efficiency": sleep.efficiency_val if sleep.has_main_sleep else None,
                "sleep_consistency": sleep.consistency_val if sleep.has_main_sleep else None,
                "planned_bedtime": planned_bedtime,
                "planned_wake": planned_wake,
                "inputs": json.dumps(inputs_payload),
                "algo_version": ALGO_VERSION,
            },
        )


def refresh_scores(engine: Engine, days_back: int) -> int:
    """Recompute daily scores from D-days_back through today, oldest first."""
    settings = get_settings()
    tz = settings.tz
    today = dt.datetime.now(tz).date()
    start_date = today - dt.timedelta(days=days_back)
    count = 0

    def _do_refresh() -> None:
        nonlocal count
        with engine.connect() as conn:
            app_settings = load_app_settings(conn)
        profile = profile_from(app_settings, settings)

        base_need_val = app_settings.get("sleep_need_base_min")
        base_need = (
            int(base_need_val) if base_need_val is not None else settings.sleep_need_base_min
        )

        alarm_str = app_settings.get("alarm_time")
        alarm_time: dt.time | None = None
        if alarm_str:
            try:
                alarm_time = dt.time.fromisoformat(str(alarm_str))
            except ValueError:
                log.warning("invalid alarm_time setting: %r", alarm_str)

        current = start_date
        while current <= today:
            compute_scores(
                engine,
                current,
                base_need_min=base_need,
                alarm_time=alarm_time,
                profile=profile,
            )
            count += 1
            current += dt.timedelta(days=1)
        with engine.begin() as conn:
            state.mark_success(conn, "worker", "scores")

    run_job("worker", "scores", _do_refresh)
    return count
