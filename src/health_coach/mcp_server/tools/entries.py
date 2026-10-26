"""Group 4 (logging): food library, meals, body metrics, check-ins, manual sessions."""

import datetime as dt
import json
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import text

from health_coach.config import get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.db.models import Confidence, Meal
from health_coach.ingest.openfoodfacts import OpenFoodFactsClient
from health_coach.mcp_server.common import (
    DATA_NOTE,
    DESTRUCTIVE,
    READ_EXTERNAL,
    UPSERT,
    WRITE,
    audited,
    jsonable,
    rnd,
    tabular,
    today,
)

FOOD_COLUMNS = [
    "id",
    "source",
    "name",
    "brand",
    "barcode",
    "kcal_100g",
    "protein_100g",
    "carbs_100g",
    "fat_100g",
    "fiber_100g",
    "default_serving_g",
    "micros_100g",
]


class MealItem(BaseModel):
    food_id: int | None = None
    description: str | None = None
    grams: Annotated[float | None, Field(ge=0, description="Weight in grams")] = None
    kcal: Annotated[float | None, Field(ge=0, description="Energy in kcal")] = None
    protein_g: Annotated[float | None, Field(ge=0, description="Protein in grams")] = None
    carbs_g: Annotated[float | None, Field(ge=0, description="Carbohydrates in grams")] = None
    fat_g: Annotated[float | None, Field(ge=0, description="Fat in grams")] = None
    fiber_g: Annotated[float | None, Field(ge=0, description="Fiber in grams")] = None


def search_food(
    query: Annotated[
        str | None,
        Field(description="Food name or query to search in personal library and Open Food Facts"),
    ] = None,
    barcode: Annotated[
        str | None, Field(description="Barcode (EAN/UPC) to look up in library and Open Food Facts")
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=50, description="Maximum number of results to return")
    ] = 10,
) -> dict[str, Any]:
    """Search for foods in the personal library first, then Open Food Facts.

    Returns nutritional values per 100 g. If Open Food Facts is unavailable, returns
    personal matches with a warning.
    """
    if not query and not barcode:
        raise ToolError("either query or barcode must be provided")

    personal_matches: list[dict[str, Any]] = []
    with get_engine(Role.rw).connect() as conn:
        if barcode:
            rows = conn.execute(
                text(
                    f"SELECT {', '.join(FOOD_COLUMNS)} FROM foods "  # noqa: S608
                    "WHERE deleted_at IS NULL AND barcode = :barcode LIMIT :limit"
                ),
                {"barcode": barcode, "limit": limit},
            ).all()
        else:
            rows = conn.execute(
                text(
                    f"SELECT {', '.join(FOOD_COLUMNS)} FROM foods "  # noqa: S608
                    "WHERE deleted_at IS NULL AND name ILIKE :pat LIMIT :limit"
                ),
                {"pat": f"%{query}%", "limit": limit},
            ).all()
        personal_matches = [{k: jsonable(v) for k, v in r._mapping.items()} for r in rows]

    off_matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    remaining = limit - len(personal_matches)

    if remaining > 0:
        off_client = OpenFoodFactsClient()
        try:
            if barcode:
                off_matches = off_client.search_by_barcode(barcode)
            elif query:
                off_matches = off_client.search_by_text(query, limit=remaining)
        except Exception as exc:
            warnings.append(f"Open Food Facts lookup failed: {exc}")

    all_rows = (personal_matches + off_matches)[:limit]
    res = tabular(all_rows, columns=FOOD_COLUMNS)
    res["note"] = DATA_NOTE
    if warnings:
        res["warnings"] = warnings
    return res


