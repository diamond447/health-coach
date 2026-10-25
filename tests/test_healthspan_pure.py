"""Pure unit tests for healthspan factor curves, Gompertz rule of thumb, and pace of aging."""

import datetime as dt
import math

import pytest

from health_coach.analytics.healthspan import (
    GOMPERTZ_SCALE,
    FactorResult,
    body_composition_factor,
    calculate_healthspan,
    calculate_pace_of_aging,
    get_vo2max_ref,
    hr_to_years,
    interpolate_log_hr,
    moderate_activity_factor,
    resting_hr_factor,
    sleep_duration_factor,
    sleep_regularity_factor,
    steps_factor,
    strength_training_factor,
    vigorous_activity_factor,
    vo2max_factor,
)


def test_gompertz_conversion() -> None:
    # 8 / ln(2) ~ 11.54156
    assert math.isclose(GOMPERTZ_SCALE, 8.0 / math.log(2.0), rel_tol=1e-6)

    # HR = 1.0 -> 0.0 years
    assert math.isclose(hr_to_years(1.0), 0.0, abs_tol=1e-5)

    # HR = 2.0 (risk doubled) -> +8.0 years, clamped to +3.0 default
    assert hr_to_years(2.0) == 3.0
    assert hr_to_years(2.0, clamp=(-10.0, 10.0)) == pytest.approx(8.0, rel=1e-4)

    # HR = 0.5 (risk halved) -> -8.0 years, clamped to -3.0 default
    assert hr_to_years(0.5) == -3.0
    assert hr_to_years(0.5, clamp=(-10.0, 10.0)) == pytest.approx(-8.0, rel=1e-4)

    with pytest.raises(ValueError, match="hazard ratio must be positive"):
        hr_to_years(-1.0)
    with pytest.raises(ValueError, match="hazard ratio must be positive"):
        hr_to_years(0.0)


def test_interpolate_log_hr_anchors() -> None:
    anchors = [(0.0, 1.25), (75.0, 1.00), (150.0, 0.85)]
    # Exactly on anchors
    assert math.isclose(interpolate_log_hr(0.0, anchors), 1.25)
    assert math.isclose(interpolate_log_hr(75.0, anchors), 1.00)
    assert math.isclose(interpolate_log_hr(150.0, anchors), 0.85)

    # Clamping outside anchors
    assert math.isclose(interpolate_log_hr(-10.0, anchors), 1.25)
    assert math.isclose(interpolate_log_hr(200.0, anchors), 0.85)

    # Midpoint between 0.0 and 75.0 in log HR
    mid_x = 37.5
    expected_ln_hr = 0.5 * (math.log(1.25) + math.log(1.00))
    assert math.isclose(interpolate_log_hr(mid_x, anchors), math.exp(expected_ln_hr))


def test_curve_1_sleep_regularity() -> None:
    # Anchors: 40 -> 1.30, 70 -> 1.00, 90 -> 0.85
    f_low = sleep_regularity_factor(30.0)
    assert f_low.has_data
    assert f_low.hr == pytest.approx(1.30, abs=1e-3)
    assert f_low.years == pytest.approx(3.0, abs=1e-1)  # clamped to +3.0

    f_mid = sleep_regularity_factor(70.0)
    assert f_mid.has_data
    assert f_mid.hr == pytest.approx(1.00, abs=1e-3)
    assert f_mid.years == pytest.approx(0.0, abs=1e-1)

    f_high = sleep_regularity_factor(95.0)
    assert f_high.has_data
    assert f_high.hr == pytest.approx(0.85, abs=1e-3)
    assert f_high.years == pytest.approx(-1.9, abs=1e-1)


def test_curve_2_sleep_duration() -> None:
    # Anchors: 5 -> 1.30, 6 -> 1.12, 7 -> 1.00, 8 -> 1.00, 9 -> 1.15, 10 -> 1.30
    f_7h = sleep_duration_factor(7.5)
    assert f_7h.has_data
    assert f_7h.hr == 1.0
    assert f_7h.years == 0.0

    f_5h = sleep_duration_factor(4.5)
    assert f_5h.hr == 1.30
    assert f_5h.years == 3.0

    f_10h = sleep_duration_factor(11.0)
    assert f_10h.hr == 1.30
    assert f_10h.years == 3.0


def test_curve_3_moderate_activity() -> None:
    # Anchors: 0 -> 1.25, 75 -> 1.00, 150 -> 0.85, 300 -> 0.78
    f_0 = moderate_activity_factor(0.0)
    assert f_0.hr == 1.25
    assert f_0.years == pytest.approx(2.6, abs=1e-1)

    f_150 = moderate_activity_factor(150.0)
    assert f_150.hr == 0.85
    assert f_150.years == pytest.approx(-1.9, abs=1e-1)

    f_400 = moderate_activity_factor(400.0)
    assert f_400.hr == 0.78
    assert f_400.years == pytest.approx(-2.9, abs=1e-1)


