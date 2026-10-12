"""Pure functions for nutrition summary, meal distribution, and completeness."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NutritionAverages:
    kcal_avg: float | None
    protein_avg_g: float | None
    carbs_avg_g: float | None
    fat_avg_g: float | None
    fiber_avg_g: float | None
    protein_g_per_kg_avg: float | None


def calculate_nutrition_averages(daily_rows: Sequence[Mapping[str, Any]]) -> NutritionAverages:
    """Calculate average intake and protein per kg across days that have entries."""
    if not daily_rows:
        return NutritionAverages(None, None, None, None, None, None)

    kcals = [float(r["kcal"]) for r in daily_rows if r.get("kcal") is not None]
    proteins = [float(r["protein_g"]) for r in daily_rows if r.get("protein_g") is not None]
    carbs = [float(r["carbs_g"]) for r in daily_rows if r.get("carbs_g") is not None]
    fats = [float(r["fat_g"]) for r in daily_rows if r.get("fat_g") is not None]
    fibers = [float(r["fiber_g"]) for r in daily_rows if r.get("fiber_g") is not None]
    prot_per_kg = [
        float(r["protein_g_per_kg"]) for r in daily_rows if r.get("protein_g_per_kg") is not None
    ]

    return NutritionAverages(
        kcal_avg=round(sum(kcals) / len(kcals)) if kcals else None,
        protein_avg_g=round(sum(proteins) / len(proteins), 1) if proteins else None,
        carbs_avg_g=round(sum(carbs) / len(carbs), 1) if carbs else None,
        fat_avg_g=round(sum(fats) / len(fats), 1) if fats else None,
        fiber_avg_g=round(sum(fibers) / len(fibers), 1) if fibers else None,
        protein_g_per_kg_avg=(
            round(sum(prot_per_kg) / len(prot_per_kg), 2) if prot_per_kg else None
        ),
    )


def calculate_meal_distribution(meal_kcals: Mapping[str, float]) -> dict[str, float]:
    """Calculate percentage of kcal per meal."""
    total = sum(meal_kcals.values())
    if total <= 0:
        return {m: 0.0 for m in meal_kcals}
    return {m: round(kcal / total * 100.0, 1) for m, kcal in meal_kcals.items()}


def calculate_logging_completeness(days_logged: int, days_in_range: int) -> dict[str, Any]:
    """Calculate logging completeness."""
    ratio = round(days_logged / days_in_range, 2) if days_in_range > 0 else 0.0
    pct = round(days_logged / days_in_range * 100.0, 1) if days_in_range > 0 else 0.0
    return {
        "days_logged": days_logged,
        "days_in_range": days_in_range,
        "ratio": ratio,
        "percentage": pct,
    }