def save_food(
    name: Annotated[str, Field(description="Name of the food")],
    kcal_100g: Annotated[float, Field(ge=0, le=950, description="Calories per 100 g (0-950)")],
    protein_100g: Annotated[float, Field(ge=0, le=100, description="Protein in grams per 100 g")],
    carbs_100g: Annotated[
        float, Field(ge=0, le=100, description="Carbohydrates in grams per 100 g")
    ],
    fat_100g: Annotated[float, Field(ge=0, le=100, description="Fat in grams per 100 g")],
    fiber_100g: Annotated[
        float | None, Field(ge=0, le=100, description="Fiber in grams per 100 g")
    ] = None,
    brand: Annotated[str | None, Field(description="Brand or producer")] = None,
    barcode: Annotated[str | None, Field(description="Barcode (EAN/UPC)")] = None,
    default_serving_g: Annotated[
        float | None, Field(gt=0, description="Standard serving size in grams")
    ] = None,
    source: Annotated[
        Literal["custom", "openfoodfacts"],
        Field(description="Source of the food item: custom or openfoodfacts"),
    ] = "custom",
    external_id: Annotated[
        str | None, Field(description="External ID (e.g. Open Food Facts code)")
    ] = None,
    micros_100g: Annotated[
        dict[str, float] | None,
        Field(description="Micros per 100 g in grams (e.g. {'sodium': 0.5, 'vitamin_c': 0.08})"),
    ] = None,
) -> dict[str, Any]:
    """Save a food item to the personal food library."""
    if not name.strip():
        raise ToolError("food name cannot be empty")
    if kcal_100g < 0 or kcal_100g > 950:
        raise ToolError("kcal_100g must be between 0 and 950")
    if protein_100g < 0 or carbs_100g < 0 or fat_100g < 0:
        raise ToolError("macros cannot be negative")
    if protein_100g + carbs_100g + fat_100g > 100:
        raise ToolError(
            f"sum of protein ({protein_100g}g), carbs ({carbs_100g}g) and fat ({fat_100g}g) "
            "exceeds 100 g per 100 g"
        )
    if fiber_100g is not None and fiber_100g < 0:
        raise ToolError("fiber cannot be negative")

    with get_engine(Role.rw).begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO foods (name, brand, barcode, kcal_100g, protein_100g, carbs_100g, "
                "fat_100g, fiber_100g, default_serving_g, source, external_id, micros_100g) "
                "VALUES (:name, :brand, :barcode, :kcal_100g, :protein_100g, :carbs_100g, "
                ":fat_100g, :fiber_100g, :default_serving_g, :source, :external_id, "
                "CAST(:micros_100g AS jsonb)) RETURNING id"
            ),
            {
                "name": name.strip(),
                "brand": brand.strip() if brand else None,
                "barcode": barcode.strip() if barcode else None,
                "kcal_100g": kcal_100g,
                "protein_100g": protein_100g,
                "carbs_100g": carbs_100g,
                "fat_100g": fat_100g,
                "fiber_100g": fiber_100g,
                "default_serving_g": default_serving_g,
                "source": source,
                "external_id": external_id,
                "micros_100g": json.dumps(micros_100g) if micros_100g else None,
            },
        ).one()
    return {"id": row.id}


def _resolve_ts_and_date(ts: dt.datetime | None) -> tuple[dt.datetime, dt.date]:
    tz = get_settings().tz
    if ts is None:
        utc_ts = dt.datetime.now(dt.UTC)
    elif ts.tzinfo is None:
        utc_ts = ts.replace(tzinfo=tz).astimezone(dt.UTC)
    else:
        utc_ts = ts.astimezone(dt.UTC)
    local_date = utc_ts.astimezone(tz).date()
    return utc_ts, local_date