def test_curve_4_vigorous_activity() -> None:
    # Anchors: 0 -> 1.05, 20 -> 1.00, 75 -> 0.85, 150 -> 0.80
    f_0 = vigorous_activity_factor(0.0)
    assert f_0.hr == 1.05
    assert f_0.years == pytest.approx(0.6, abs=1e-1)

    f_20 = vigorous_activity_factor(20.0)
    assert f_20.hr == 1.00
    assert f_20.years == 0.0

    f_75 = vigorous_activity_factor(75.0)
    assert f_75.hr == 0.85
    assert f_75.years == pytest.approx(-1.9, abs=1e-1)


def test_curve_5_strength_training() -> None:
    # J-shape: 0 -> 1.10, 0.5 -> 0.90, 1.0 -> 0.85, 2.5 -> 0.90, 4 -> 0.95
    f_0 = strength_training_factor(0.0)
    assert f_0.hr == 1.10
    assert f_0.years == pytest.approx(1.1, abs=1e-1)

    f_1 = strength_training_factor(1.0)
    assert f_1.hr == 0.85
    assert f_1.years == pytest.approx(-1.9, abs=1e-1)

    f_4 = strength_training_factor(5.0)
    assert f_4.hr == 0.95
    assert f_4.years == pytest.approx(-0.6, abs=1e-1)


def test_curve_6_steps() -> None:
    # 2500 -> 1.40, 4000 -> 1.20, 6000 -> 1.00, 8000 -> 0.85, 10000 -> 0.78, 12000 -> 0.76
    f_2k = steps_factor(2000.0)
    assert f_2k.hr == 1.40
    assert f_2k.years == 3.0  # clamped to +3.0

    f_6k = steps_factor(6000.0)
    assert f_6k.hr == 1.00
    assert f_6k.years == 0.0

    f_10k = steps_factor(10000.0)
    assert f_10k.hr == 0.78
    assert f_10k.years == pytest.approx(-2.9, abs=1e-1)


def test_curve_7_resting_hr() -> None:
    # HR per 10 bpm = 1.09 relative to 60 bpm
    f_60 = resting_hr_factor(60.0)
    assert f_60.hr == 1.00
    assert f_60.years == 0.0

    f_70 = resting_hr_factor(70.0)
    assert f_70.hr == pytest.approx(1.09, abs=1e-3)
    assert f_70.years == pytest.approx(1.0, abs=1e-1)

    f_50 = resting_hr_factor(50.0)
    assert f_50.hr == pytest.approx(1.09**-1, abs=1e-3)
    assert f_50.years == pytest.approx(-1.0, abs=1e-1)


def test_curve_8_vo2max() -> None:
    # Reference table: male 20-29: 44, 30-39: 42, 40-49: 39, 50-59: 36, 60+: 32; female 6 lower.
    assert get_vo2max_ref(25, "male") == 44.0
    assert get_vo2max_ref(35, "male") == 42.0
    assert get_vo2max_ref(45, "male") == 39.0
    assert get_vo2max_ref(55, "male") == 36.0
    assert get_vo2max_ref(65, "male") == 32.0

    assert get_vo2max_ref(25, "female") == 38.0
    assert get_vo2max_ref(35, "female") == 36.0
    assert get_vo2max_ref(45, "female") == 33.0

    # Male age 35, vo2max = 42.0 (exactly on ref) -> HR 1.0, 0.0 years
    f_exact = vo2max_factor(42.0, age=35, sex="male")
    assert f_exact.hr == 1.00
    assert f_exact.years == 0.0

    # Male age 35, vo2max = 45.5 (+3.5 ml/kg/min) -> HR = 0.87
    f_higher = vo2max_factor(45.5, age=35, sex="male")
    assert f_higher.hr == pytest.approx(0.87, abs=1e-3)
    assert f_higher.years == pytest.approx(-1.6, abs=1e-1)

    # Missing age or vo2max -> no data
    f_no_age = vo2max_factor(45.5, age=None, sex="male")
    assert not f_no_age.has_data
    assert f_no_age.years is None

    f_no_val = vo2max_factor(None, age=35, sex="male")
    assert not f_no_val.has_data


