"""Pure functions and column whitelist for comparing v_daily periods."""

from collections.abc import Mapping, Sequence
from typing import Any

V_DAILY_NUMERIC_COLUMNS = frozenset(
    {
        "steps",
        "distance_km",
        "active_minutes",
        "active_zone_minutes",
        "calories_out",
        "floors",
        "resting_hr",
        "hrv_rmssd_ms",
        "spo2_avg",
        "breathing_rate",
        "skin_temp_delta",
        "sleep_min",
        "sleep_efficiency",
        "sleep_score",
        "sleep_deep_min",
        "sleep_rem_min",
        "kcal_in",
        "protein_g",
        "carbs_g",
        "fat_g",
        "nutrition_entries",
        "target_kcal",
        "target_protein_g",
        "weight_kg",
        "body_fat_pct",
        "energy",
        "soreness",
        "stress",
        "motivation",
        "strength_sessions",
        "hard_sets",
        "tonnage_kg",
        "exercise_min",
    }
)


def compute_metric_change(
    mean_a: float | None,
    mean_b: float | None,
) -> tuple[float | None, float | None]:
    """Compute absolute change and percentage change between period A and period B.

    Returns (absolute_change, percent_change).
    percent_change is (mean_b - mean_a) / mean_a * 100 (or None if mean_a is 0 or missing).
    """
    if mean_a is None or mean_b is None:
        return None, None

    abs_change = round(mean_b - mean_a, 2)
    pct_change = round((mean_b - mean_a) / abs(mean_a) * 100.0, 1) if mean_a != 0 else None
    return abs_change, pct_change


def compare_period_metrics(
    metrics: Sequence[str],
    stats_a: Mapping[str, tuple[float | None, int]],
    stats_b: Mapping[str, tuple[float | None, int]],
) -> list[dict[str, Any]]:
    """Compare a list of metrics across two periods.

    Each stats dict maps metric -> (mean_value, days_with_data).
    """
    rows = []
    for m in metrics:
        mean_a, days_a = stats_a.get(m, (None, 0))
        mean_b, days_b = stats_b.get(m, (None, 0))

        m_a = round(mean_a, 2) if mean_a is not None else None
        m_b = round(mean_b, 2) if mean_b is not None else None

        abs_diff, pct_diff = compute_metric_change(m_a, m_b)

        rows.append(
            {
                "metric": m,
                "mean_a": m_a,
                "mean_b": m_b,
                "absolute_change": abs_diff,
                "percent_change": pct_diff,
                "days_a": days_a,
                "days_b": days_b,
            }
        )
    return rows
