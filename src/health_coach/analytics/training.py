"""Pure functions for training load, exercise progression, PRs, and least-squares trend."""

import contextlib
import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def least_squares_slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Least-squares slope in units/week from (day_offset, metric) points.

    Returns slope * 7.0 (change per week), rounded to 2 decimal places.
    Returns None if fewer than 2 points or all x-coordinates are identical.
    """
    n = len(points)
    if n < 2:
        return None

    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None

    slope_per_day = (n * sum_xy - sum_x * sum_y) / denom
    return round(slope_per_day * 7.0, 2)


@dataclass(frozen=True)
class SessionProgress:
    session_id: int
    local_date: dt.date
    top_set_weight_kg: float | None
    top_set_reps: float | None
    e1rm_kg: float | None
    volume_kg: float


def compute_session_progress(
    session_id: int,
    local_date: dt.date,
    sets: Sequence[Mapping[str, Any]],
    session_e1rm: float | None = None,
) -> SessionProgress:
    """Compute top set, e1RM, and volume for one strength session."""
    working_sets = [
        s
        for s in sets
        if not s.get("is_warmup", False)
        and s.get("weight_kg") is not None
        and s.get("reps") is not None
        and float(s["reps"]) > 0
    ]

    top_weight: float | None = None
    top_reps: float | None = None
    if working_sets:
        sorted_sets = sorted(
            working_sets,
            key=lambda s: (float(s["weight_kg"]), float(s["reps"])),
            reverse=True,
        )
        top = sorted_sets[0]
        top_weight = float(top["weight_kg"])
        top_reps = float(top["reps"])

    volume = round(
        sum(float(s["weight_kg"]) * float(s["reps"]) for s in working_sets),
        1,
    )

    e1rm = session_e1rm
    if e1rm is None and working_sets:
        # Fallback Epley calculation
        best_epley: float | None = None
        for s in working_sets:
            reps = float(s["reps"])
            wt = float(s["weight_kg"])
            rir = s.get("rir")
            if 1 <= reps <= 12 and (rir is None or float(rir) <= 3):
                epley = wt if reps == 1 else wt * (1.0 + reps / 30.0)
                if best_epley is None or epley > best_epley:
                    best_epley = epley
        if best_epley is not None:
            e1rm = round(best_epley, 1)

    return SessionProgress(
        session_id=session_id,
        local_date=local_date,
        top_set_weight_kg=top_weight,
        top_set_reps=top_reps,
        e1rm_kg=e1rm,
        volume_kg=volume,
    )


def sum_hr_zones(sessions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Sum hr_zone_minutes across sessions.

    Keyed by zone identifier (str), sorted numerically if digits.
    """
    totals: dict[str, int] = defaultdict(int)
    for s in sessions:
        zones = s.get("hr_zone_minutes")
        if isinstance(zones, Mapping):
            for k, v in zones.items():
                if v is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        totals[str(k)] += round(float(v))

    def zone_sort_key(z: str) -> tuple[int, str]:
        return (0, f"{int(z):04d}") if z.isdigit() else (1, z)

    return {k: totals[k] for k in sorted(totals, key=zone_sort_key)}
