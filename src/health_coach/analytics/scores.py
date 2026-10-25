"""Pure functions and frozen dataclasses for daily WHOOP-style scores.

Computes:
1. Robust baselines (median, MAD) over trailing nights.
2. Recovery score (0-100, green/yellow/red), z-scores, components, flags, strain target.
3. Day strain (0-21) via Banister TRIMP cardio load, muscular load, and zone minutes.
4. Sleep need, debt, performance, consistency, and bedtime plan.

Zero database dependencies. Fully deterministic and testable.
"""

import datetime as dt
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from zoneinfo import ZoneInfo

ALGO_VERSION = 1

# Recovery baseline scale floors
FLOOR_LN_HRV = 0.08
FLOOR_RHR = 1.5  # bpm
FLOOR_BREATHING_RATE = 0.5  # /min
FLOOR_SKIN_TEMP = 0.15  # degC

# Recovery component weights
WEIGHT_HRV = 0.50
WEIGHT_RHR = 0.20
WEIGHT_SLEEP_PERF = 0.15
WEIGHT_BREATHING_RATE = 0.05
WEIGHT_SKIN_TEMP = 0.05
WEIGHT_SPO2 = 0.05

# Recovery zones
ZONE_GREEN_MIN = 67
ZONE_YELLOW_MIN = 34

# Day strain anchors and defaults
DEFAULT_RESTING_HR = 60.0
DEFAULT_HR_MAX = 190.0

# Muscular load minimum caps and defaults
CAP_VOL_MIN = 5000.0  # kg
CAP_SRPE_MIN = 480.0
DEFAULT_SESSION_RPE = 7.0

# Sleep need bounds (minutes)
SLEEP_NEED_MIN = 360  # 6 hours
SLEEP_NEED_MAX = 660  # 11 hours
SLEEP_DEBT_MAX = 120  # 2 hours
SLEEP_DEBT_DECAY = 0.75


# --- 2a. Baselines --------------------------------------------------------------------


def robust_baseline(values: Sequence[float], floor: float = 0.0) -> tuple[float, float] | None:
    """Compute median (center) and 1.4826 * MAD (scale) for a sequence of values.

    Returns None when fewer than 7 values are available.
    Scale is clamped to at least `floor`.
    """
    if len(values) < 7:
        return None
    center = float(statistics.median(values))
    mad = float(statistics.median([abs(v - center) for v in values]))
    scale = max(1.4826 * mad, floor)
    return center, scale


# --- 2b. Recovery ---------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryComponent:
    signal: str
    value: float | None
    z: float
    weight: float
    points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "value": round(self.value, 2) if self.value is not None else None,
            "z": round(self.z, 2),
            "weight": round(self.weight, 3),
            "points": self.points,
        }


@dataclass(frozen=True)
class RecoveryResult:
    score: int
    z: float
    zone: str
    components: list[dict[str, Any]]
    flags: list[str]
    strain_target_low: float
    strain_target_high: float


def recovery_zone(score: int | None) -> str | None:
    """Return 'green', 'yellow', or 'red' zone for a recovery score."""
    if score is None:
        return None
    if score >= ZONE_GREEN_MIN:
        return "green"
    if score >= ZONE_YELLOW_MIN:
        return "yellow"
    return "red"


def _score_from_z(z: float) -> int:
    """Convert blended z-score to recovery score (1..99)."""
    raw = 100.0 / (1.0 + math.exp(-(1.6 * z + 0.3)))
    return max(1, min(99, round(raw)))


