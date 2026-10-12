"""Recovery readiness analysis and acute:chronic training load ratio."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessResult:
    flag: str  # "green", "amber", "red", "unknown"
    reasons: list[str]
    missing: list[str]


def calculate_acute_chronic(daily_loads_28d: Sequence[float]) -> float | None:
    """Calculate acute:chronic workload ratio from 28 daily loads.

    daily_load = hard_sets * 1 + exercise_min / 10
    acute = 7-day average of daily load (last 7 days of the 28-day window)
    chronic = 28-day average of daily load
    """
    if not daily_loads_28d:
        return None
    # Use up to the last 28 days
    loads = list(daily_loads_28d)[-28:]
    if len(loads) < 7:
        return None
    acute = sum(loads[-7:]) / 7.0
    chronic = sum(loads) / float(len(loads))
    if chronic > 0:
        return round(acute / chronic, 2)
    return 0.0 if acute == 0 else None


def evaluate_readiness(
    sleep_min: float | None,
    rhr_z: float | None,
    hrv_z: float | None,
    soreness: int | None,
    energy: int | None,
    acute_chronic_ratio: float | None,
) -> ReadinessResult:
    """Evaluate recovery readiness based on z-scores, sleep, check-ins, and workload.

    Rules:
    - red when at least two of {hrv_z <= -1.5, rhr_z >= 1.5, sleep_min < 360,
      soreness >= 4 with energy <= 2, acute:chronic > 1.5}
    - amber when at least one of {hrv_z <= -1, rhr_z >= 1, sleep_min < 390,
      soreness >= 4, energy <= 2, acute:chronic > 1.3}
    - else green.
    - Missing metrics are skipped and listed under "missing".
    - With no data at all the flag is "unknown".
    """
    missing: list[str] = []
    if sleep_min is None:
        missing.append("sleep_min")
    if rhr_z is None:
        missing.append("rhr_z")
    if hrv_z is None:
        missing.append("hrv_z")
    if soreness is None:
        missing.append("soreness")
    if energy is None:
        missing.append("energy")
    if acute_chronic_ratio is None:
        missing.append("acute_chronic")

    # If all metrics are missing:
    if (
        sleep_min is None
        and rhr_z is None
        and hrv_z is None
        and soreness is None
        and energy is None
        and acute_chronic_ratio is None
    ):
        return ReadinessResult(flag="unknown", reasons=["no data available"], missing=missing)

    red_triggers: list[str] = []
    if hrv_z is not None and hrv_z <= -1.5:
        red_triggers.append(f"HRV z-score very low ({hrv_z:+.2f} <= -1.5)")
    if rhr_z is not None and rhr_z >= 1.5:
        red_triggers.append(f"Resting HR z-score elevated ({rhr_z:+.2f} >= +1.5)")
    if sleep_min is not None and sleep_min < 360:
        red_triggers.append(f"Sleep under 6h ({int(sleep_min)} min < 360)")
    if soreness is not None and energy is not None and soreness >= 4 and energy <= 2:
        red_triggers.append(f"High soreness ({soreness}) with low energy ({energy})")
    if acute_chronic_ratio is not None and acute_chronic_ratio > 1.5:
        red_triggers.append(f"Acute:chronic load ratio very high ({acute_chronic_ratio:.2f} > 1.5)")

    if len(red_triggers) >= 2:
        return ReadinessResult(flag="red", reasons=red_triggers, missing=missing)

    amber_triggers: list[str] = []
    if hrv_z is not None and hrv_z <= -1.0:
        amber_triggers.append(f"HRV z-score depressed ({hrv_z:+.2f} <= -1.0)")
    if rhr_z is not None and rhr_z >= 1.0:
        amber_triggers.append(f"Resting HR z-score slightly elevated ({rhr_z:+.2f} >= +1.0)")
    if sleep_min is not None and sleep_min < 390:
        amber_triggers.append(f"Sleep under 6.5h ({int(sleep_min)} min < 390)")
    if soreness is not None and soreness >= 4:
        amber_triggers.append(f"High soreness ({soreness} >= 4)")
    if energy is not None and energy <= 2:
        amber_triggers.append(f"Low energy ({energy} <= 2)")
    if acute_chronic_ratio is not None and acute_chronic_ratio > 1.3:
        amber_triggers.append(
            f"Acute:chronic load ratio elevated ({acute_chronic_ratio:.2f} > 1.3)"
        )

    if len(amber_triggers) >= 1:
        return ReadinessResult(flag="amber", reasons=amber_triggers, missing=missing)

    return ReadinessResult(flag="green", reasons=[], missing=missing)
