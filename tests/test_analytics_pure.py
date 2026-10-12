"""Unit tests for pure analytics functions."""

import datetime as dt
from zoneinfo import ZoneInfo

from health_coach.analytics.compare import (
    V_DAILY_NUMERIC_COLUMNS,
    compare_period_metrics,
    compute_metric_change,
)
from health_coach.analytics.nutrition import (
    calculate_logging_completeness,
    calculate_meal_distribution,
    calculate_nutrition_averages,
)
from health_coach.analytics.recovery import (
    calculate_acute_chronic,
    evaluate_readiness,
)
from health_coach.analytics.sleep import (
    calculate_bedtime_minutes,
    calculate_sleep_analysis,
)
from health_coach.analytics.tdee import calculate_tdee
from health_coach.analytics.training import (
    compute_session_progress,
    least_squares_slope,
    sum_hr_zones,
)

PRAGUE = ZoneInfo("Europe/Prague")


# --- TDEE tests -----------------------------------------------------------------------


def test_tdee_calculation_high_confidence() -> None:
    # 21 days of 2800 kcal, weight rises 0.75 kg over 21 days (0.25 kg/week)
    kcals = [2800.0] * 21
    res = calculate_tdee(
        window_days=21,
        logged_daily_kcals=kcals,
        start_trend_kg=78.0,
        end_trend_kg=78.75,
        weigh_ins=21,
    )
    assert res.avg_intake == 2800.0
    assert res.trend_change_kg == 0.75
    # 2800 - 0.75 * 7700 / 21 = 2800 - 275 = 2525.0
    assert res.tdee == 2525.0
    assert res.confidence == "high"
    assert res.logged_days == 21
    assert res.weigh_ins == 21


def test_tdee_confidence_tiers() -> None:
    kcals_21 = [2500.0] * 21
    # High: logged >= 0.85*21 (18 days), weigh_ins >= 0.5*21 (11 days)
    res_high = calculate_tdee(21, kcals_21[:18], 78.0, 78.0, 11)
    assert res_high.confidence == "high"

    # Medium: logged >= 0.7*21 (15 days), weigh_ins >= 0.3*21 (7 days)
    res_med = calculate_tdee(21, kcals_21[:15], 78.0, 78.0, 7)
    assert res_med.confidence == "medium"

    # Low: logged 15 days, weigh_ins 5 (< 7)
    res_low = calculate_tdee(21, kcals_21[:15], 78.0, 78.0, 5)
    assert res_low.confidence == "low"

    # None: logged_days < 7
    res_none_logged = calculate_tdee(21, kcals_21[:6], 78.0, 78.0, 15)
    assert res_none_logged.confidence == "none"
    assert res_none_logged.tdee is None

    # None: weigh_ins < 4
    res_none_weigh = calculate_tdee(21, kcals_21[:20], 78.0, 78.0, 3)
    assert res_none_weigh.confidence == "none"
    assert res_none_weigh.tdee is None

    # Missing trend
    res_none_trend = calculate_tdee(21, kcals_21, None, 78.0, 20)
    assert res_none_trend.confidence == "none"
    assert res_none_trend.tdee is None


# --- Recovery tests -------------------------------------------------------------------


def test_recovery_acute_chronic_ratio() -> None:
    # 28 days: daily load = 10 for the first 21 days, 20 for the last 7 days
    loads = [10.0] * 21 + [20.0] * 7
    # acute = 20.0; chronic = (21*10 + 7*20) / 28 = (210 + 140)/28 = 350/28 = 12.5
    # ratio = 20 / 12.5 = 1.6
    ratio = calculate_acute_chronic(loads)
    assert ratio == 1.6

    # Fewer than 7 days returns None
    assert calculate_acute_chronic([10.0] * 6) is None
    # Empty returns None
    assert calculate_acute_chronic([]) is None


def test_readiness_rules_green() -> None:
    res = evaluate_readiness(
        sleep_min=450,
        rhr_z=-0.2,
        hrv_z=0.5,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.1,
    )
    assert res.flag == "green"
    assert res.reasons == []
    assert res.missing == []


def test_readiness_rules_red_cases() -> None:
    # Two red triggers: hrv_z <= -1.5 and sleep_min < 360
    res1 = evaluate_readiness(
        sleep_min=350,
        rhr_z=0.0,
        hrv_z=-1.6,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.0,
    )
    assert res1.flag == "red"
    assert len(res1.reasons) == 2

    # Two red triggers: rhr_z >= 1.5 and acute_chronic > 1.5
    res2 = evaluate_readiness(
        sleep_min=420,
        rhr_z=1.7,
        hrv_z=0.0,
        soreness=2,
        energy=3,
        acute_chronic_ratio=1.6,
    )
    assert res2.flag == "red"
    assert len(res2.reasons) == 2

    # Two red triggers: soreness >= 4 with energy <= 2, and sleep_min < 360
    res3 = evaluate_readiness(
        sleep_min=340,
        rhr_z=0.5,
        hrv_z=0.0,
        soreness=5,
        energy=1,
        acute_chronic_ratio=1.0,
    )
    assert res3.flag == "red"
    assert len(res3.reasons) == 2