def calculate_recovery(
    hrv_rmssd: float | None = None,
    resting_hr: float | None = None,
    breathing_rate: float | None = None,
    skin_temp_delta: float | None = None,
    spo2_avg: float | None = None,
    sleep_performance: float | None = None,
    hrv_baseline: tuple[float, float] | None = None,
    rhr_baseline: tuple[float, float] | None = None,
    breathing_baseline: tuple[float, float] | None = None,
    skin_temp_baseline: tuple[float, float] | None = None,
    prev_rhr: float | None = None,
    prev_rmssd: float | None = None,
) -> RecoveryResult | None:
    """Calculate daily recovery score (1-99) for local day D.

    Inputs are from the night ending on D.
    Returns None if both HRV and resting HR are missing (or lack valid baselines).
    """
    signals: list[tuple[str, float | None, float, float]] = []  # (name, raw_val, z, weight)

    # 1. HRV: (ln(rmssd) - center) / scale, weight 0.50
    hrv_valid = False
    if hrv_rmssd is not None and hrv_rmssd > 0 and hrv_baseline is not None:
        center, scale = hrv_baseline
        z = (math.log(hrv_rmssd) - center) / scale
        z = max(-3.0, min(3.0, z))
        signals.append(("hrv", hrv_rmssd, z, WEIGHT_HRV))
        hrv_valid = True

    # 2. Resting HR: (center - rhr) / scale, weight 0.20
    rhr_valid = False
    if resting_hr is not None and rhr_baseline is not None:
        center, scale = rhr_baseline
        z = (center - resting_hr) / scale
        z = max(-3.0, min(3.0, z))
        signals.append(("resting_hr", resting_hr, z, WEIGHT_RHR))
        rhr_valid = True

    # If both HRV and resting HR are missing, recovery is None
    if not hrv_valid and not rhr_valid:
        return None

    # 3. Sleep performance: (perf/100 - 0.85) / 0.12, weight 0.15
    if sleep_performance is not None:
        perf_ratio = sleep_performance / 100.0
        z = (perf_ratio - 0.85) / 0.12
        z = max(-3.0, min(3.0, z))
        signals.append(("sleep_performance", sleep_performance, z, WEIGHT_SLEEP_PERF))

    # 4. Breathing rate: (center - rate) / scale, weight 0.05
    if breathing_rate is not None and breathing_baseline is not None:
        center, scale = breathing_baseline
        z = (center - breathing_rate) / scale
        z = max(-3.0, min(3.0, z))
        signals.append(("breathing_rate", breathing_rate, z, WEIGHT_BREATHING_RATE))

    # 5. Skin temperature: -abs(delta - center) / max(scale, 0.3), weight 0.05
    if skin_temp_delta is not None and skin_temp_baseline is not None:
        center, scale = skin_temp_baseline
        z = -abs(skin_temp_delta - center) / max(scale, 0.3)
        z = max(-3.0, min(3.0, z))
        signals.append(("skin_temperature", skin_temp_delta, z, WEIGHT_SKIN_TEMP))

    # 6. SpO2: min(0, (spo2 - 95) / 2.5), weight 0.05 (no baseline)
    if spo2_avg is not None:
        z = min(0.0, (spo2_avg - 95.0) / 2.5)
        z = max(-3.0, min(3.0, z))
        signals.append(("spo2", spo2_avg, z, WEIGHT_SPO2))

    total_weight = sum(w for _, _, _, w in signals)
    blended_z = sum(w * z for _, _, z, w in signals) / total_weight
    score = _score_from_z(blended_z)

    # Compute components with individual point impact
    components: list[dict[str, Any]] = []
    for name, val, z, w in signals:
        renorm_weight = w / total_weight
        z_sub = blended_z - renorm_weight * z
        score_sub = _score_from_z(z_sub)
        points = score - score_sub

        comp = RecoveryComponent(
            signal=name,
            value=val,
            z=z,
            weight=renorm_weight,
            points=points,
        )
        components.append(comp.to_dict())

    # Flags
    flags: list[str] = []
    # illness: resting HR > center+5 and RMSSD < 0.85*exp(lnHRV center) on D and D-1
    if rhr_baseline is not None and hrv_baseline is not None:
        rhr_center = rhr_baseline[0]
        hrv_exp_center = math.exp(hrv_baseline[0])
        d_ill = (
            resting_hr is not None
            and resting_hr > rhr_center + 5.0
            and hrv_rmssd is not None
            and hrv_rmssd < 0.85 * hrv_exp_center
        )
        prev_ill = (
            prev_rhr is not None
            and prev_rhr > rhr_center + 5.0
            and prev_rmssd is not None
            and prev_rmssd < 0.85 * hrv_exp_center
        )
        if d_ill and prev_ill:
            flags.append("illness")

    # temperature: abs(skin delta - center) >= 0.6
    if (
        skin_temp_delta is not None
        and skin_temp_baseline is not None
        and abs(skin_temp_delta - skin_temp_baseline[0]) >= 0.6
    ):
        flags.append("temperature")

    # low_spo2: spo2_avg < 94
    if spo2_avg is not None and spo2_avg < 94.0:
        flags.append("low_spo2")

    r = score / 100.0
    target_low = round(3.0 + 12.0 * r, 1)
    target_high = round(6.0 + 12.0 * r, 1)

    return RecoveryResult(
        score=score,
        z=round(blended_z, 2),
        zone=recovery_zone(score) or "yellow",
        components=components,
        flags=flags,
        strain_target_low=target_low,
        strain_target_high=target_high,
    )


