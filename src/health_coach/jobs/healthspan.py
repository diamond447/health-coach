"""Worker job for weekly estimated biological age (healthspan) and pace of aging."""

from __future__ import annotations

import datetime as dt
import json
import logging
import statistics

from sqlalchemy import Connection, Engine, text

from health_coach.analytics.healthspan import (
    ALGO_VERSION,
    FactorResult,
    HealthspanResult,
    body_composition_factor,
    calculate_healthspan,
    moderate_activity_factor,
    resting_hr_factor,
    sleep_duration_factor,
    sleep_regularity_factor,
    steps_factor,
    strength_training_factor,
    vigorous_activity_factor,
    vo2max_factor,
)
from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.jobs.runner import run_job
from health_coach.profile import load_profile

log = logging.getLogger(__name__)

_UPSERT_HEALTHSPAN_WEEKLY = """
INSERT INTO healthspan_weekly (
    week_start, delta_years, pace, factors, factors_with_data, age,
    algo_version, source, created_at, updated_at
) VALUES (
    :week_start, :delta_years, :pace, CAST(:factors AS jsonb), :factors_with_data, :age,
    :algo_version, 'worker', now(), now()
) ON CONFLICT (week_start) DO UPDATE SET
    delta_years = EXCLUDED.delta_years,
    pace = EXCLUDED.pace,
    factors = EXCLUDED.factors,
    factors_with_data = EXCLUDED.factors_with_data,
    age = EXCLUDED.age,
    algo_version = EXCLUDED.algo_version,
    updated_at = now()
"""


def _to_week_start(d: dt.date) -> dt.date:
    """Return the Monday of the week containing date d."""
    return d - dt.timedelta(days=d.weekday())