def test_readiness_rules_amber_cases() -> None:
    # Only one red trigger (e.g. hrv_z = -1.6) -> triggers amber because hrv_z <= -1.0
    res1 = evaluate_readiness(
        sleep_min=420,
        rhr_z=0.0,
        hrv_z=-1.6,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.0,
    )
    assert res1.flag == "amber"
    assert any("HRV" in r for r in res1.reasons)

    # Amber trigger: sleep_min < 390 (380 min)
    res2 = evaluate_readiness(
        sleep_min=380,
        rhr_z=0.2,
        hrv_z=0.2,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.0,
    )
    assert res2.flag == "amber"
    assert any("Sleep" in r for r in res2.reasons)

    # Amber trigger: rhr_z >= 1.0 (1.2)
    res3 = evaluate_readiness(
        sleep_min=420,
        rhr_z=1.2,
        hrv_z=0.0,
        soreness=1,
        energy=5,
        acute_chronic_ratio=1.0,
    )
    assert res3.flag == "amber"

    # Amber trigger: soreness >= 4 (even with energy > 2)
    res4 = evaluate_readiness(
        sleep_min=420,
        rhr_z=0.0,
        hrv_z=0.0,
        soreness=4,
        energy=4,
        acute_chronic_ratio=1.0,
    )
    assert res4.flag == "amber"

    # Amber trigger: energy <= 2 (even with low soreness)
    res5 = evaluate_readiness(
        sleep_min=420,
        rhr_z=0.0,
        hrv_z=0.0,
        soreness=2,
        energy=2,
        acute_chronic_ratio=1.0,
    )
    assert res5.flag == "amber"

    # Amber trigger: acute_chronic > 1.3 (1.4)
    res6 = evaluate_readiness(
        sleep_min=420,
        rhr_z=0.0,
        hrv_z=0.0,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.4,
    )
    assert res6.flag == "amber"


def test_readiness_missing_metrics() -> None:
    # Watch does not provide HRV
    res = evaluate_readiness(
        sleep_min=450,
        rhr_z=0.1,
        hrv_z=None,
        soreness=2,
        energy=4,
        acute_chronic_ratio=1.0,
    )
    assert res.flag == "green"
    assert "hrv_z" in res.missing

    # No data at all -> unknown
    res_unknown = evaluate_readiness(
        sleep_min=None,
        rhr_z=None,
        hrv_z=None,
        soreness=None,
        energy=None,
        acute_chronic_ratio=None,
    )
    assert res_unknown.flag == "unknown"
    assert "no data available" in res_unknown.reasons[0]
    assert len(res_unknown.missing) == 6


# --- Sleep tests ----------------------------------------------------------------------


def test_bedtime_minutes_wrap() -> None:
    tz = PRAGUE
    # 18:00
    t1 = dt.datetime(2026, 10, 10, 18, 0, tzinfo=tz)
    assert calculate_bedtime_minutes(t1, tz) == 0.0

    # 23:30
    t2 = dt.datetime(2026, 10, 10, 23, 30, tzinfo=tz)
    assert calculate_bedtime_minutes(t2, tz) == 330.0

    # 00:30 (next morning, wrap past midnight)
    t3 = dt.datetime(2026, 10, 11, 0, 30, tzinfo=tz)
    assert calculate_bedtime_minutes(t3, tz) == 390.0

    # 02:00
    t4 = dt.datetime(2026, 10, 11, 2, 0, tzinfo=tz)
    assert calculate_bedtime_minutes(t4, tz) == 480.0


def test_sleep_analysis_calculation() -> None:
    tz = PRAGUE
    sessions = [
        {
            "local_date": dt.date(2026, 10, 1),
            "start_ts": dt.datetime(2026, 9, 30, 23, 0, tzinfo=tz),
            "duration_min": 420,
            "efficiency": 90,
            "minutes_deep": 80,
            "minutes_light": 240,
            "minutes_rem": 100,
            "minutes_awake": 30,
            "sleep_score": 85,
        },
        {
            "local_date": dt.date(2026, 10, 2),
            "start_ts": dt.datetime(2026, 10, 1, 23, 30, tzinfo=tz),
            "duration_min": 480,
            "efficiency": 92,
            "minutes_deep": 90,
            "minutes_light": 280,
            "minutes_rem": 110,
            "minutes_awake": 20,
            "sleep_score": 90,
        },
        {
            "local_date": dt.date(2026, 10, 3),
            "start_ts": dt.datetime(2026, 10, 2, 23, 15, tzinfo=tz),
            "duration_min": 360,
            "efficiency": 80,
            "minutes_deep": 60,
            "minutes_light": 200,
            "minutes_rem": 100,
            "minutes_awake": 40,
            "sleep_score": 75,
        },
    ]

    res = calculate_sleep_analysis(sessions, tz)
    assert res.avg_duration_min == 420.0
    assert res.avg_efficiency == 87.3
    # Sleep debt: max(0, 480-420) + max(0, 480-480) + max(0, 480-360) = 60 + 0 + 120 = 180 min
    assert res.sleep_debt_min == 180
    assert res.bedtime_consistency_sd_min is not None
    # 3 worst nights ordered by duration ascending
    assert res.worst_nights[0]["duration_min"] == 360
    assert res.worst_nights[1]["duration_min"] == 420
    assert res.worst_nights[2]["duration_min"] == 480


