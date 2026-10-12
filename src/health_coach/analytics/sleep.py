"""Pure functions for sleep analysis, bedtime consistency, and sleep debt."""

import datetime as dt
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SleepAnalysisResult:
    avg_duration_min: float | None
    avg_efficiency: float | None
    avg_deep_min: float | None
    avg_light_min: float | None
    avg_rem_min: float | None
    avg_awake_min: float | None
    bedtime_consistency_sd_min: float | None
    sleep_debt_min: int
    worst_nights: list[dict[str, Any]]


def calculate_bedtime_minutes(start_dt: dt.datetime, tz: ZoneInfo) -> float:
    """Calculate minutes relative to 18:00 local time to handle midnight wrap.

    Examples:
    18:00 -> 0 min
    23:30 -> 330 min
    00:30 -> 390 min
    02:00 -> 480 min
    """
    local = start_dt.astimezone(tz)
    return float(((local.hour - 18) % 24) * 60 + local.minute + local.second / 60.0)


def calculate_sleep_analysis(
    sessions: Sequence[Mapping[str, Any]],
    tz: ZoneInfo,
) -> SleepAnalysisResult:
    """Compute sleep duration averages, stages, consistency, sleep debt, and worst nights."""
    if not sessions:
        return SleepAnalysisResult(
            avg_duration_min=None,
            avg_efficiency=None,
            avg_deep_min=None,
            avg_light_min=None,
            avg_rem_min=None,
            avg_awake_min=None,
            bedtime_consistency_sd_min=None,
            sleep_debt_min=0,
            worst_nights=[],
        )

    durations: list[int] = []
    efficiencies: list[int] = []
    deeps: list[int] = []
    lights: list[int] = []
    rems: list[int] = []
    awakes: list[int] = []
    bedtime_minutes: list[float] = []

    for s in sessions:
        dur = s.get("duration_min")
        if dur is not None:
            durations.append(int(dur))
        eff = s.get("efficiency")
        if eff is not None:
            efficiencies.append(int(eff))
        dp = s.get("minutes_deep")
        if dp is not None:
            deeps.append(int(dp))
        lt = s.get("minutes_light")
        if lt is not None:
            lights.append(int(lt))
        rm = s.get("minutes_rem")
        if rm is not None:
            rems.append(int(rm))
        aw = s.get("minutes_awake")
        if aw is not None:
            awakes.append(int(aw))

        start_ts = s.get("start_ts")
        if isinstance(start_ts, dt.datetime):
            bedtime_minutes.append(calculate_bedtime_minutes(start_ts, tz))

    avg_dur = round(statistics.mean(durations), 1) if durations else None
    avg_eff = round(statistics.mean(efficiencies), 1) if efficiencies else None
    avg_dp = round(statistics.mean(deeps), 1) if deeps else None
    avg_lt = round(statistics.mean(lights), 1) if lights else None
    avg_rm = round(statistics.mean(rems), 1) if rems else None
    avg_aw = round(statistics.mean(awakes), 1) if awakes else None

    consistency = round(statistics.stdev(bedtime_minutes), 1) if len(bedtime_minutes) >= 2 else None

    sleep_debt = sum(max(0, 480 - d) for d in durations)

    # 3 worst nights by duration
    sorted_nights = sorted(
        sessions, key=lambda s: (s.get("duration_min") or 99999, -(s.get("sleep_score") or 0))
    )
    worst = [
        {
            "local_date": s.get("local_date"),
            "duration_min": s.get("duration_min"),
            "efficiency": s.get("efficiency"),
            "sleep_score": s.get("sleep_score"),
        }
        for s in sorted_nights[:3]
    ]

    return SleepAnalysisResult(
        avg_duration_min=avg_dur,
        avg_efficiency=avg_eff,
        avg_deep_min=avg_dp,
        avg_light_min=avg_lt,
        avg_rem_min=avg_rm,
        avg_awake_min=avg_aw,
        bedtime_consistency_sd_min=consistency,
        sleep_debt_min=sleep_debt,
        worst_nights=worst,
    )