def log_meal(
    meal: Annotated[
        Meal, Field(description="Meal type: breakfast, lunch, dinner, snack, or other")
    ],
    items: Annotated[list[MealItem] | None, Field(description="Items eaten in this meal")] = None,
    repeat_entry_ids: Annotated[
        list[int] | None,
        Field(description="Earlier nutrition entry IDs to repeat into this meal"),
    ] = None,
    ts: Annotated[
        dt.datetime | None, Field(description="Timestamp of the meal (defaults to now)")
    ] = None,
    confidence: Annotated[
        Confidence, Field(description="Confidence: exact, estimated, or photo")
    ] = Confidence.estimated,
) -> dict[str, Any]:
    """Log a meal consisting of food items or repeated entries.

    Returns the inserted entry IDs and the day's running nutrition totals vs targets.
    """
    if not items and not repeat_entry_ids:
        raise ToolError("either items or repeat_entry_ids must be provided")

    meal_val = meal.value if hasattr(meal, "value") else str(meal)
    conf_val = confidence.value if hasattr(confidence, "value") else str(confidence)
    utc_ts, local_date = _resolve_ts_and_date(ts)

    inserted_ids: list[int] = []

    with get_engine(Role.rw).begin() as conn:
        # 1. Process new items
        for item in items or []:
            if item.food_id is not None:
                food = conn.execute(
                    text(
                        "SELECT id, name, kcal_100g, protein_100g, carbs_100g, fat_100g, "
                        "fiber_100g, default_serving_g, micros_100g FROM foods "
                        "WHERE id = :id AND deleted_at IS NULL"
                    ),
                    {"id": item.food_id},
                ).first()
                if food is None:
                    raise ToolError(f"food id {item.food_id} not found")

                grams = item.grams
                if grams is None:
                    if food.default_serving_g is not None:
                        grams = float(food.default_serving_g)
                    else:
                        raise ToolError(
                            f"grams required for food '{food.name}' (id {item.food_id})"
                        )

                ratio = grams / 100.0
                desc = item.description or food.name
                kcal = (
                    item.kcal if item.kcal is not None else round(float(food.kcal_100g) * ratio, 1)
                )
                protein_g = (
                    item.protein_g
                    if item.protein_g is not None
                    else round(float(food.protein_100g) * ratio, 1)
                )
                carbs_g = (
                    item.carbs_g
                    if item.carbs_g is not None
                    else round(float(food.carbs_100g) * ratio, 1)
                )
                fat_g = (
                    item.fat_g if item.fat_g is not None else round(float(food.fat_100g) * ratio, 1)
                )
                fiber_g = (
                    item.fiber_g
                    if item.fiber_g is not None
                    else (
                        round(float(food.fiber_100g) * ratio, 1)
                        if food.fiber_100g is not None
                        else None
                    )
                )
                food_id = food.id
                food_micros = food.micros_100g
                item_micros = (
                    {
                        k: round(float(v) * ratio, 8)
                        for k, v in food_micros.items()
                        if v is not None and float(v) > 0
                    }
                    if food_micros and isinstance(food_micros, dict)
                    else None
                )
            else:
                if not item.description or not item.description.strip():
                    raise ToolError("description required when food_id is not provided")
                if (
                    item.kcal is None
                    or item.protein_g is None
                    or item.carbs_g is None
                    or item.fat_g is None
                ):
                    raise ToolError(
                        "kcal, protein_g, carbs_g and fat_g are required when food_id "
                        "is not provided"
                    )
                desc = item.description.strip()
                grams = item.grams
                kcal = item.kcal
                protein_g = item.protein_g
                carbs_g = item.carbs_g
                fat_g = item.fat_g
                fiber_g = item.fiber_g
                food_id = None
                item_micros = None

            row = conn.execute(
                text(
                    "INSERT INTO nutrition_entries (ts, local_date, meal, food_id, description, "
                    "grams, kcal, protein_g, carbs_g, fat_g, fiber_g, confidence, source, micros) "
                    "VALUES (:ts, :ld, :meal, :food_id, :desc, :grams, :kcal, :prot, :carbs, "
                    ":fat, :fiber, :conf, 'chat', CAST(:micros AS jsonb)) RETURNING id"
                ),
                {
                    "ts": utc_ts,
                    "ld": local_date,
                    "meal": meal_val,
                    "food_id": food_id,
                    "desc": desc,
                    "grams": grams,
                    "kcal": kcal,
                    "prot": protein_g,
                    "carbs": carbs_g,
                    "fat": fat_g,
                    "fiber": fiber_g,
                    "conf": conf_val,
                    "micros": json.dumps(item_micros) if item_micros else None,
                },
            ).one()
            inserted_ids.append(row.id)

        # 2. Process repeat entries
        if repeat_entry_ids:
            repeats = conn.execute(
                text(
                    "SELECT id, food_id, description, grams, kcal, protein_g, carbs_g, "
                    "fat_g, fiber_g, micros FROM nutrition_entries "
                    "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                ),
                {"ids": repeat_entry_ids},
            ).all()
            found_by_id = {r.id: r for r in repeats}
            for rep_id in repeat_entry_ids:
                if rep_id not in found_by_id:
                    raise ToolError(f"nutrition entry {rep_id} not found")
                orig = found_by_id[rep_id]
                row = conn.execute(
                    text(
                        "INSERT INTO nutrition_entries (ts, local_date, meal, food_id, "
                        "description, grams, kcal, protein_g, carbs_g, fat_g, fiber_g, "
                        "confidence, source, micros) "
                        "VALUES (:ts, :ld, :meal, :food_id, :desc, :grams, :kcal, :prot, "
                        ":carbs, :fat, :fiber, :conf, 'chat', CAST(:micros AS jsonb)) RETURNING id"
                    ),
                    {
                        "ts": utc_ts,
                        "ld": local_date,
                        "meal": meal_val,
                        "food_id": orig.food_id,
                        "desc": orig.description,
                        "grams": orig.grams,
                        "kcal": orig.kcal,
                        "prot": orig.protein_g,
                        "carbs": orig.carbs_g,
                        "fat": orig.fat_g,
                        "fiber": orig.fiber_g,
                        "conf": conf_val,
                        "micros": json.dumps(orig.micros) if orig.micros else None,
                    },
                ).one()
                inserted_ids.append(row.id)

        daily_row = conn.execute(
            text("SELECT * FROM v_nutrition_daily WHERE local_date = :ld"), {"ld": local_date}
        ).first()

    return {
        "entry_ids": inserted_ids,
        "daily_totals": {k: jsonable(v) for k, v in daily_row._mapping.items()}
        if daily_row
        else None,
    }


def update_nutrition_entry(
    entry_id: Annotated[int, Field(description="ID of the nutrition entry to update")],
    grams: Annotated[
        float | None,
        Field(ge=0, description="New serving weight in grams; rescales linked food macros"),
    ] = None,
    kcal: Annotated[float | None, Field(ge=0, description="New kcal amount")] = None,
    protein_g: Annotated[float | None, Field(ge=0, description="New protein in grams")] = None,
    carbs_g: Annotated[float | None, Field(ge=0, description="New carbohydrates in grams")] = None,
    fat_g: Annotated[float | None, Field(ge=0, description="New fat in grams")] = None,
    fiber_g: Annotated[float | None, Field(ge=0, description="New fiber in grams")] = None,
    meal: Annotated[Meal | None, Field(description="New meal type")] = None,
    description: Annotated[str | None, Field(description="New description")] = None,
    ts: Annotated[dt.datetime | None, Field(description="New timestamp")] = None,
) -> dict[str, Any]:
    """Update a logged nutrition entry.

    Changing grams on an entry linked to a food rescales its macros automatically.
    """
    with get_engine(Role.rw).begin() as conn:
        existing = conn.execute(
            text(
                "SELECT id, ts, local_date, meal, food_id, description, grams, kcal, "
                "protein_g, carbs_g, fat_g, fiber_g, micros FROM nutrition_entries "
                "WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": entry_id},
        ).first()
        if existing is None:
            raise ToolError(f"nutrition entry {entry_id} not found")

        # Rescale if food-linked and grams changed
        target_kcal = kcal
        target_protein = protein_g
        target_carbs = carbs_g
        target_fat = fat_g
        target_fiber = fiber_g
        target_micros = existing.micros

        if grams is not None and existing.food_id is not None:
            food = conn.execute(
                text(
                    "SELECT kcal_100g, protein_100g, carbs_100g, fat_100g, fiber_100g, micros_100g "
                    "FROM foods WHERE id = :id"
                ),
                {"id": existing.food_id},
            ).first()
            if food is not None:
                ratio = grams / 100.0
                if target_kcal is None:
                    target_kcal = round(float(food.kcal_100g) * ratio, 1)
                if target_protein is None:
                    target_protein = round(float(food.protein_100g) * ratio, 1)
                if target_carbs is None:
                    target_carbs = round(float(food.carbs_100g) * ratio, 1)
                if target_fat is None:
                    target_fat = round(float(food.fat_100g) * ratio, 1)
                if target_fiber is None and food.fiber_100g is not None:
                    target_fiber = round(float(food.fiber_100g) * ratio, 1)
                if food.micros_100g and isinstance(food.micros_100g, dict):
                    target_micros = {
                        k: round(float(v) * ratio, 8)
                        for k, v in food.micros_100g.items()
                        if v is not None and float(v) > 0
                    }
                else:
                    target_micros = None

        if ts is not None:
            utc_ts, local_date = _resolve_ts_and_date(ts)
        else:
            utc_ts = existing.ts
            local_date = existing.local_date

        meal_val = (
            meal.value
            if meal is not None and hasattr(meal, "value")
            else (str(meal) if meal is not None else None)
        )

        updated = conn.execute(
            text(
                "UPDATE nutrition_entries SET "
                "grams = COALESCE(:grams, grams), "
                "kcal = COALESCE(:kcal, kcal), "
                "protein_g = COALESCE(:prot, protein_g), "
                "carbs_g = COALESCE(:carbs, carbs_g), "
                "fat_g = COALESCE(:fat, fat_g), "
                "fiber_g = COALESCE(:fiber, fiber_g), "
                "meal = COALESCE(:meal, meal), "
                "description = COALESCE(:desc, description), "
                "micros = CAST(:micros AS jsonb), "
                "ts = :ts, "
                "local_date = :ld, "
                "updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL "
                "RETURNING id, ts, local_date, meal, food_id, description, grams, kcal, "
                "protein_g, carbs_g, fat_g, fiber_g, confidence, source, micros"
            ),
            {
                "id": entry_id,
                "grams": grams,
                "kcal": target_kcal,
                "prot": target_protein,
                "carbs": target_carbs,
                "fat": target_fat,
                "fiber": target_fiber,
                "meal": meal_val,
                "desc": description.strip() if description is not None else None,
                "micros": json.dumps(target_micros) if target_micros else None,
                "ts": utc_ts,
                "ld": local_date,
            },
        ).one()

    return {k: jsonable(v) for k, v in updated._mapping.items()}


def delete_nutrition_entry(
    entry_id: Annotated[int, Field(description="ID of the nutrition entry to delete")],
) -> dict[str, Any]:
    """Soft delete a nutrition entry."""
    with get_engine(Role.rw).begin() as conn:
        res = conn.execute(
            text(
                "UPDATE nutrition_entries SET deleted_at = now(), updated_at = now() "
                "WHERE id = :id AND deleted_at IS NULL RETURNING id"
            ),
            {"id": entry_id},
        ).first()
        if res is None:
            raise ToolError(f"nutrition entry {entry_id} not found")
    return {"deleted": True, "id": entry_id}


def log_body_metric(
    weight_kg: Annotated[
        float | None, Field(ge=30, le=250, description="Body weight in kg (30-250)")
    ] = None,
    body_fat_pct: Annotated[
        float | None, Field(ge=1, le=70, description="Body fat percentage (1-70)")
    ] = None,
    waist_cm: Annotated[
        float | None, Field(ge=40, le=200, description="Waist circumference in cm (40-200)")
    ] = None,
    ts: Annotated[
        dt.datetime | None, Field(description="Timestamp of the measurement (defaults to now)")
    ] = None,
) -> dict[str, Any]:
    """Log body weight, body fat %, or waist circumference.

    Returns the entry ID and the updated 7-day average weight.
    """
    if weight_kg is None and body_fat_pct is None and waist_cm is None:
        raise ToolError("at least one of weight_kg, body_fat_pct, or waist_cm must be provided")
    if weight_kg is not None and not (30 <= weight_kg <= 250):
        raise ToolError("weight_kg must be between 30 and 250 kg")
    if body_fat_pct is not None and not (1 <= body_fat_pct <= 70):
        raise ToolError("body_fat_pct must be between 1 and 70%")
    if waist_cm is not None and not (40 <= waist_cm <= 200):
        raise ToolError("waist_cm must be between 40 and 200 cm")

    utc_ts, local_date = _resolve_ts_and_date(ts)

    with get_engine(Role.rw).begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO body_metrics (ts, local_date, weight_kg, body_fat_pct, "
                "waist_cm, source) "
                "VALUES (:ts, :ld, :weight, :bf, :waist, 'chat') RETURNING id"
            ),
            {
                "ts": utc_ts,
                "ld": local_date,
                "weight": weight_kg,
                "bf": body_fat_pct,
                "waist": waist_cm,
            },
        ).one()

        trend = conn.execute(
            text(
                "SELECT avg_7d_kg FROM v_weight_trend "
                "WHERE local_date <= :ld ORDER BY local_date DESC LIMIT 1"
            ),
            {"ld": local_date},
        ).first()

    return {
        "id": row.id,
        "local_date": jsonable(local_date),
        "weight_kg": weight_kg,
        "avg_7d_kg": rnd(trend.avg_7d_kg, 0.1) if trend else None,
    }