# --- Training tests -------------------------------------------------------------------


def test_least_squares_slope() -> None:
    # 1 kg gain per day -> 7 kg/week
    pts = [(0.0, 100.0), (1.0, 101.0), (2.0, 102.0), (3.0, 103.0)]
    assert least_squares_slope(pts) == 7.0

    # Flat slope
    pts_flat = [(0.0, 100.0), (7.0, 100.0), (14.0, 100.0)]
    assert least_squares_slope(pts_flat) == 0.0

    # < 2 points
    assert least_squares_slope([(0.0, 100.0)]) is None
    # Identical x coordinates
    assert least_squares_slope([(0.0, 100.0), (0.0, 105.0)]) is None


def test_compute_session_progress() -> None:
    sets = [
        {"is_warmup": True, "reps": 10, "weight_kg": 60.0},
        {"is_warmup": False, "reps": 8, "weight_kg": 100.0, "rir": 2},
        {"is_warmup": False, "reps": 6, "weight_kg": 105.0, "rir": 1},
        {"is_warmup": False, "reps": 10, "weight_kg": 95.0, "rir": 3},
    ]
    prog = compute_session_progress(1, dt.date(2026, 10, 10), sets)
    # Top set: heaviest weight (105.0 x 6)
    assert prog.top_set_weight_kg == 105.0
    assert prog.top_set_reps == 6.0
    # Working volume: 8*100 + 6*105 + 10*95 = 800 + 630 + 950 = 2380.0
    assert prog.volume_kg == 2380.0
    # e1RM fallback: best of 100x8 (126.7) vs 105x6 (126.0) is 126.7
    assert prog.e1rm_kg == 126.7


def test_sum_hr_zones() -> None:
    sessions = [
        {"hr_zone_minutes": {"1": 15, "2": 30, "3": 10}},
        {"hr_zone_minutes": {"2": 20, "3": 25, "4": 5}},
    ]
    zones = sum_hr_zones(sessions)
    assert zones == {"1": 15, "2": 50, "3": 35, "4": 5}


# --- Compare & Nutrition tests --------------------------------------------------------


def test_compute_metric_change() -> None:
    abs_d, pct_d = compute_metric_change(2000.0, 2500.0)
    assert abs_d == 500.0
    assert pct_d == 25.0

    abs_d2, pct_d2 = compute_metric_change(100.0, 80.0)
    assert abs_d2 == -20.0
    assert pct_d2 == -20.0

    abs_none, pct_none = compute_metric_change(None, 100.0)
    assert abs_none is None
    assert pct_none is None


def test_compare_period_metrics() -> None:
    stats_a = {"kcal_in": (2400.0, 7), "steps": (10000.0, 7)}
    stats_b = {"kcal_in": (2640.0, 7), "steps": (8000.0, 7)}
    rows = compare_period_metrics(["kcal_in", "steps"], stats_a, stats_b)
    assert len(rows) == 2
    assert rows[0]["metric"] == "kcal_in"
    assert rows[0]["absolute_change"] == 240.0
    assert rows[0]["percent_change"] == 10.0
    assert rows[1]["metric"] == "steps"
    assert rows[1]["absolute_change"] == -2000.0
    assert rows[1]["percent_change"] == -20.0


def test_v_daily_numeric_columns_whitelist() -> None:
    assert {"steps", "kcal_in", "weight_kg", "resting_hr", "sleep_min"} <= V_DAILY_NUMERIC_COLUMNS
    assert "source" not in V_DAILY_NUMERIC_COLUMNS
    assert "local_date" not in V_DAILY_NUMERIC_COLUMNS


def test_nutrition_summary_pure_helpers() -> None:
    meals = {"breakfast": 500.0, "lunch": 1000.0, "dinner": 1000.0}
    dist = calculate_meal_distribution(meals)
    assert dist == {"breakfast": 20.0, "lunch": 40.0, "dinner": 40.0}

    comp = calculate_logging_completeness(5, 7)
    assert comp["days_logged"] == 5
    assert comp["days_in_range"] == 7
    assert comp["ratio"] == 0.71
    assert comp["percentage"] == 71.4

    daily = [
        {
            "kcal": 2500,
            "protein_g": 160.0,
            "carbs_g": 250.0,
            "fat_g": 70.0,
            "fiber_g": 30.0,
            "protein_g_per_kg": 2.0,
        },
        {
            "kcal": 2700,
            "protein_g": 180.0,
            "carbs_g": 270.0,
            "fat_g": 80.0,
            "fiber_g": 35.0,
            "protein_g_per_kg": 2.25,
        },
    ]
    avgs = calculate_nutrition_averages(daily)
    assert avgs.kcal_avg == 2600
    assert avgs.protein_avg_g == 170.0
    assert avgs.protein_g_per_kg_avg == 2.12
