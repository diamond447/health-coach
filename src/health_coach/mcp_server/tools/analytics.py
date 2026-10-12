"""Group 3: TDEE, recovery, sleep, training load, exercise progress, PRs, compare tools."""

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from sqlalchemy import Connection, text

from health_coach.analytics.compare import V_DAILY_NUMERIC_COLUMNS, compare_period_metrics
from health_coach.analytics.nutrition import (
    calculate_logging_completeness,
    calculate_meal_distribution,
    calculate_nutrition_averages,
)
from health_coach.analytics.recovery import (
    calculate_acute_chronic,
    evaluate_readiness,
)
from health_coach.analytics.sleep import calculate_sleep_analysis
from health_coach.analytics.tdee import estimate_from_db
from health_coach.analytics.training import (
    compute_session_progress,
    least_squares_slope,
    sum_hr_zones,
)
from health_coach.config import get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import (
    READ,
    audited,
    date_range,
    rnd,
    tabular,
    today,
)

DateArg = Annotated[dt.date | None, Field(description="YYYY-MM-DD, local date")]


# --- 1. estimate_tdee -----------------------------------------------------------------


def estimate_tdee(
    window_days: Annotated[
        int, Field(ge=7, le=60, description="Window size in days (7..60); default 21")
    ] = 21,
) -> dict[str, Any]:
    """Adaptive TDEE estimation based on daily caloric intake and exponential weight trend change.

    The window ends yesterday (today is incomplete). Intake is averaged over days with
    logged nutrition entries; weight trend change is latest trend_kg on/before window end
    minus latest trend_kg on/before window start. Includes past estimates from tdee_estimates.
    """
    with get_engine(Role.ro).connect() as conn:
        res, start, end = estimate_from_db(conn, today(), window_days)
        history_rows = conn.execute(
            text(
                "SELECT local_date, window_days, avg_intake, trend_change_kg, tdee, "
                "       confidence, logged_days, weigh_ins "
                "FROM tdee_estimates ORDER BY local_date DESC, window_days LIMIT 12"
            )
        ).all()

        return {
            "window_days": window_days,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "avg_intake": rnd(res.avg_intake, 10),
            "trend_change_kg": res.trend_change_kg,
            "tdee": rnd(res.tdee, 10),
            "confidence": res.confidence,
            "logged_days": res.logged_days,
            "weigh_ins": res.weigh_ins,
            "history": tabular(history_rows),
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- 2. get_nutrition_summary ---------------------------------------------------------


def get_nutrition_summary(
    start: DateArg = None,
    end: DateArg = None,
) -> dict[str, Any]:
    """Nutritional summary over a date range: daily intake vs targets, averages,
    protein per kg bodyweight, meal distribution (% kcal), top 10 foods, and logging completeness.
    """
    s, e = date_range(start, end)
    days_in_range = (e - s).days + 1

    with get_engine(Role.ro).connect() as conn:
        daily_rows = conn.execute(
            text(
                "SELECT local_date, kcal, protein_g, carbs_g, fat_g, fiber_g, "
                "       target_kcal, target_protein_g, kcal_vs_target, protein_vs_target_g, "
                "       protein_g_per_kg, entries, meals_logged "
                "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e "
                "ORDER BY local_date"
            ),
            {"s": s, "e": e},
        ).all()

        mapped_daily = [dict(r._mapping) for r in daily_rows]
        averages = calculate_nutrition_averages(mapped_daily)

        meal_rows = conn.execute(
            text(
                "SELECT meal, round(sum(kcal)) AS kcal FROM nutrition_entries "
                "WHERE deleted_at IS NULL AND local_date BETWEEN :s AND :e "
                "GROUP BY meal ORDER BY kcal DESC"
            ),
            {"s": s, "e": e},
        ).all()
        meal_kcals = {r.meal: float(r.kcal) for r in meal_rows}
        meal_distribution = calculate_meal_distribution(meal_kcals)

        top_food_rows = conn.execute(
            text(
                "SELECT coalesce(food_id::text, description) AS food_id, "
                "       description, round(sum(kcal)) AS kcal, "
                "       round(sum(grams), 1) AS grams, count(*) AS entries "
                "FROM nutrition_entries "
                "WHERE deleted_at IS NULL AND local_date BETWEEN :s AND :e "
                "GROUP BY food_id, description ORDER BY sum(kcal) DESC LIMIT 10"
            ),
            {"s": s, "e": e},
        ).all()

        completeness = calculate_logging_completeness(len(daily_rows), days_in_range)

        return {
            "start": s.isoformat(),
            "end": e.isoformat(),
            "daily": tabular(daily_rows),
            "averages": {
                "kcal_avg": rnd(averages.kcal_avg, 10),
                "protein_avg_g": averages.protein_avg_g,
                "carbs_avg_g": averages.carbs_avg_g,
                "fat_avg_g": averages.fat_avg_g,
                "fiber_avg_g": averages.fiber_avg_g,
                "protein_g_per_kg": averages.protein_g_per_kg_avg,
            },
            "meal_distribution_pct": meal_distribution,
            "top_foods": tabular(top_food_rows),
            "completeness": completeness,
            "as_of": quality.as_of(conn),
            "warnings": quality.logging_warnings(conn, e),
        }


# --- 3. get_recovery_status -----------------------------------------------------------


def get_recovery_snapshot(conn: Connection, day: dt.date) -> dict[str, Any]:
    """Compute compact recovery readiness for get_context_snapshot."""
    baseline = conn.execute(
        text(
            "SELECT local_date, resting_hr, rhr_mean_30d, rhr_sd_30d, rhr_z, "
            "       hrv_rmssd_ms, hrv_mean_30d, hrv_sd_30d, hrv_z, "
            "       sleep_min, sleep_mean_30d, sleep_sd_30d, sleep_z "
            "FROM v_recovery_baseline WHERE local_date = :d"
        ),
        {"d": day},
    ).first()

    checkin = conn.execute(
        text("SELECT energy, soreness FROM checkins WHERE local_date = :d"),
        {"d": day},
    ).first()

    # Acute:chronic training load
    start_28d = day - dt.timedelta(days=27)
    daily_loads_rows = conn.execute(
        text(
            "SELECT local_date, hard_sets, exercise_min FROM v_daily "
            "WHERE local_date BETWEEN :s AND :d ORDER BY local_date"
        ),
        {"s": start_28d, "d": day},
    ).all()

    if not daily_loads_rows:
        acute_chronic = None
    else:
        loads_by_date = {
            r.local_date: float(r.hard_sets or 0) * 1.0 + float(r.exercise_min or 0) / 10.0
            for r in daily_loads_rows
        }
        loads_28d = [loads_by_date.get(start_28d + dt.timedelta(days=i), 0.0) for i in range(28)]
        acute_chronic = calculate_acute_chronic(loads_28d)

    readiness = evaluate_readiness(
        sleep_min=float(baseline.sleep_min)
        if (baseline and baseline.sleep_min is not None)
        else None,
        rhr_z=float(baseline.rhr_z) if (baseline and baseline.rhr_z is not None) else None,
        hrv_z=float(baseline.hrv_z) if (baseline and baseline.hrv_z is not None) else None,
        soreness=int(checkin.soreness) if (checkin and checkin.soreness is not None) else None,
        energy=int(checkin.energy) if (checkin and checkin.energy is not None) else None,
        acute_chronic_ratio=acute_chronic,
    )

    return {
        "flag": readiness.flag,
        "readiness": readiness.flag,
        "reasons": readiness.reasons,
        "rhr_z": rnd(baseline.rhr_z, 0.01) if baseline else None,
        "hrv_z": rnd(baseline.hrv_z, 0.01) if baseline else None,
        "sleep_z": rnd(baseline.sleep_z, 0.01) if baseline else None,
    }


def get_recovery_status(date: DateArg = None) -> dict[str, Any]:
    """Readiness status for today or a specific date (green/amber/red/unknown).

    Compares last night's sleep against the rolling 30-day baseline, resting heart rate
    and HRV z-scores, acute:chronic workload ratio (7d vs 28d daily load), and subjective
    check-in soreness and energy.
    """
    day = date or today()

    with get_engine(Role.ro).connect() as conn:
        baseline = conn.execute(
            text(
                "SELECT local_date, resting_hr, rhr_mean_30d, rhr_sd_30d, rhr_z, "
                "       hrv_rmssd_ms, hrv_mean_30d, hrv_sd_30d, hrv_z, "
                "       sleep_min, sleep_mean_30d, sleep_sd_30d, sleep_z "
                "FROM v_recovery_baseline WHERE local_date = :d"
            ),
            {"d": day},
        ).first()

        checkin = conn.execute(
            text(
                "SELECT energy, soreness, stress, motivation, notes FROM checkins "
                "WHERE local_date = :d"
            ),
            {"d": day},
        ).first()

        start_28d = day - dt.timedelta(days=27)
        training_rows = conn.execute(
            text(
                "SELECT local_date, hard_sets, tonnage_kg, exercise_min FROM v_daily "
                "WHERE local_date BETWEEN :s AND :d ORDER BY local_date"
            ),
            {"s": start_28d, "d": day},
        ).all()

        if not training_rows:
            acute_chronic = None
        else:
            daily_loads_map = {
                r.local_date: float(r.hard_sets or 0) * 1.0 + float(r.exercise_min or 0) / 10.0
                for r in training_rows
            }
            loads_28d = [
                daily_loads_map.get(start_28d + dt.timedelta(days=i), 0.0) for i in range(28)
            ]
            acute_chronic = calculate_acute_chronic(loads_28d)

        # 3-day and 7-day training loads
        last_3_start = day - dt.timedelta(days=2)
        last_7_start = day - dt.timedelta(days=6)

        rows_3d = [r for r in training_rows if r.local_date >= last_3_start]
        rows_7d = [r for r in training_rows if r.local_date >= last_7_start]

        load_3d = {
            "hard_sets": sum(int(r.hard_sets or 0) for r in rows_3d),
            "tonnage_kg": rnd(sum(float(r.tonnage_kg or 0) for r in rows_3d), 10),
            "exercise_min": sum(int(r.exercise_min or 0) for r in rows_3d),
        }
        load_7d = {
            "hard_sets": sum(int(r.hard_sets or 0) for r in rows_7d),
            "tonnage_kg": rnd(sum(float(r.tonnage_kg or 0) for r in rows_7d), 10),
            "exercise_min": sum(int(r.exercise_min or 0) for r in rows_7d),
        }

        readiness = evaluate_readiness(
            sleep_min=float(baseline.sleep_min)
            if (baseline and baseline.sleep_min is not None)
            else None,
            rhr_z=float(baseline.rhr_z) if (baseline and baseline.rhr_z is not None) else None,
            hrv_z=float(baseline.hrv_z) if (baseline and baseline.hrv_z is not None) else None,
            soreness=int(checkin.soreness) if (checkin and checkin.soreness is not None) else None,
            energy=int(checkin.energy) if (checkin and checkin.energy is not None) else None,
            acute_chronic_ratio=acute_chronic,
        )

        return {
            "date": day.isoformat(),
            "readiness": readiness.flag,
            "reasons": readiness.reasons,
            "missing": readiness.missing,
            "sleep": {
                "duration_min": baseline.sleep_min if baseline else None,
                "baseline_mean_min": rnd(baseline.sleep_mean_30d, 1) if baseline else None,
                "baseline_sd_min": rnd(baseline.sleep_sd_30d, 1) if baseline else None,
                "z_score": rnd(baseline.sleep_z, 0.01) if baseline else None,
            },
            "vitals": {
                "resting_hr": rnd(baseline.resting_hr, 1) if baseline else None,
                "rhr_mean_30d": rnd(baseline.rhr_mean_30d, 1) if baseline else None,
                "rhr_z": rnd(baseline.rhr_z, 0.01) if baseline else None,
                "hrv_rmssd_ms": rnd(baseline.hrv_rmssd_ms, 0.1) if baseline else None,
                "hrv_mean_30d": rnd(baseline.hrv_mean_30d, 0.1) if baseline else None,
                "hrv_z": rnd(baseline.hrv_z, 0.01) if baseline else None,
            },
            "training_load": {
                "last_3_days": load_3d,
                "last_7_days": load_7d,
                "acute_chronic_ratio": acute_chronic,
            },
            "checkin": {
                "energy": checkin.energy if checkin else None,
                "soreness": checkin.soreness if checkin else None,
                "stress": checkin.stress if checkin else None,
                "motivation": checkin.motivation if checkin else None,
                "notes": checkin.notes if checkin else None,
            },
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- 4. get_sleep_analysis ------------------------------------------------------------


def get_sleep_analysis(
    start: DateArg = None,
    end: DateArg = None,
) -> dict[str, Any]:
    """Sleep analysis (default: last 14 days): night-by-night metrics, averages of duration,
    efficiency and stages, bedtime consistency (SD of bedtime minutes relative to 18:00 local),
    sleep debt (vs 8h), and the 3 worst nights.
    """
    s, e = date_range(start, end, default_days=14)

    with get_engine(Role.ro).connect() as conn:
        sessions = conn.execute(
            text(
                "SELECT local_date, start_ts, end_ts, duration_min, efficiency, "
                "       minutes_deep, minutes_light, minutes_rem, minutes_awake, sleep_score "
                "FROM sleep_sessions WHERE is_main AND local_date BETWEEN :s AND :e "
                "ORDER BY local_date"
            ),
            {"s": s, "e": e},
        ).all()

        mapped_sessions = [dict(r._mapping) for r in sessions]
        stats = calculate_sleep_analysis(mapped_sessions, get_settings().tz)

        return {
            "start": s.isoformat(),
            "end": e.isoformat(),
            "nights": tabular(sessions),
            "averages": {
                "duration_min": stats.avg_duration_min,
                "efficiency": stats.avg_efficiency,
                "minutes_deep": stats.avg_deep_min,
                "minutes_light": stats.avg_light_min,
                "minutes_rem": stats.avg_rem_min,
                "minutes_awake": stats.avg_awake_min,
            },
            "bedtime_consistency_sd_min": stats.bedtime_consistency_sd_min,
            "sleep_debt_min": stats.sleep_debt_min,
            "worst_nights": stats.worst_nights,
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- 5. get_training_load -------------------------------------------------------------


def get_training_load(
    start: DateArg = None,
    end: DateArg = None,
) -> dict[str, Any]:
    """Weekly training load (default: last 28 days): strength sessions, hard sets,
    tonnage, hard sets per muscle group, other sports minutes by activity, and HR zone totals.
    """
    s, e = date_range(start, end, default_days=28)
    s_monday = s - dt.timedelta(days=s.weekday())

    with get_engine(Role.ro).connect() as conn:
        strength_weeks = conn.execute(
            text(
                "SELECT to_char(s.local_date, 'IYYY-\"W\"IW') AS iso_week, "
                "       date_trunc('week', s.local_date)::date AS week_start, "
                "       count(DISTINCT s.id) AS sessions, "
                "       count(ss.id) FILTER (WHERE NOT ss.is_warmup AND coalesce(ss.reps, 0) > 0 "
                "                            AND (ss.rir IS NULL OR ss.rir <= 4)) AS hard_sets, "
                "       round(sum(ss.reps * ss.weight_kg) "
                "             FILTER (WHERE NOT ss.is_warmup)) AS tonnage_kg "
                "FROM strength_sessions s "
                "LEFT JOIN strength_sets ss ON ss.session_id = s.id "
                "WHERE s.local_date BETWEEN :s AND :e "
                "GROUP BY 1, 2 ORDER BY week_start"
            ),
            {"s": s, "e": e},
        ).all()

        muscle_rows = conn.execute(
            text(
                "SELECT iso_week, muscle, hard_sets "
                "FROM v_strength_volume_weekly "
                "WHERE week_start BETWEEN :s_monday AND :e "
                "ORDER BY iso_week, hard_sets DESC"
            ),
            {"s_monday": s_monday, "e": e},
        ).all()
        muscles_by_week: dict[str, dict[str, float]] = defaultdict(dict)
        for m in muscle_rows:
            muscles_by_week[m.iso_week][m.muscle] = float(m.hard_sets)

        exercise_rows = conn.execute(
            text(
                "SELECT to_char(local_date, 'IYYY-\"W\"IW') AS iso_week, "
                "       date_trunc('week', local_date)::date AS week_start, "
                "       activity_type, duration_min, hr_zone_minutes "
                "FROM exercise_sessions "
                "WHERE deleted_at IS NULL AND local_date BETWEEN :s AND :e "
                "ORDER BY local_date"
            ),
            {"s": s, "e": e},
        ).all()

        sports_by_week: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        sessions_for_zones: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for ex in exercise_rows:
            sports_by_week[ex.iso_week][ex.activity_type] += int(ex.duration_min or 0)
            sessions_for_zones[ex.iso_week].append(dict(ex._mapping))

        # Collect all active weeks in range
        weeks_data: dict[str, dict[str, Any]] = {}
        for sw in strength_weeks:
            weeks_data[sw.iso_week] = {
                "iso_week": sw.iso_week,
                "week_start": sw.week_start.isoformat(),
                "strength_sessions": int(sw.sessions or 0),
                "hard_sets": int(sw.hard_sets or 0),
                "tonnage_kg": rnd(sw.tonnage_kg, 10),
                "muscles": muscles_by_week.get(sw.iso_week, {}),
                "other_sports_minutes": dict(sports_by_week.get(sw.iso_week, {})),
                "hr_zone_minutes": sum_hr_zones(sessions_for_zones.get(sw.iso_week, [])),
            }

        for ex in exercise_rows:
            if ex.iso_week not in weeks_data:
                weeks_data[ex.iso_week] = {
                    "iso_week": ex.iso_week,
                    "week_start": ex.week_start.isoformat(),
                    "strength_sessions": 0,
                    "hard_sets": 0,
                    "tonnage_kg": 0,
                    "muscles": muscles_by_week.get(ex.iso_week, {}),
                    "other_sports_minutes": dict(sports_by_week.get(ex.iso_week, {})),
                    "hr_zone_minutes": sum_hr_zones(sessions_for_zones.get(ex.iso_week, [])),
                }

        sorted_weeks = sorted(weeks_data.values(), key=lambda w: w["week_start"])

        return {
            "start": s.isoformat(),
            "end": e.isoformat(),
            "weeks": sorted_weeks,
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- Exercise resolver helper ---------------------------------------------------------


def _resolve_exercise(conn: Connection, exercise: str) -> Any:
    cleaned = exercise.strip()
    row = conn.execute(
        text("SELECT id, name FROM exercises WHERE id = :id"),
        {"id": cleaned},
    ).first()
    if row:
        return row

    # Exact name match
    exact = conn.execute(
        text("SELECT id, name FROM exercises WHERE lower(name) = lower(:q)"),
        {"q": cleaned},
    ).first()
    if exact:
        return exact

    # ILIKE search
    matches = conn.execute(
        text(
            "SELECT id, name FROM exercises "
            "WHERE name ILIKE '%' || :q || '%' "
            "ORDER BY length(name), name LIMIT 6"
        ),
        {"q": cleaned},
    ).all()

    if not matches:
        raise ToolError(f"no exercise found matching {exercise!r}")
    if len(matches) == 1:
        return matches[0]

    candidates = [f"{m.name} ({m.id})" for m in matches[:5]]
    raise ToolError(
        f"ambiguous exercise {exercise!r}; did you mean one of: {', '.join(candidates)}?"
    )


# --- 6. get_exercise_progress ---------------------------------------------------------


def get_exercise_progress(
    exercise: Annotated[str, Field(description="Exercise name fragment or openGym exercise id")],
    start: DateArg = None,
    end: DateArg = None,
) -> dict[str, Any]:
    """Progress over time for a strength exercise (default: last 180 days).

    Returns per-session top set, e1RM, working volume, least-squares e1RM trend slope
    (kg/week), and new personal records set in the range.
    """
    s, e = date_range(start, end, default_days=180)

    with get_engine(Role.ro).connect() as conn:
        ex = _resolve_exercise(conn, exercise)

        sets_rows = conn.execute(
            text(
                "SELECT s.id AS session_id, s.local_date, ss.set_no, ss.reps, "
                "       ss.weight_kg, ss.rir, ss.is_warmup "
                "FROM strength_sets ss JOIN strength_sessions s ON s.id = ss.session_id "
                "WHERE ss.exercise_id = :id AND s.local_date BETWEEN :s AND :e "
                "ORDER BY s.local_date, s.id, ss.set_no"
            ),
            {"id": ex.id, "s": s, "e": e},
        ).all()

        e1rm_rows = conn.execute(
            text(
                "SELECT session_id, local_date, e1rm_kg FROM v_exercise_e1rm "
                "WHERE exercise_id = :id AND local_date BETWEEN :s AND :e"
            ),
            {"id": ex.id, "s": s, "e": e},
        ).all()
        e1rm_by_session = {r.session_id: float(r.e1rm_kg) for r in e1rm_rows}

        sets_by_session: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        dates_by_session: dict[int, dt.date] = {}
        for r in sets_rows:
            sets_by_session[r.session_id].append(dict(r._mapping))
            dates_by_session[r.session_id] = r.local_date

        sessions_progress = []
        for sid, s_sets in sets_by_session.items():
            ldate = dates_by_session[sid]
            prog = compute_session_progress(sid, ldate, s_sets, e1rm_by_session.get(sid))
            sessions_progress.append(prog)

        sessions_progress.sort(key=lambda p: (p.local_date, p.session_id))

        # Least squares e1RM slope
        e1rm_points: list[tuple[float, float]] = []
        if sessions_progress:
            first_day = sessions_progress[0].local_date
            for sp in sessions_progress:
                if sp.e1rm_kg is not None:
                    offset = float((sp.local_date - first_day).days)
                    e1rm_points.append((offset, sp.e1rm_kg))

        slope = least_squares_slope(e1rm_points)

        # Personal records in range
        prior_best = conn.execute(
            text(
                "SELECT max(e1rm_kg) AS best_e1rm, max(weight_kg) AS best_wt "
                "FROM v_exercise_e1rm WHERE exercise_id = :id AND local_date < :s"
            ),
            {"id": ex.id, "s": s},
        ).first()
        running_e1rm = float(prior_best.best_e1rm) if (prior_best and prior_best.best_e1rm) else 0.0
        running_wt = float(prior_best.best_wt) if (prior_best and prior_best.best_wt) else 0.0

        prs: list[dict[str, Any]] = []
        for sp in sessions_progress:
            if sp.e1rm_kg and sp.e1rm_kg > running_e1rm:
                prs.append(
                    {
                        "date": sp.local_date.isoformat(),
                        "type": "e1rm",
                        "value_kg": sp.e1rm_kg,
                        "previous_best_kg": rnd(running_e1rm, 0.1) if running_e1rm > 0 else None,
                    }
                )
                running_e1rm = sp.e1rm_kg
            if sp.top_set_weight_kg and sp.top_set_weight_kg > running_wt:
                prs.append(
                    {
                        "date": sp.local_date.isoformat(),
                        "type": "weight",
                        "value_kg": sp.top_set_weight_kg,
                        "reps": sp.top_set_reps,
                        "previous_best_kg": rnd(running_wt, 0.1) if running_wt > 0 else None,
                    }
                )
                running_wt = sp.top_set_weight_kg

        session_table = [
            {
                "local_date": sp.local_date,
                "top_set_weight_kg": sp.top_set_weight_kg,
                "top_set_reps": sp.top_set_reps,
                "e1rm_kg": sp.e1rm_kg,
                "volume_kg": sp.volume_kg,
            }
            for sp in sessions_progress
        ]

        return {
            "exercise_id": ex.id,
            "exercise": ex.name,
            "start": s.isoformat(),
            "end": e.isoformat(),
            "sessions": tabular(session_table),
            "e1rm_trend_kg_per_week": slope,
            "prs_in_range": prs,
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- 7. get_personal_records ----------------------------------------------------------


def get_personal_records(
    exercise: Annotated[
        str | None,
        Field(description="Exercise name or id; omit to show the 20 most frequent exercises"),
    ] = None,
) -> dict[str, Any]:
    """Personal records: all-time heaviest weight lifted, reps achieved at that weight,
    best estimated 1RM, and the dates they occurred.
    """
    with get_engine(Role.ro).connect() as conn:
        if exercise is not None:
            ex = _resolve_exercise(conn, exercise)
            target_exercises = [(ex.id, ex.name)]
        else:
            rows = conn.execute(
                text(
                    "SELECT ss.exercise_id, x.name, count(DISTINCT ss.session_id) AS sessions "
                    "FROM strength_sets ss JOIN exercises x ON x.id = ss.exercise_id "
                    "GROUP BY ss.exercise_id, x.name ORDER BY sessions DESC LIMIT 20"
                )
            ).all()
            target_exercises = [(r.exercise_id, r.name) for r in rows]

        records = []
        for ex_id, ex_name in target_exercises:
            best_wt_row = conn.execute(
                text(
                    "SELECT ss.weight_kg, ss.reps, s.local_date "
                    "FROM strength_sets ss JOIN strength_sessions s ON s.id = ss.session_id "
                    "WHERE ss.exercise_id = :id AND NOT ss.is_warmup AND ss.weight_kg > 0 "
                    "ORDER BY ss.weight_kg DESC, ss.reps DESC, s.local_date LIMIT 1"
                ),
                {"id": ex_id},
            ).first()

            best_e1rm_row = conn.execute(
                text(
                    "SELECT e1rm_kg, weight_kg, reps, local_date "
                    "FROM v_exercise_e1rm WHERE exercise_id = :id "
                    "ORDER BY e1rm_kg DESC, local_date LIMIT 1"
                ),
                {"id": ex_id},
            ).first()

            records.append(
                {
                    "exercise_id": ex_id,
                    "exercise": ex_name,
                    "best_weight_kg": rnd(best_wt_row.weight_kg, 0.1) if best_wt_row else None,
                    "reps_at_best_weight": best_wt_row.reps if best_wt_row else None,
                    "best_weight_date": best_wt_row.local_date.isoformat() if best_wt_row else None,
                    "best_e1rm_kg": rnd(best_e1rm_row.e1rm_kg, 0.1) if best_e1rm_row else None,
                    "e1rm_weight_kg": rnd(best_e1rm_row.weight_kg, 0.1) if best_e1rm_row else None,
                    "e1rm_reps": best_e1rm_row.reps if best_e1rm_row else None,
                    "best_e1rm_date": best_e1rm_row.local_date.isoformat()
                    if best_e1rm_row
                    else None,
                }
            )

        return {
            **tabular(records),
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- 8. compare_periods ---------------------------------------------------------------


def compare_periods(
    metrics: Annotated[
        list[str],
        Field(description="Numeric columns of v_daily, e.g. ['kcal_in', 'steps', 'sleep_min']"),
    ],
    a_start: Annotated[dt.date, Field(description="Period A start (YYYY-MM-DD)")],
    a_end: Annotated[dt.date, Field(description="Period A end (YYYY-MM-DD)")],
    b_start: Annotated[dt.date, Field(description="Period B start (YYYY-MM-DD)")],
    b_end: Annotated[dt.date, Field(description="Period B end (YYYY-MM-DD)")],
) -> dict[str, Any]:
    """Compare averages of selected numeric v_daily metrics between two periods.

    Period A vs Period B: returns means, absolute change (B - A), percentage change,
    and days with data. Only whitelisted numeric columns of v_daily are permitted.
    """
    if a_start > a_end:
        raise ToolError(f"Period A start {a_start} is after end {a_end}")
    if b_start > b_end:
        raise ToolError(f"Period B start {b_start} is after end {b_end}")
    if not metrics:
        raise ToolError("metrics list cannot be empty")

    invalid = [m for m in metrics if m not in V_DAILY_NUMERIC_COLUMNS]
    if invalid:
        allowed = sorted(V_DAILY_NUMERIC_COLUMNS)
        raise ToolError(
            f"invalid metric(s) {invalid}; allowed numeric columns: {', '.join(allowed)}"
        )

    # Safe SQL building: column names only from the verified whitelist
    select_clauses = [
        f"round(avg({col})::numeric, 2) AS {col}_mean, count({col}) AS {col}_days"
        for col in metrics
    ]
    query_sql = (
        f"SELECT {', '.join(select_clauses)} FROM v_daily WHERE local_date BETWEEN :s AND :e"  # noqa: S608
    )

    with get_engine(Role.ro).connect() as conn:
        row_a = conn.execute(text(query_sql), {"s": a_start, "e": a_end}).first()
        row_b = conn.execute(text(query_sql), {"s": b_start, "e": b_end}).first()

        stats_a: dict[str, tuple[float | None, int]] = {}
        stats_b: dict[str, tuple[float | None, int]] = {}
        for col in metrics:
            m_a = getattr(row_a, f"{col}_mean", None) if row_a else None
            d_a = getattr(row_a, f"{col}_days", 0) if row_a else 0
            m_b = getattr(row_b, f"{col}_mean", None) if row_b else None
            d_b = getattr(row_b, f"{col}_days", 0) if row_b else 0

            stats_a[col] = (
                float(m_a) if isinstance(m_a, Decimal | float | int) else None,
                int(d_a),
            )
            stats_b[col] = (
                float(m_b) if isinstance(m_b, Decimal | float | int) else None,
                int(d_b),
            )

        rows = compare_period_metrics(metrics, stats_a, stats_b)

        return {
            "period_a": {"start": a_start.isoformat(), "end": a_end.isoformat()},
            "period_b": {"start": b_start.isoformat(), "end": b_end.isoformat()},
            **tabular(rows),
            "as_of": quality.as_of(conn),
            "warnings": quality.all_warnings(conn),
        }


# --- Registration ---------------------------------------------------------------------


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(estimate_tdee))
    server.tool(annotations=READ)(audited(get_nutrition_summary))
    server.tool(annotations=READ)(audited(get_recovery_status))
    server.tool(annotations=READ)(audited(get_sleep_analysis))
    server.tool(annotations=READ)(audited(get_training_load))
    server.tool(annotations=READ)(audited(get_exercise_progress))
    server.tool(annotations=READ)(audited(get_personal_records))
    server.tool(annotations=READ)(audited(compare_periods))