def compute_healthspan_for_week(
    conn: Connection,
    week_start: dt.date,
    settings: Settings | None = None,
) -> HealthspanResult:
    """Compute and persist healthspan for a single Monday-aligned week_start."""
    app_settings = settings or get_settings()
    profile = load_profile(conn, app_settings)

    # Align to Monday
    week_start = _to_week_start(week_start)

    # Trailing 26-week window: Monday of (W - 25 weeks) to Sunday of W
    window_start = week_start - dt.timedelta(weeks=25)
    window_end = week_start + dt.timedelta(days=6)

    # Trailing 8-week window: Monday of (W - 7 weeks) to Sunday of W
    window_8_start = week_start - dt.timedelta(weeks=7)

    # Chronological age as of this week
    age = profile.age(week_start.year)

    # 1. Daily scores: sleep consistency, sleep actual minutes, zone minutes
    score_rows = conn.execute(
        text(
            "SELECT local_date, sleep_consistency, sleep_actual_min, zone_minutes "
            "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
        ),
        {"s": window_start, "e": window_end},
    ).all()

    sleep_consistency_vals: list[float] = []
    sleep_consistency_weeks: set[dt.date] = set()

    sleep_duration_vals: list[float] = []
    sleep_duration_weeks: set[dt.date] = set()

    mod_minutes_by_week: dict[dt.date, int] = {}
    vig_minutes_by_week: dict[dt.date, int] = {}
    tracked_score_weeks: set[dt.date] = set()

    for r in score_rows:
        w = _to_week_start(r.local_date)
        tracked_score_weeks.add(w)

        if r.sleep_consistency is not None:
            sleep_consistency_vals.append(float(r.sleep_consistency))
            sleep_consistency_weeks.add(w)

        if r.sleep_actual_min is not None and r.sleep_actual_min > 0:
            sleep_duration_vals.append(float(r.sleep_actual_min) / 60.0)
            sleep_duration_weeks.add(w)

        zm = r.zone_minutes
        if isinstance(zm, str):
            try:
                zm = json.loads(zm)
            except Exception:
                zm = {}
        if isinstance(zm, dict):
            z1 = int(zm.get("Z1") or 0)
            z2 = int(zm.get("Z2") or 0)
            z3 = int(zm.get("Z3") or 0)
            z4 = int(zm.get("Z4") or 0)
            z5 = int(zm.get("Z5") or 0)
            mod_minutes_by_week[w] = mod_minutes_by_week.get(w, 0) + (z1 + z2 + z3)
            vig_minutes_by_week[w] = vig_minutes_by_week.get(w, 0) + (z4 + z5)

    # Factor 1: Sleep regularity
    mean_sleep_reg = (
        sum(sleep_consistency_vals) / len(sleep_consistency_vals)
        if sleep_consistency_vals
        else None
    )
    f_sleep_reg = sleep_regularity_factor(
        mean_sleep_reg,
        weeks_count=len(sleep_consistency_weeks),
    )

    # Factor 2: Sleep duration
    mean_sleep_dur = (
        sum(sleep_duration_vals) / len(sleep_duration_vals) if sleep_duration_vals else None
    )
    f_sleep_dur = sleep_duration_factor(
        mean_sleep_dur,
        weeks_count=len(sleep_duration_weeks),
    )

    # Factor 3: Moderate activity
    activity_weeks_count = len(tracked_score_weeks)
    mean_mod_mins: float | None = None
    if activity_weeks_count > 0:
        total_mod = sum(mod_minutes_by_week.get(w, 0) for w in tracked_score_weeks)
        mean_mod_mins = total_mod / activity_weeks_count
    f_mod_act = moderate_activity_factor(mean_mod_mins, weeks_count=activity_weeks_count)

    # Factor 4: Vigorous activity
    mean_vig_mins: float | None = None
    if activity_weeks_count > 0:
        total_vig = sum(vig_minutes_by_week.get(w, 0) for w in tracked_score_weeks)
        mean_vig_mins = total_vig / activity_weeks_count
    f_vig_act = vigorous_activity_factor(mean_vig_mins, weeks_count=activity_weeks_count)

    # Factor 5: Strength training
    st_rows = conn.execute(
        text(
            "SELECT local_date, start_ts, end_ts FROM strength_sessions "
            "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
        ),
        {"s": window_start, "e": window_end},
    ).all()

    st_duration_hours_by_week: dict[dt.date, float] = {}
    st_weeks: set[dt.date] = set()
    for st in st_rows:
        w = _to_week_start(st.local_date)
        st_weeks.add(w)
        if st.start_ts and st.end_ts:
            dur_h = max(0.0, (st.end_ts - st.start_ts).total_seconds() / 3600.0)
        else:
            dur_h = 0.75  # 45 min default
        st_duration_hours_by_week[w] = st_duration_hours_by_week.get(w, 0.0) + dur_h

    overall_tracked_weeks = max(activity_weeks_count, len(st_weeks))
    mean_st_hours: float | None = None
    if overall_tracked_weeks > 0:
        total_st_h = sum(st_duration_hours_by_week.values())
        mean_st_hours = total_st_h / overall_tracked_weeks
    f_strength = strength_training_factor(mean_st_hours, weeks_count=overall_tracked_weeks)

    # Factor 6: Steps
    steps_rows = conn.execute(
        text(
            "SELECT local_date, steps FROM daily_activity "
            "WHERE local_date BETWEEN :s AND :e AND steps IS NOT NULL ORDER BY local_date"
        ),
        {"s": window_start, "e": window_end},
    ).all()
    steps_vals = [float(r.steps) for r in steps_rows]
    steps_weeks = {_to_week_start(r.local_date) for r in steps_rows}
    mean_steps = sum(steps_vals) / len(steps_vals) if steps_vals else None
    f_steps = steps_factor(mean_steps, weeks_count=len(steps_weeks))

    # Factor 7: Resting HR
    rhr_rows = conn.execute(
        text(
            "SELECT local_date, resting_hr FROM daily_vitals "
            "WHERE local_date BETWEEN :s AND :e AND resting_hr IS NOT NULL ORDER BY local_date"
        ),
        {"s": window_start, "e": window_end},
    ).all()
    rhr_vals = [float(r.resting_hr) for r in rhr_rows]
    rhr_weeks = {_to_week_start(r.local_date) for r in rhr_rows}
    median_rhr = float(statistics.median(rhr_vals)) if rhr_vals else None
    f_rhr = resting_hr_factor(median_rhr, weeks_count=len(rhr_weeks))

    # Factor 8: VO2max (latest 8-week median)
    vo2_rows = conn.execute(
        text(
            "SELECT cardio_fitness FROM daily_vitals "
            "WHERE local_date BETWEEN :s AND :e AND cardio_fitness IS NOT NULL"
        ),
        {"s": window_8_start, "e": window_end},
    ).all()
    vo2_vals = [float(r.cardio_fitness) for r in vo2_rows]
    median_vo2 = float(statistics.median(vo2_vals)) if vo2_vals else None
    f_vo2 = vo2max_factor(median_vo2, age=age, sex=profile.sex)

    # Factor 9: Body composition (latest 8-week median)
    fat_rows = conn.execute(
        text(
            "SELECT body_fat_pct FROM body_metrics "
            "WHERE local_date BETWEEN :s AND :e "
            "  AND body_fat_pct IS NOT NULL AND deleted_at IS NULL"
        ),
        {"s": window_8_start, "e": window_end},
    ).all()
    fat_vals = [float(r.body_fat_pct) for r in fat_rows]
    median_fat = float(statistics.median(fat_vals)) if fat_vals else None
    f_fat = body_composition_factor(median_fat, sex=profile.sex)

    factors: list[FactorResult] = [
        f_sleep_reg,
        f_sleep_dur,
        f_mod_act,
        f_vig_act,
        f_strength,
        f_steps,
        f_rhr,
        f_vo2,
        f_fat,
    ]

    # Load previous weeks in the trailing 26 weeks for pace calculation
    prev_rows = conn.execute(
        text(
            "SELECT week_start, delta_years FROM healthspan_weekly "
            "WHERE week_start >= :s AND week_start < :w AND delta_years IS NOT NULL "
            "ORDER BY week_start"
        ),
        {"s": window_start, "w": week_start},
    ).all()

    # Pre-calculate delta_years for current week to append to series
    active_factors = [f for f in factors if f.has_data and f.years is not None]
    raw_delta = (
        sum(f.years for f in active_factors if f.years is not None) if active_factors else 0.0
    )
    current_delta = max(-10.0, min(10.0, raw_delta))

    weekly_series: list[tuple[dt.date, float]] = [
        (r.week_start, float(r.delta_years)) for r in prev_rows
    ]
    weekly_series.append((week_start, current_delta))

    result = calculate_healthspan(factors, age=age, weekly_deltas=weekly_series)

    # Upsert into healthspan_weekly
    conn.execute(
        text(_UPSERT_HEALTHSPAN_WEEKLY),
        {
            "week_start": week_start,
            "delta_years": result.delta_years,
            "pace": result.pace,
            "factors": json.dumps([f.to_dict() for f in result.factors]),
            "factors_with_data": result.factors_with_data,
            "age": result.age,
            "algo_version": ALGO_VERSION,
        },
    )

    return result


def refresh_healthspan(
    engine: Engine,
    weeks_back: int = 26,
    settings: Settings | None = None,
) -> int:
    """Compute and persist healthspan for the trailing N weeks up to current week."""
    app_settings = settings or get_settings()
    now_date = dt.datetime.now(app_settings.tz).date()
    current_week_start = _to_week_start(now_date)

    weeks = [current_week_start - dt.timedelta(weeks=i) for i in range(weeks_back - 1, -1, -1)]

    count = 0
    with engine.begin() as conn:
        for w in weeks:
            compute_healthspan_for_week(conn, w, app_settings)
            count += 1

    log.info("Computed healthspan for %d weeks", count)
    return count


def healthspan_recent() -> None:
    """Job run nightly at 05:00: compute previous week and current week."""
    engine = get_engine(Role.ingest)
    settings = get_settings()
    now_date = dt.datetime.now(settings.tz).date()
    curr_week = _to_week_start(now_date)
    prev_week = curr_week - dt.timedelta(weeks=1)

    def _run() -> None:
        with engine.begin() as conn:
            compute_healthspan_for_week(conn, prev_week, settings)
            compute_healthspan_for_week(conn, curr_week, settings)

    run_job("worker", "healthspan_recent", _run)