# --- 2c. Day Strain -------------------------------------------------------------------


@dataclass(frozen=True)
class StrengthSetData:
    reps: float | None = None
    weight_kg: float | None = None
    rir: float | None = None
    rpe: float | None = None
    is_warmup: bool = False


@dataclass(frozen=True)
class StrengthSessionData:
    id: Any
    name: str
    start_ts: dt.datetime | None = None
    end_ts: dt.datetime | None = None
    duration_min: float | None = None
    sets: list[StrengthSetData] = field(default_factory=list)


@dataclass(frozen=True)
class ExerciseSessionData:
    id: Any
    kind: str
    name: str
    start_ts: dt.datetime
    end_ts: dt.datetime
    duration_min: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None


@dataclass(frozen=True)
class DayStrainResult:
    strain: float
    cardio_load: float
    muscular_load: float
    zone_minutes: dict[str, int]
    activities: list[dict[str, Any]]


def resample_hr_1min(
    samples: Sequence[tuple[dt.datetime, float]],
) -> list[tuple[dt.datetime, float]]:
    """Resample raw HR samples to 1-minute means.

    A minute counts only if it has at least one sample.
    """
    if not samples:
        return []

    buckets: dict[dt.datetime, list[float]] = {}
    for ts, bpm in samples:
        minute_ts = ts.replace(second=0, microsecond=0)
        buckets.setdefault(minute_ts, []).append(float(bpm))

    sorted_minutes = sorted(buckets.keys())
    res: list[tuple[dt.datetime, float]] = []
    for m in sorted_minutes:
        vals = buckets[m]
        res.append((m, sum(vals) / len(vals)))
    return res


