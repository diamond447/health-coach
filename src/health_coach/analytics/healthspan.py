"""Pure functions and frozen dataclasses for estimated biological age (healthspan).

Converts 9 lifestyle and physiological factors into all-cause mortality hazard ratios (HR)
relative to reference values, then translates them into biological age delta years using
the Gompertz rule of thumb (mortality risk doubles roughly every 8 years):
    years = (8 / ln(2)) * ln(HR)  (~11.54 * ln(HR))
Negative years indicate a younger biological age; positive years indicate an older age.

Literature references:
1. Sleep regularity: Windred et al. 2024, SLEEP.
2. Sleep duration: Cappuccio et al. 2010, Sleep.
3. Moderate activity: Lee et al. 2022, Circulation.
4. Vigorous activity: Lee et al. 2022, Circulation.
5. Strength training: Momma et al. 2022, BJSM (J-shaped curve).
6. Daily steps: Paluch et al. 2022, Lancet Public Health (under-60 curve).
7. Resting heart rate: Zhang et al. 2016, CMAJ.
8. VO2max: Kodama et al. 2009, JAMA.
9. Body composition: Heitmann et al. / standard body fat mortality curves (weak evidence).

Zero database dependencies. Fully deterministic and testable.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

ALGO_VERSION = 2

# Gompertz rule of thumb: mortality doubles every ~8 years.
GOMPERTZ_DOUBLING_YEARS = 8.0
GOMPERTZ_SCALE = GOMPERTZ_DOUBLING_YEARS / math.log(2.0)  # ~11.5415603

# Clamping bounds
FACTOR_YEARS_CLAMP_DEFAULT = (-3.0, 3.0)
FACTOR_YEARS_CLAMP_BODY_FAT = (-1.5, 1.5)
TOTAL_YEARS_CLAMP = (-10.0, 10.0)
PACE_CLAMP = (0.5, 1.5)

MIN_WEEKS_PER_FACTOR = 4
MIN_WEEKS_FOR_PACE = 8

# 1. Sleep regularity anchors (Windred et al. 2024, SLEEP)
# consistency score 0-100 (daily_scores.sleep_consistency mean)
ANCHORS_SLEEP_REGULARITY: list[tuple[float, float]] = [
    (40.0, 1.30),
    (70.0, 1.00),
    (90.0, 0.85),
]

# 2. Sleep duration anchors (Cappuccio et al. 2010, Sleep)
# mean hours of main sleep (daily_scores.sleep_actual_min / 60)
ANCHORS_SLEEP_DURATION: list[tuple[float, float]] = [
    (5.0, 1.30),
    (6.0, 1.12),
    (7.0, 1.00),
    (8.0, 1.00),
    (9.0, 1.15),
    (10.0, 1.30),
]

# 3. Moderate activity anchors (Lee et al. 2022, Circulation)
# minutes per week in HR zones 1-3 (daily_scores.zone_minutes Z1-Z3, weekly mean)
ANCHORS_MODERATE_ACTIVITY: list[tuple[float, float]] = [
    (0.0, 1.25),
    (75.0, 1.00),
    (150.0, 0.85),
    (300.0, 0.78),
]

# 4. Vigorous activity anchors (Lee et al. 2022, Circulation)
# minutes per week in HR zones 4-5 (daily_scores.zone_minutes Z4-Z5, weekly mean)
ANCHORS_VIGOROUS_ACTIVITY: list[tuple[float, float]] = [
    (0.0, 1.05),
    (20.0, 1.00),
    (75.0, 0.85),
    (150.0, 0.80),
]

# 5. Strength training anchors (Momma et al. 2022, BJSM: J-shape)
# hours per week (strength_sessions duration, weekly mean)
ANCHORS_STRENGTH_TRAINING: list[tuple[float, float]] = [
    (0.0, 1.10),
    (0.5, 0.90),
    (1.0, 0.85),
    (2.5, 0.90),
    (4.0, 0.95),
]

# 6. Steps per day anchors (Paluch et al. 2022, Lancet Public Health: under-60 curve)
# daily_activity.steps mean
ANCHORS_STEPS: list[tuple[float, float]] = [
    (2500.0, 1.40),
    (4000.0, 1.20),
    (6000.0, 1.00),
    (8000.0, 0.85),
    (10000.0, 0.78),
    (12000.0, 0.76),
]

# 8. VO2max reference tables by decade (Kodama et al. 2009, JAMA)
# Male decade references: <30: 44, 30-39: 42, 40-49: 39, 50-59: 36, 60+: 32.
# Female reference is 6 lower across each decade.
VO2MAX_REF_MALE: list[tuple[int, float]] = [
    (30, 44.0),
    (40, 42.0),
    (50, 39.0),
    (60, 36.0),
]
VO2MAX_REF_MALE_60_PLUS = 32.0
VO2MAX_FEMALE_DELTA = -6.0

# 9. Body composition anchors (Weak evidence, Heitmann et al.)
# body_fat_pct latest 8-week median. Female is +8 points on each anchor.
ANCHORS_BODY_FAT_MALE: list[tuple[float, float]] = [
    (10.0, 1.00),
    (18.0, 1.00),
    (25.0, 1.10),
    (30.0, 1.25),
]
BODY_FAT_FEMALE_DELTA = 8.0
ANCHORS_BODY_FAT_FEMALE: list[tuple[float, float]] = [
    (x + BODY_FAT_FEMALE_DELTA, hr) for x, hr in ANCHORS_BODY_FAT_MALE
]


# --- Core Math Helpers ----------------------------------------------------------------


def interpolate_log_hr(x: float, anchors: Sequence[tuple[float, float]]) -> float:
    """Piecewise-linear interpolation in log HR between anchor points.

    Values outside the anchor endpoints are held at the end points.
    """
    if not anchors:
        raise ValueError("anchors must not be empty")
    if len(anchors) == 1 or x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]

    for i in range(len(anchors) - 1):
        x0, hr0 = anchors[i]
        x1, hr1 = anchors[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return hr0
            t = (x - x0) / (x1 - x0)
            ln_hr = math.log(hr0) + t * (math.log(hr1) - math.log(hr0))
            return math.exp(ln_hr)

    return anchors[-1][1]


def hr_to_years(
    hr: float,
    clamp: tuple[float, float] = FACTOR_YEARS_CLAMP_DEFAULT,
) -> float:
    """Convert hazard ratio to biological age delta in years via Gompertz rule of thumb:

    years = (8 / ln(2)) * ln(HR)
    """
    if hr <= 0.0:
        raise ValueError(f"hazard ratio must be positive, got {hr}")
    years = GOMPERTZ_SCALE * math.log(hr)
    return max(clamp[0], min(clamp[1], years))


# --- Data Structures ------------------------------------------------------------------


@dataclass(frozen=True)
class FactorResult:
    key: str
    name: str
    value: float | None
    unit: str
    goal: str
    hr: float | None
    years: float | None
    has_data: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "value": round(self.value, 1) if self.value is not None else None,
            "unit": self.unit,
            "goal": self.goal,
            "hr": round(self.hr, 3) if self.hr is not None else None,
            "years": round(self.years, 1) if self.years is not None else None,
            "has_data": self.has_data,
        }


@dataclass(frozen=True)
class HealthspanResult:
    delta_years: float | None
    pace: float | None
    age: int | None
    biological_age: float | None
    factors: list[FactorResult]
    factors_with_data: int
    algo_version: int = ALGO_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_years": round(self.delta_years, 1) if self.delta_years is not None else None,
            "pace": round(self.pace, 2) if self.pace is not None else None,
            "age": self.age,
            "biological_age": (
                round(self.biological_age, 1) if self.biological_age is not None else None
            ),
            "factors": [f.to_dict() for f in self.factors],
            "factors_with_data": self.factors_with_data,
            "algo_version": self.algo_version,
        }


# --- Factor Curve Implementations ----------------------------------------------------


def sleep_regularity_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 1: Sleep regularity (Windred et al. 2024, SLEEP).

    daily_scores.sleep_consistency mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="sleep_regularity",
            name="Pravidelnost spánku",
            value=None,
            unit="%",
            goal="≥ 85 %",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_SLEEP_REGULARITY)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="sleep_regularity",
        name="Pravidelnost spánku",
        value=round(value, 1),
        unit="%",
        goal="≥ 85 %",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def sleep_duration_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 2: Sleep duration in hours (Cappuccio et al. 2010, Sleep).

    daily_scores.sleep_actual_min / 60 mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="sleep_duration",
            name="Délka spánku",
            value=None,
            unit="h",
            goal="7\u20139 h",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_SLEEP_DURATION)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="sleep_duration",
        name="Délka spánku",
        value=round(value, 2),
        unit="h",
        goal="7\u20139 h",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def moderate_activity_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 3: Moderate activity, minutes per week in HR zones 1-3 (Lee et al. 2022, Circulation).

    daily_scores.zone_minutes Z1-Z3, weekly mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="moderate_activity",
            name="Minuty v zónách 1\u20133",
            value=None,
            unit="min/týden",
            goal="≥ 150 min",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_MODERATE_ACTIVITY)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="moderate_activity",
        name="Minuty v zónách 1\u20133",
        value=round(value, 1),
        unit="min/týden",
        goal="≥ 150 min",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def vigorous_activity_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 4: Vigorous activity, minutes per week in zones 4-5 (Lee et al. 2022, Circulation).

    daily_scores.zone_minutes Z4-Z5, weekly mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="vigorous_activity",
            name="Minuty v zónách 4\u20135",
            value=None,
            unit="min/týden",
            goal="≥ 75 min",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_VIGOROUS_ACTIVITY)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="vigorous_activity",
        name="Minuty v zónách 4\u20135",
        value=round(value, 1),
        unit="min/týden",
        goal="≥ 75 min",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def strength_training_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 5: Strength training, hours per week (Momma et al. 2022, BJSM: J-shape).

    strength_sessions duration, weekly mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="strength_training",
            name="Posilování",
            value=None,
            unit="h/týden",
            goal="1\u20132,5 h",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_STRENGTH_TRAINING)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="strength_training",
        name="Posilování",
        value=round(value, 2),
        unit="h/týden",
        goal="1\u20132,5 h",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def steps_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 6: Steps per day (Paluch et al. 2022, Lancet Public Health: under-60 curve).

    daily_activity.steps mean over trailing 26 weeks.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="steps",
            name="Kroky",
            value=None,
            unit="/den",
            goal="≥ 8 000/den",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = interpolate_log_hr(value, ANCHORS_STEPS)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="steps",
        name="Kroky",
        value=round(value, 0),
        unit="/den",
        goal="≥ 8 000/den",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def resting_hr_factor(value: float | None, weeks_count: int = 4) -> FactorResult:
    """Factor 7: Resting HR (Zhang et al. 2016, CMAJ).

    daily_vitals.resting_hr median over trailing 26 weeks.
    HR per 10 bpm = 1.09 relative to 60 bpm.
    """
    if value is None or weeks_count < MIN_WEEKS_PER_FACTOR:
        return FactorResult(
            key="resting_hr",
            name="Klidový tep",
            value=None,
            unit="bpm",
            goal="≤ 60 bpm",
            hr=None,
            years=None,
            has_data=False,
        )
    hr = 1.09 ** ((value - 60.0) / 10.0)
    years = hr_to_years(hr, FACTOR_YEARS_CLAMP_DEFAULT)
    return FactorResult(
        key="resting_hr",
        name="Klidový tep",
        value=round(value, 1),
        unit="bpm",
        goal="≤ 60 bpm",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def get_vo2max_ref(age: int, sex: Literal["male", "female"]) -> float:
    """VO2max reference by age decade and sex (Kodama et al. 2009, JAMA)."""
    for max_age, ref in VO2MAX_REF_MALE:
        if age < max_age:
            return ref if sex == "male" else ref + VO2MAX_FEMALE_DELTA
    female_ref = VO2MAX_REF_MALE_60_PLUS + VO2MAX_FEMALE_DELTA
    return VO2MAX_REF_MALE_60_PLUS if sex == "male" else female_ref


def vo2max_factor(
    value: float | None,
    age: int | None,
    sex: Literal["male", "female"] | None = None,
) -> FactorResult:
    """Factor 8: VO2max (Kodama et al. 2009, JAMA).

    daily_vitals.cardio_fitness, latest 8-week median.
    HR = 0.87 per +3.5 ml/kg/min relative to an age/sex reference.
    When sex is None, uses arithmetic mean of male and female results.
    Without data (or without age): 'no data'.
    """
    if value is None or age is None:
        return FactorResult(
            key="vo2max",
            name="VO2max",
            value=round(value, 1) if value is not None else None,
            unit="ml/kg/min",
            goal="podle věku",
            hr=None,
            years=None,
            has_data=False,
        )

    def _eval_sex(s: Literal["male", "female"]) -> tuple[float, float]:
        ref = get_vo2max_ref(age, s)
        diff = value - ref
        # HR = 0.87 ** (diff / 3.5)
        hr_val = 0.87 ** (diff / 3.5)
        yr_val = hr_to_years(hr_val, FACTOR_YEARS_CLAMP_DEFAULT)
        return hr_val, yr_val

    if sex is not None:
        hr, years = _eval_sex(sex)
    else:
        hr_m, yr_m = _eval_sex("male")
        hr_f, yr_f = _eval_sex("female")
        hr = (hr_m + hr_f) / 2.0
        years = (yr_m + yr_f) / 2.0

    return FactorResult(
        key="vo2max",
        name="VO2max",
        value=round(value, 1),
        unit="ml/kg/min",
        goal="podle věku",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


def body_composition_factor(
    value: float | None,
    sex: Literal["male", "female"] | None = None,
) -> FactorResult:
    """Factor 9: Body composition: body_fat_pct (Heitmann et al., weak evidence).

    body_metrics, latest 8-week median.
    Anchors male: 10 -> 1.00, 18 -> 1.00, 25 -> 1.10, 30 -> 1.25.
    Female: +8 points on each anchor.
    Clamped to [-1.5, +1.5] years.
    When sex is None, uses arithmetic mean of male and female results.
    """
    if value is None:
        return FactorResult(
            key="body_composition",
            name="Podíl svalové hmoty",
            value=None,
            unit="%",
            goal="podle věku",
            hr=None,
            years=None,
            has_data=False,
        )

    def _eval_sex(s: Literal["male", "female"]) -> tuple[float, float]:
        anchors = ANCHORS_BODY_FAT_MALE if s == "male" else ANCHORS_BODY_FAT_FEMALE
        hr_val = interpolate_log_hr(value, anchors)
        yr_val = hr_to_years(hr_val, FACTOR_YEARS_CLAMP_BODY_FAT)
        return hr_val, yr_val

    if sex is not None:
        hr, years = _eval_sex(sex)
    else:
        hr_m, yr_m = _eval_sex("male")
        hr_f, yr_f = _eval_sex("female")
        hr = (hr_m + hr_f) / 2.0
        years = (yr_m + yr_f) / 2.0

    return FactorResult(
        key="body_composition",
        name="Podíl svalové hmoty",
        value=round(value, 1),
        unit="%",
        goal="podle věku",
        hr=round(hr, 3),
        years=round(years, 1),
        has_data=True,
    )


# --- Pace of Aging --------------------------------------------------------------------


def calculate_pace_of_aging(
    series: Sequence[float] | Sequence[tuple[dt.date, float]],
) -> float | None:
    """Calculate pace of aging over weekly biological age deltas.

    pace = 1 + slope of delta years per calendar year (least squares over weekly values),
    clamped to [0.5, 1.5]; returns None with fewer than 8 weekly values.
    """
    if len(series) < MIN_WEEKS_FOR_PACE:
        return None

    # Handle sequence of dates+floats or plain floats
    points: list[tuple[float, float]] = []
    first_item = series[0]
    if isinstance(first_item, tuple):
        date_series: list[tuple[dt.date, float]] = [
            (item[0], float(item[1]))
            for item in series
            if isinstance(item, tuple) and len(item) == 2 and item[1] is not None
        ]
        if len(date_series) < MIN_WEEKS_FOR_PACE:
            return None
        d0 = date_series[0][0]
        for d, y in date_series:
            # Calendar year in Julian days
            t = (d - d0).days / 365.25
            points.append((t, y))
    else:
        float_series: list[float] = [
            float(item) for item in series if not isinstance(item, tuple) and item is not None
        ]
        if len(float_series) < MIN_WEEKS_FOR_PACE:
            return None
        for i, y in enumerate(float_series):
            # 52 weeks per year
            points.append((i / 52.0, y))

    n = len(points)
    if n < MIN_WEEKS_FOR_PACE:
        return None

    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    mean_x = sum_x / n
    mean_y = sum_y / n

    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if denom == 0.0:
        slope = 0.0
    else:
        numer = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
        slope = numer / denom

    pace = 1.0 + slope
    return max(PACE_CLAMP[0], min(PACE_CLAMP[1], pace))


# --- Healthspan Aggregator ------------------------------------------------------------


def calculate_healthspan(
    factors: Sequence[FactorResult],
    age: int | None = None,
    weekly_deltas: Sequence[float] | Sequence[tuple[dt.date, float]] = (),
) -> HealthspanResult:
    """Combine individual factor results into total delta years, pace, and biological age."""
    factors_list = list(factors)
    active_factors = [f for f in factors_list if f.has_data and f.years is not None]
    factors_with_data = len(active_factors)

    if factors_with_data == 0:
        delta_years: float | None = None
    else:
        raw_delta = sum(f.years for f in active_factors if f.years is not None)
        delta_years = max(TOTAL_YEARS_CLAMP[0], min(TOTAL_YEARS_CLAMP[1], raw_delta))
        delta_years = round(delta_years, 1)

    pace = calculate_pace_of_aging(weekly_deltas)

    biological_age: float | None = None
    if age is not None and delta_years is not None:
        biological_age = round(age + delta_years, 1)

    return HealthspanResult(
        delta_years=delta_years,
        pace=round(pace, 2) if pace is not None else None,
        age=age,
        biological_age=biological_age,
        factors=factors_list,
        factors_with_data=factors_with_data,
        algo_version=ALGO_VERSION,
    )
