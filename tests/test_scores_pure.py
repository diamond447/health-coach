import datetime as dt
import math
from zoneinfo import ZoneInfo

import pytest

from health_coach.analytics.scores import (
    FLOOR_BREATHING_RATE,
    FLOOR_LN_HRV,
    FLOOR_RHR,
    FLOOR_SKIN_TEMP,
    ExerciseSessionData,
    SleepNightData,
    StrengthSessionData,
    StrengthSetData,
    banister_weight,
    calculate_bedtime_plan,
    calculate_day_strain,
    calculate_muscular_caps,
    calculate_recovery,
    calculate_session_muscular_load,
    calculate_sleep_consistency,
    calculate_sleep_debt,
    calculate_sleep_need,
    calculate_strain_from_load,
    hr_gate,
    recovery_zone,
    resample_hr_1min,
    robust_baseline,
)

UTC = dt.UTC
PRAGUE = ZoneInfo("Europe/Prague")


# --- 2a. Baselines --------------------------------------------------------------------


def test_robust_baseline_minimum_values() -> None:
    assert robust_baseline([]) is None
    assert robust_baseline([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) is None
    res = robust_baseline([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0])
    assert res is not None
    center, scale = res
    assert center == 13.0
    # MAD of [10..16] around 13: abs diffs are [3, 2, 1, 0, 1, 2, 3] -> median is 2.0
    # 1.4826 * 2.0 = 2.9652
    assert pytest.approx(scale, rel=1e-3) == 2.9652


def test_robust_baseline_floors() -> None:
    # All identical values -> MAD is 0 -> floor takes effect
    res_hrv = robust_baseline([3.5] * 10, floor=FLOOR_LN_HRV)
    assert res_hrv is not None
    assert res_hrv[0] == 3.5
    assert res_hrv[1] == FLOOR_LN_HRV

    res_rhr = robust_baseline([55.0] * 7, floor=FLOOR_RHR)
    assert res_rhr is not None
    assert res_rhr[1] == FLOOR_RHR

    res_br = robust_baseline([15.0] * 7, floor=FLOOR_BREATHING_RATE)
    assert res_br is not None
    assert res_br[1] == FLOOR_BREATHING_RATE

    res_temp = robust_baseline([0.0] * 7, floor=FLOOR_SKIN_TEMP)
    assert res_temp is not None
    assert res_temp[1] == FLOOR_SKIN_TEMP


# --- 2b. Recovery ---------------------------------------------------------------------


def test_recovery_zero_z_night_gives_57() -> None:
    # All signals at their baseline centers -> all z-scores = 0.0 -> score = 57
    ln_hrv_center = math.log(50.0)
    res = calculate_recovery(
        hrv_rmssd=50.0,
        resting_hr=60.0,
        breathing_rate=14.0,
        skin_temp_delta=0.0,
        spo2_avg=98.0,  # >= 95 -> z = 0
        sleep_performance=85.0,  # 85% -> z = 0
        hrv_baseline=(ln_hrv_center, 0.20),
        rhr_baseline=(60.0, 3.0),
        breathing_baseline=(14.0, 1.0),
        skin_temp_baseline=(0.0, 0.3),
    )
    assert res is not None
    assert res.score == 57
    assert res.z == 0.0
    assert res.zone == "yellow"
    assert res.flags == []
    # Strain target for r = 0.57: 3 + 12*0.57 = 9.84 -> 9.8, 6 + 12*0.57 = 12.84 -> 12.8
    assert res.strain_target_low == 9.8
    assert res.strain_target_high == 12.8


def test_recovery_both_hrv_and_rhr_missing_returns_none() -> None:
    # No HRV and no RHR
    res = calculate_recovery(
        hrv_rmssd=None,
        resting_hr=None,
        breathing_rate=14.0,
        breathing_baseline=(14.0, 1.0),
        sleep_performance=90.0,
    )
    assert res is None

    # HRV and RHR present but lacking baselines
    res2 = calculate_recovery(
        hrv_rmssd=50.0,
        resting_hr=60.0,
        hrv_baseline=None,
        rhr_baseline=None,
    )
    assert res2 is None


def test_recovery_missing_inputs_renormalise_and_points_sum() -> None:
    # Only HRV present with high value
    ln_hrv_center = math.log(50.0)
    res = calculate_recovery(
        hrv_rmssd=75.0,
        resting_hr=None,
        hrv_baseline=(ln_hrv_center, 0.20),
    )
    assert res is not None
    assert len(res.components) == 1
    assert res.components[0]["signal"] == "hrv"
    assert res.components[0]["weight"] == 1.0
    assert res.score > 57
    # Points sum to score - 57 when single component
    assert res.components[0]["points"] == res.score - 57

    # Multiple components: points roughly sum to score - 57
    res_multi = calculate_recovery(
        hrv_rmssd=58.0,
        resting_hr=58.0,
        sleep_performance=88.0,
        hrv_baseline=(ln_hrv_center, 0.20),
        rhr_baseline=(60.0, 3.0),
    )
    assert res_multi is not None
    assert res_multi.score >= 67
    assert res_multi.zone == "green"
    total_points = sum(c["points"] for c in res_multi.components)
    delta_from_baseline = res_multi.score - 57
    assert abs(total_points - delta_from_baseline) <= 6


def test_recovery_zones_and_flags() -> None:
    assert recovery_zone(70) == "green"
    assert recovery_zone(50) == "yellow"
    assert recovery_zone(20) == "red"
    assert recovery_zone(None) is None

    ln_hrv_center = math.log(50.0)
    # Low recovery (red zone)
    res_low = calculate_recovery(
        hrv_rmssd=25.0,
        resting_hr=72.0,
        hrv_baseline=(ln_hrv_center, 0.15),
        rhr_baseline=(60.0, 3.0),
    )
    assert res_low is not None
    assert res_low.score <= 33
    assert res_low.zone == "red"

    # Illness flag: RHR > center+5 AND RMSSD < 0.85*exp(center) on both D and D-1
    res_ill = calculate_recovery(
        hrv_rmssd=35.0,  # < 0.85 * 50 = 42.5
        resting_hr=68.0,  # > 60 + 5 = 65
        hrv_baseline=(ln_hrv_center, 0.20),
        rhr_baseline=(60.0, 3.0),
        prev_rhr=69.0,
        prev_rmssd=38.0,
    )
    assert res_ill is not None
    assert "illness" in res_ill.flags

    # Illness flag NOT set if only today has symptoms
    res_not_ill = calculate_recovery(
        hrv_rmssd=35.0,
        resting_hr=68.0,
        hrv_baseline=(ln_hrv_center, 0.20),
        rhr_baseline=(60.0, 3.0),
        prev_rhr=58.0,
        prev_rmssd=55.0,
    )
    assert res_not_ill is not None
    assert "illness" not in res_not_ill.flags

    # Temperature and low SpO2 flags
    res_flags = calculate_recovery(
        hrv_rmssd=50.0,
        resting_hr=60.0,
        skin_temp_delta=0.8,
        spo2_avg=92.0,
        hrv_baseline=(ln_hrv_center, 0.20),
        rhr_baseline=(60.0, 3.0),
        skin_temp_baseline=(0.0, 0.2),
    )
    assert res_flags is not None
    assert "temperature" in res_flags.flags
    assert "low_spo2" in res_flags.flags


# --- 2c. Day Strain -------------------------------------------------------------------


def test_strain_calibration_curve() -> None:
    # Calibration tests from spec: load 5 -> ~1.0, 25 -> ~4.6, 60 -> ~9.5, 85 -> ~12.0, 135 -> ~15.6
    cases = [
        (5.0, 1.0),
        (25.0, 4.6),
        (60.0, 9.5),
        (85.0, 12.0),
        (135.0, 15.6),
    ]
    for load, expected in cases:
        strain = calculate_strain_from_load(load)
        assert abs(strain - expected) <= 1.0


def test_hr_gate_and_zones() -> None:
    # x < 0.30 -> 0.0
    assert hr_gate(0.25, inside_window=False) == 0.0
    assert hr_gate(0.25, inside_window=True) == 0.0

    # 0.30 <= x < 0.40 outside window -> scale (x - 0.30) / 0.10
    assert pytest.approx(hr_gate(0.35, inside_window=False), rel=1e-3) == 0.5
    # 0.30 <= x < 0.40 inside window -> 1.0
    assert hr_gate(0.35, inside_window=True) == 1.0

    # x >= 0.40 -> 1.0 anywhere
    assert hr_gate(0.50, inside_window=False) == 1.0
    assert hr_gate(0.50, inside_window=True) == 1.0


def test_banister_weight_sex_differences() -> None:
    x = 0.50
    male_y = banister_weight(x, "male")
    female_y = banister_weight(x, "female")
    none_y = banister_weight(x, None)

    assert pytest.approx(male_y, rel=1e-3) == 0.64 * math.exp(1.92 * x)
    assert pytest.approx(female_y, rel=1e-3) == 0.86 * math.exp(1.67 * x)
    assert pytest.approx(none_y, rel=1e-3) == 0.5 * (male_y + female_y)


def test_resample_hr_1min() -> None:
    t0 = dt.datetime(2026, 10, 25, 10, 0, 0, tzinfo=UTC)
    raw = [
        (t0 + dt.timedelta(seconds=0), 120.0),
        (t0 + dt.timedelta(seconds=20), 130.0),
        (t0 + dt.timedelta(seconds=40), 140.0),
        # Next minute
        (t0 + dt.timedelta(seconds=65), 150.0),
    ]
    resampled = resample_hr_1min(raw)
    assert len(resampled) == 2
    assert resampled[0] == (t0, 130.0)
    assert resampled[1] == (t0 + dt.timedelta(minutes=1), 150.0)


def test_muscular_load_and_caps() -> None:
    # 90th percentile caps with minimums
    hist_sess = [
        StrengthSessionData(
            id=1,
            name="Session A",
            duration_min=60,
            sets=[
                StrengthSetData(reps=10, weight_kg=100, rpe=8, is_warmup=False),  # 1000 kg
            ],
        )
    ]
    cap_vol, cap_srpe = calculate_muscular_caps(hist_sess)
    assert cap_vol == 5000.0  # below 5000 -> minimum applies
    assert cap_srpe == 480.0  # 8 * 60 = 480 -> minimum 480

    # Session muscular load
    sess = StrengthSessionData(
        id=2,
        name="Heavy bench",
        duration_min=60,
        sets=[
            StrengthSetData(reps=10, weight_kg=100, is_warmup=True),  # warmup: excluded
            StrengthSetData(reps=10, weight_kg=100, rpe=8, is_warmup=False),  # 1000 kg
            StrengthSetData(reps=10, weight_kg=100, rpe=8, is_warmup=False),  # 1000 kg
        ],
    )
    vol, srpe, m_load = calculate_session_muscular_load(sess, cap_vol=5000.0, cap_srpe=480.0)
    assert vol == 2000.0
    assert srpe == 480.0
    # score = 50 * 2000 / 5000 + 50 * 480 / 480 = 20 + 50 = 70
    # muscular_load = 45 * (70/100)^1.6
    expected_m_load = 45.0 * (0.7**1.6)
    assert pytest.approx(m_load, rel=1e-3) == expected_m_load


def test_day_strain_end_to_end() -> None:
    t0 = dt.datetime(2026, 10, 25, 8, 0, 0, tzinfo=UTC)
    # 60 minutes of exercise at 150 bpm (rest=60, max=190 -> x = (150-60)/130 = 0.6923)
    minute_hr = [(t0 + dt.timedelta(minutes=i), 150.0) for i in range(60)]
    ex = ExerciseSessionData(
        id=1,
        kind="exercise",
        name="Morning Run",
        start_ts=t0,
        end_ts=t0 + dt.timedelta(minutes=60),
        duration_min=60,
        avg_hr=150,
        max_hr=150,
    )
    res = calculate_day_strain(
        minute_hr=minute_hr,
        rest_hr=60.0,
        hr_max=190.0,
        sex="male",
        exercise_sessions=[ex],
    )
    assert res.cardio_load > 0
    assert res.strain > 0
    # x = 0.6923 -> Zone 2 (0.60 - 0.70)
    assert res.zone_minutes["Z2"] == 60
    assert len(res.activities) == 1
    assert res.activities[0]["name"] == "Morning Run"
    assert res.activities[0]["strain"] > 0


# --- 2d. Sleep Need and Performance ---------------------------------------------------


def test_sleep_debt_exponential_decay() -> None:
    # 3 nights back with deficit: night 1 has 60 min deficit, night 2 has 60 min deficit
    history = [
        SleepNightData(k=1, need=480, actual=420),  # deficit 60, weight 1.0
        SleepNightData(k=2, need=480, actual=420),  # deficit 60, weight 0.75
    ]
    debt = calculate_sleep_debt(history, base_need=480)
    # (1.0*60 + 0.75*60) / (1.0 + 0.75) = 60
    assert debt == 60

    # Night with zero actual (e.g. missing) is skipped
    history_with_missing = [
        SleepNightData(k=1, need=480, actual=None),
        SleepNightData(k=2, need=480, actual=420),
    ]
    debt2 = calculate_sleep_debt(history_with_missing, base_need=480)
    assert debt2 == 60


def test_sleep_need_clamping_and_strain_bonus() -> None:
    # Base 480, debt 30, strain bonus (strain 12 -> max(0, 12-7)*3 = 15), naps 20
    need = calculate_sleep_need(base=480, debt=30, prev_strain=12.0, prev_naps=20)
    # 480 + 30 + 15 - 20 = 505
    assert need == 505

    # Clamping bounds: 360 to 660
    assert calculate_sleep_need(base=300, debt=0, prev_strain=0.0, prev_naps=100) == 360
    assert calculate_sleep_need(base=600, debt=120, prev_strain=20.0, prev_naps=0) == 660


def test_sleep_consistency_midnight_wrap() -> None:
    # Midpoints relative to 18:00 local:
    # 03:00 -> (3-18)%24 * 60 = 9 * 60 = 540 min
    # 03:10 -> 550 min
    # 02:50 -> 530 min
    midpoints = [540.0, 550.0, 530.0]  # mean 540, SD 10 min
    consistency = calculate_sleep_consistency(midpoints)
    assert consistency is not None
    # 100 - 10 * 100 / 120 = 100 - 8.33 = 92
    assert consistency == 92

    # High variability (>120 min SD) clamps to 0
    high_var = [200.0, 600.0, 100.0]
    assert calculate_sleep_consistency(high_var) == 0


def test_bedtime_plan() -> None:
    today_date = dt.date(2026, 10, 25)
    # Base 480, debt 20, strain today 10 (bonus 9), naps 0 -> need = 509 min
    # Efficiency 90% -> in_bed = 509 / 0.9 = 565.55 min (9h 25.5m)
    # Wake time default 07:00 tomorrow (2026-10-26 07:00)
    bedtime, wake = calculate_bedtime_plan(
        today_date=today_date,
        tz=PRAGUE,
        base_need=480,
        debt_with_last_night=20,
        today_strain=10.0,
        today_naps=0,
        recent_efficiencies=[90.0],
        recent_wake_times=[dt.time(7, 0)],
    )
    assert wake.date() == dt.date(2026, 10, 26)
    assert wake.hour == 7 and wake.minute == 0
    # Bedtime should be on 2026-10-25 around 21:34
    assert bedtime.date() == dt.date(2026, 10, 25)
    assert bedtime.hour == 21
    assert bedtime < wake