def calculate_percentile(values: Sequence[float], percentile: float) -> float:
    """Calculate the given percentile (0..100) using linear interpolation."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    d0 = s[f] * (c - k)
    d1 = s[c] * (k - f)
    return float(d0 + d1)


def hrr_fraction(hr: float, rest_hr: float, hr_max: float) -> float:
    """Compute clamped %HRR fraction x = clamp((hr - rest) / (hr_max - rest), 0, 1)."""
    if hr_max <= rest_hr:
        return 0.0
    return min(1.0, max(0.0, (hr - rest_hr) / (hr_max - rest_hr)))


def _session_volume_srpe(session: StrengthSessionData) -> tuple[float, float]:
    """Compute (volume_kg, sRPE) for a strength session."""
    working_sets = [s for s in session.sets if not s.is_warmup]
    volume = sum((s.reps or 0.0) * (s.weight_kg or 0.0) for s in working_sets)

    rpes = [float(s.rpe) for s in working_sets if s.rpe is not None]
    rirs = [float(s.rir) for s in working_sets if s.rir is not None]
    if rpes:
        session_rpe = sum(rpes) / len(rpes)
    elif rirs:
        session_rpe = sum(10.0 - r for r in rirs) / len(rirs)
    else:
        session_rpe = DEFAULT_SESSION_RPE

    dur = session.duration_min
    if dur is None or dur <= 0:
        if session.start_ts and session.end_ts:
            dur = max(0.0, (session.end_ts - session.start_ts).total_seconds() / 60.0)
        else:
            dur = 45.0
    srpe = session_rpe * dur
    return volume, srpe


def calculate_muscular_caps(
    historical_sessions: Sequence[StrengthSessionData],
) -> tuple[float, float]:
    """Compute 90th percentile caps for volume and sRPE over trailing 30 days.

    Enforces minimums: cap_vol >= 5000 kg, cap_srpe >= 480.
    """
    volumes: list[float] = []
    srpes: list[float] = []
    for sess in historical_sessions:
        vol, srpe = _session_volume_srpe(sess)
        volumes.append(vol)
        srpes.append(srpe)

    cap_vol = max(CAP_VOL_MIN, calculate_percentile(volumes, 90.0) if volumes else CAP_VOL_MIN)
    cap_srpe = max(CAP_SRPE_MIN, calculate_percentile(srpes, 90.0) if srpes else CAP_SRPE_MIN)
    return cap_vol, cap_srpe


def calculate_session_muscular_load(
    session: StrengthSessionData,
    cap_vol: float,
    cap_srpe: float,
) -> tuple[float, float, float]:
    """Compute (volume, sRPE, muscular_load) for one strength session."""
    volume, srpe = _session_volume_srpe(session)
    score = min(100.0, max(0.0, 50.0 * volume / cap_vol + 50.0 * srpe / cap_srpe))
    muscular_load = 45.0 * ((score / 100.0) ** 1.6)
    return volume, srpe, muscular_load


def hr_gate(x: float, inside_window: bool) -> float:
    """Scale factor gating HR effort x (%HRR).

    x < 0.30 -> 0;
    0.30 <= x < 0.40 outside window -> scale (x - 0.30) / 0.10;
    x >= 0.40 or inside window -> 1.
    """
    if x < 0.30:
        return 0.0
    if 0.30 <= x < 0.40 and not inside_window:
        return (x - 0.30) / 0.10
    return 1.0


def banister_weight(x: float, sex: Literal["male", "female"] | None) -> float:
    """Banister TRIMP weighting factor y(x)."""
    if sex == "male":
        return 0.64 * math.exp(1.92 * x)
    if sex == "female":
        return 0.86 * math.exp(1.67 * x)
    return 0.5 * (0.64 * math.exp(1.92 * x) + 0.86 * math.exp(1.67 * x))


def calculate_strain_from_load(load: float) -> float:
    """Compute 0-21 strain score from total load."""
    if load <= 0:
        return 0.0
    return round(21.0 * (1.0 - math.exp(-load / 100.0)), 1)


def _build_activity_load(
    kind: str,
    name: str,
    start_ts: dt.datetime,
    end_ts: dt.datetime,
    minute_hr: Sequence[tuple[dt.datetime, float]],
    rest_hr: float,
    hr_max: float,
    sex: Literal["male", "female"] | None,
    extra_load: float = 0.0,
    fallback_avg_hr: int | None = None,
    fallback_max_hr: int | None = None,
) -> dict[str, Any]:
    """Compute activity load, strain, and HR stats within a time window."""
    hrs_in_window = [hr for ts, hr in minute_hr if start_ts <= ts <= end_ts]
    window_cardio = sum(
        hrr_fraction(hr, rest_hr, hr_max) * banister_weight(hrr_fraction(hr, rest_hr, hr_max), sex)
        for ts, hr in minute_hr
        if start_ts <= ts <= end_ts and hrr_fraction(hr, rest_hr, hr_max) >= 0.30
    )
    avg_hr = round(sum(hrs_in_window) / len(hrs_in_window)) if hrs_in_window else fallback_avg_hr
    max_hr = round(max(hrs_in_window)) if hrs_in_window else fallback_max_hr
    total_load = round(window_cardio + extra_load, 1)
    return {
        "kind": kind,
        "name": name,
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "load": total_load,
        "strain": calculate_strain_from_load(total_load),
    }


def calculate_day_strain(
    minute_hr: Sequence[tuple[dt.datetime, float]],
    rest_hr: float = DEFAULT_RESTING_HR,
    hr_max: float = DEFAULT_HR_MAX,
    sex: Literal["male", "female"] | None = None,
    exercise_sessions: Sequence[ExerciseSessionData] = (),
    strength_sessions: Sequence[StrengthSessionData] = (),
    caps: tuple[float, float] = (CAP_VOL_MIN, CAP_SRPE_MIN),
) -> DayStrainResult:
    """Calculate day strain and activity loads for local calendar day D."""
    if hr_max <= rest_hr:
        hr_max = rest_hr + 1.0

    cap_vol, cap_srpe = caps

    # Collect activity windows [start, end]
    all_windows: list[tuple[dt.datetime, dt.datetime]] = []
    for ex in exercise_sessions:
        all_windows.append((ex.start_ts, ex.end_ts))
    for st in strength_sessions:
        if st.start_ts and st.end_ts:
            all_windows.append((st.start_ts, st.end_ts))

    cardio_load = 0.0
    zone_minutes: dict[str, int] = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}

    for ts, hr in minute_hr:
        x = hrr_fraction(hr, rest_hr, hr_max)
        inside = any(w_start <= ts <= w_end for w_start, w_end in all_windows)
        scale = hr_gate(x, inside)
        y = banister_weight(x, sex)
        minute_load = x * y * scale
        cardio_load += minute_load

        # Zone minutes by %HRR (x)
        if x >= 0.90:
            zone_minutes["Z5"] += 1
        elif x >= 0.80:
            zone_minutes["Z4"] += 1
        elif x >= 0.70:
            zone_minutes["Z3"] += 1
        elif x >= 0.60:
            zone_minutes["Z2"] += 1
        elif x >= 0.50:
            zone_minutes["Z1"] += 1

    # Muscular load per strength session
    total_muscular_load = 0.0
    strength_muscular_loads: dict[Any, float] = {}
    for st in strength_sessions:
        _, _, m_load = calculate_session_muscular_load(st, cap_vol, cap_srpe)
        total_muscular_load += m_load
        strength_muscular_loads[st.id] = m_load

    total_load = cardio_load + total_muscular_load
    strain = calculate_strain_from_load(total_load)

    # Activity breakdown
    activities: list[dict[str, Any]] = []

    # 1. Exercise sessions
    for ex in exercise_sessions:
        activities.append(
            _build_activity_load(
                kind=ex.kind or "exercise",
                name=ex.name,
                start_ts=ex.start_ts,
                end_ts=ex.end_ts,
                minute_hr=minute_hr,
                rest_hr=rest_hr,
                hr_max=hr_max,
                sex=sex,
                fallback_avg_hr=ex.avg_hr,
                fallback_max_hr=ex.max_hr,
            )
        )

    # 2. Strength sessions
    for st in strength_sessions:
        if not (st.start_ts and st.end_ts):
            continue
        m_load = strength_muscular_loads.get(st.id, 0.0)
        activities.append(
            _build_activity_load(
                kind="strength",
                name=st.name,
                start_ts=st.start_ts,
                end_ts=st.end_ts,
                minute_hr=minute_hr,
                rest_hr=rest_hr,
                hr_max=hr_max,
                sex=sex,
                extra_load=m_load,
            )
        )

    # Sort activities by start time
    activities.sort(key=lambda a: a.get("start") or "")

    return DayStrainResult(
        strain=strain,
        cardio_load=round(cardio_load, 1),
        muscular_load=round(total_muscular_load, 1),
        zone_minutes=zone_minutes,
        activities=activities,
    )


# --- 2d. Sleep Need and Performance ---------------------------------------------------


@dataclass(frozen=True)
class SleepNightData:
    k: int  # 1..14 nights back
    need: int | None
    actual: int | None


@dataclass(frozen=True)
class SleepDayResult:
    need: int
    actual: int | None
    debt: int
    performance: int | None
    efficiency: int | None
    consistency: int | None
    planned_bedtime: dt.datetime | None
    planned_wake: dt.datetime | None


def calculate_sleep_debt(
    history: Sequence[SleepNightData],
    base_need: int,
) -> int:
    """Calculate accumulated sleep debt over k = 1..14 nights.

    debt = min(120, sum_k 0.75^(k-1) * max(0, need(D-k) - actual(D-k)) / sum_k 0.75^(k-1))
    over nights that have both values.
    """
    numerator = 0.0
    denominator = 0.0
    for night in history:
        if night.actual is None:
            continue
        effective_need = float(night.need if night.need is not None else base_need)
        deficit = max(0.0, effective_need - float(night.actual))
        weight = SLEEP_DEBT_DECAY ** (night.k - 1)
        numerator += weight * deficit
        denominator += weight

    if denominator <= 0:
        return 0
    return min(SLEEP_DEBT_MAX, round(numerator / denominator))


def calculate_sleep_need(
    base: int,
    debt: int,
    prev_strain: float | None = None,
    prev_naps: int = 0,
) -> int:
    """Calculate sleep need: clamp(base + debt + strain_bonus - nap_credit, 360, 660)."""
    strain_bonus = max(0.0, (prev_strain or 0.0) - 7.0) * 3.0
    raw_need = base + debt + round(strain_bonus) - prev_naps
    return max(SLEEP_NEED_MIN, min(SLEEP_NEED_MAX, raw_need))


def calculate_sleep_consistency(
    midpoint_minutes: Sequence[float],
) -> int | None:
    """Calculate sleep consistency score (0..100) from SD of midpoints relative to 18:00 local.

    consistency = clamp(100 - SD * 100 / 120, 0, 100).
    Requires at least 2 midpoints.
    """
    if len(midpoint_minutes) < 2:
        return None
    sd = statistics.stdev(midpoint_minutes)
    score = 100.0 - sd * 100.0 / 120.0
    return max(0, min(100, round(score)))


def calculate_bedtime_plan(
    today_date: dt.date,
    tz: ZoneInfo,
    base_need: int,
    debt_with_last_night: int,
    today_strain: float | None = None,
    today_naps: int = 0,
    recent_efficiencies: Sequence[float] = (),
    recent_wake_times: Sequence[dt.time] = (),
) -> tuple[dt.datetime, dt.datetime]:
    """Calculate (planned_bedtime, planned_wake) for tonight."""
    strain_bonus = max(0.0, (today_strain or 0.0) - 7.0) * 3.0
    raw_need_tonight = base_need + debt_with_last_night + round(strain_bonus) - today_naps
    need_tonight = max(SLEEP_NEED_MIN, min(SLEEP_NEED_MAX, raw_need_tonight))

    if recent_efficiencies:
        valid_effs = [e / 100.0 for e in recent_efficiencies if e > 0]
        mean_eff = sum(valid_effs) / len(valid_effs) if valid_effs else 0.90
    else:
        mean_eff = 0.90
    if mean_eff <= 0.1:
        mean_eff = 0.90

    in_bed_min = need_tonight / mean_eff

    if recent_wake_times:
        wake_mins = [t.hour * 60 + t.minute + t.second / 60.0 for t in recent_wake_times]
        median_wake_min = float(statistics.median(wake_mins))
    else:
        median_wake_min = 7.0 * 60.0  # default 07:00

    tomorrow = today_date + dt.timedelta(days=1)
    wake_dt = dt.datetime.combine(tomorrow, dt.time(0, 0), tz) + dt.timedelta(
        minutes=median_wake_min
    )
    bedtime_dt = wake_dt - dt.timedelta(minutes=in_bed_min)
    return bedtime_dt, wake_dt