def log_checkin(
    date: Annotated[
        dt.date | None,
        Field(description="Check-in date (YYYY-MM-DD, local date; defaults to today)"),
    ] = None,
    energy: Annotated[int | None, Field(ge=1, le=5, description="Energy rating 1-5")] = None,
    soreness: Annotated[int | None, Field(ge=1, le=5, description="Soreness rating 1-5")] = None,
    stress: Annotated[int | None, Field(ge=1, le=5, description="Stress rating 1-5")] = None,
    motivation: Annotated[
        int | None, Field(ge=1, le=5, description="Motivation rating 1-5")
    ] = None,
    notes: Annotated[str | None, Field(description="Subjective comments or observations")] = None,
) -> dict[str, Any]:
    """Log or update a subjective daily check-in (energy, soreness, stress, motivation 1-5)."""
    if all(v is None for v in (energy, soreness, stress, motivation, notes)):
        raise ToolError("at least one check-in field must be provided")

    for name, val in [
        ("energy", energy),
        ("soreness", soreness),
        ("stress", stress),
        ("motivation", motivation),
    ]:
        if val is not None and not (1 <= val <= 5):
            raise ToolError(f"{name} must be between 1 and 5")

    d = date or today()

    with get_engine(Role.rw).begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO checkins (local_date, energy, soreness, stress, motivation, "
                "notes, source) "
                "VALUES (:ld, :energy, :soreness, :stress, :motivation, :notes, 'chat') "
                "ON CONFLICT (local_date) DO UPDATE SET "
                "energy = COALESCE(EXCLUDED.energy, checkins.energy), "
                "soreness = COALESCE(EXCLUDED.soreness, checkins.soreness), "
                "stress = COALESCE(EXCLUDED.stress, checkins.stress), "
                "motivation = COALESCE(EXCLUDED.motivation, checkins.motivation), "
                "notes = COALESCE(EXCLUDED.notes, checkins.notes), "
                "updated_at = now() "
                "RETURNING local_date, energy, soreness, stress, motivation, notes"
            ),
            {
                "ld": d,
                "energy": energy,
                "soreness": soreness,
                "stress": stress,
                "motivation": motivation,
                "notes": notes,
            },
        ).one()

    return {k: jsonable(v) for k, v in row._mapping.items()}