def test_curve_8_vo2max_sex_none_averaging() -> None:
    # When sex is None, male and female results are averaged
    age = 35
    vo2max = 40.0
    f_male = vo2max_factor(vo2max, age=age, sex="male")
    f_female = vo2max_factor(vo2max, age=age, sex="female")
    f_none = vo2max_factor(vo2max, age=age, sex=None)

    assert f_none.has_data
    expected_hr = (f_male.hr + f_female.hr) / 2.0  # type: ignore[operator]
    expected_yr = (f_male.years + f_female.years) / 2.0  # type: ignore[operator]
    assert f_none.hr == pytest.approx(expected_hr, abs=1e-3)
    assert f_none.years == pytest.approx(expected_yr, abs=1e-1)


def test_curve_9_body_composition() -> None:
    # Male: 10 -> 1.00, 18 -> 1.00, 25 -> 1.10, 30 -> 1.25. Clamped to [-1.5, +1.5]
    f_m_15 = body_composition_factor(15.0, sex="male")
    assert f_m_15.hr == 1.00
    assert f_m_15.years == 0.0

    f_m_35 = body_composition_factor(35.0, sex="male")
    assert f_m_35.hr == 1.25
    # Gompertz for 1.25 is ~2.57 years, clamped to 1.5
    assert f_m_35.years == 1.5

    # Female is +8 points: 18 -> 1.00, 26 -> 1.00, 33 -> 1.10, 38 -> 1.25
    f_f_22 = body_composition_factor(22.0, sex="female")
    assert f_f_22.hr == 1.00
    assert f_f_22.years == 0.0


def test_curve_9_body_composition_sex_none_averaging() -> None:
    val = 24.0
    f_m = body_composition_factor(val, sex="male")
    f_f = body_composition_factor(val, sex="female")
    f_none = body_composition_factor(val, sex=None)

    assert f_none.has_data
    expected_hr = (f_m.hr + f_f.hr) / 2.0  # type: ignore[operator]
    expected_yr = (f_m.years + f_f.years) / 2.0  # type: ignore[operator]
    assert f_none.hr == pytest.approx(expected_hr, abs=1e-3)
    assert f_none.years == pytest.approx(expected_yr, abs=1e-1)


def test_missing_factors_count() -> None:
    # Factors with < 4 weeks of data report has_data=False
    f_short = sleep_regularity_factor(85.0, weeks_count=3)
    assert not f_short.has_data
    assert f_short.years is None

    # Factors with None value report has_data=False
    f_none = resting_hr_factor(None)
    assert not f_none.has_data
    assert f_none.years is None


def test_pace_of_aging() -> None:
    # Fewer than 8 values returns None
    assert calculate_pace_of_aging([0.0] * 7) is None

    # Constant deltas (no change over time) -> slope 0 -> pace 1.0
    const_deltas = [-2.0] * 12
    assert calculate_pace_of_aging(const_deltas) == pytest.approx(1.0, abs=1e-3)

    # Weekly delta decreasing by 0.2 / 52 per week -> delta decreases by 0.2 per calendar year
    # slope = -0.2 -> pace = 1 + (-0.2) = 0.8
    step = -0.2 / 52.0
    series = [-2.0 + i * step for i in range(26)]
    pace = calculate_pace_of_aging(series)
    assert pace is not None
    assert math.isclose(pace, 0.8, rel_tol=1e-4)

    # Extreme slope clamped to [0.5, 1.5]
    fast_younger = [0.0 - i * 2.0 for i in range(10)]
    assert calculate_pace_of_aging(fast_younger) == 0.5

    fast_older = [0.0 + i * 2.0 for i in range(10)]
    assert calculate_pace_of_aging(fast_older) == 1.5

    # With date tuples
    start_date = dt.date(2026, 1, 5)
    date_series = [(start_date + dt.timedelta(weeks=i), -2.0 + i * step) for i in range(26)]
    date_pace = calculate_pace_of_aging(date_series)
    assert date_pace is not None
    assert math.isclose(date_pace, 0.8, rel_tol=1e-2)


def test_healthspan_aggregator_clamping_and_age() -> None:
    # Aggregate clamping to [-10, +10]
    # Create 5 factors with +3.0 years each -> sum = 15.0 -> clamped to 10.0
    factors = [
        FactorResult(
            key=f"f{i}",
            name=f"F{i}",
            value=1.0,
            unit="",
            goal="",
            hr=1.5,
            years=3.0,
            has_data=True,
        )
        for i in range(5)
    ]
    res = calculate_healthspan(factors, age=40)
    assert res.delta_years == 10.0
    assert res.age == 40
    assert res.biological_age == 50.0
    assert res.factors_with_data == 5

    # Without age
    res_no_age = calculate_healthspan(factors, age=None)
    assert res_no_age.delta_years == 10.0
    assert res_no_age.age is None
    assert res_no_age.biological_age is None