def log_exercise_session(
    activity_type: Annotated[
        str, Field(description="Activity type: e.g. bjj, climbing, cycling, gym, running")
    ],
    start_ts: Annotated[dt.datetime, Field(description="Session start timestamp")],
    duration_min: Annotated[int, Field(ge=1, le=1440, description="Duration in minutes")],
    notes: Annotated[str | None, Field(description="Optional session notes")] = None,
    rpe: Annotated[int | None, Field(ge=1, le=10, description="RPE rating (1-10)")] = None,
    avg_hr: Annotated[
        int | None, Field(ge=30, le=250, description="Average heart rate (bpm)")
    ] = None,
) -> dict[str, Any]:
    """Log an exercise session manually (e.g. for sessions when the watch was not worn)."""
    if not activity_type.strip():
        raise ToolError("activity_type cannot be empty")
    if duration_min <= 0:
        raise ToolError("duration_min must be positive")
    if rpe is not None and not (1 <= rpe <= 10):
        raise ToolError("rpe must be between 1 and 10")
    if avg_hr is not None and not (30 <= avg_hr <= 250):
        raise ToolError("avg_hr must be between 30 and 250 bpm")

    tz = get_settings().tz
    if start_ts.tzinfo is None:
        utc_start = start_ts.replace(tzinfo=tz).astimezone(dt.UTC)
    else:
        utc_start = start_ts.astimezone(dt.UTC)

    end_ts = utc_start + dt.timedelta(minutes=duration_min)
    local_date = utc_start.astimezone(tz).date()

    with get_engine(Role.rw).begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO exercise_sessions (activity_type, start_ts, end_ts, local_date, "
                "duration_min, notes, rpe, avg_hr, source) "
                "VALUES (:act, :start, :end, :ld, :dur, :notes, :rpe, :hr, 'manual') RETURNING id"
            ),
            {
                "act": activity_type.strip(),
                "start": utc_start,
                "end": end_ts,
                "ld": local_date,
                "dur": duration_min,
                "notes": notes.strip() if notes else None,
                "rpe": rpe,
                "hr": avg_hr,
            },
        ).one()

    return {"id": row.id}


def register(server: MCPServer) -> None:
    server.tool(annotations=READ_EXTERNAL)(audited(search_food))
    server.tool(annotations=WRITE)(audited(save_food))
    server.tool(annotations=WRITE)(audited(log_meal))
    server.tool(annotations=UPSERT)(audited(update_nutrition_entry))
    server.tool(annotations=DESTRUCTIVE)(audited(delete_nutrition_entry))
    server.tool(annotations=WRITE)(audited(log_body_metric))
    server.tool(annotations=UPSERT)(audited(log_checkin))
    server.tool(annotations=WRITE)(audited(log_exercise_session))
