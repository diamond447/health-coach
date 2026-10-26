import datetime as dt
from typing import Any

import httpx
import pytest
from mcp import Client
from sqlalchemy import Engine, text

from health_coach.ingest import openfoodfacts
from health_coach.mcp_server.common import today
from health_coach.mcp_server.server import create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def call(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    async with Client(create_server()) as client:
        result = await client.call_tool(tool, args or {})
    assert not result.is_error, result.content
    content: dict[str, Any] | None = result.structured_content
    assert content is not None
    return content


async def call_error(tool: str, args: dict[str, Any]) -> str:
    async with Client(create_server()) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error
    return " ".join(getattr(c, "text", "") for c in result.content)


async def test_search_food_personal_and_off(owner: Engine) -> None:
    # Seed personal food
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO foods (name, brand, barcode, kcal_100g, protein_100g, carbs_100g, "
                "fat_100g, fiber_100g, source) VALUES "
                "('Greek Yogurt 0%', 'Milko', '5201234567890', 57, 10.3, 4.0, 0.0, 0.0, 'custom')"
            )
        )

    # 1. Search by name finds personal food
    res = await call("search_food", {"query": "Greek Yogurt"})
    assert len(res["rows"]) >= 1
    row = res["rows"][0]
    assert row[2] == "Greek Yogurt 0%"
    assert row[4] == "5201234567890"

    # 2. Search by barcode with mocked OFF
    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v2/product/7310865004703.json" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "product": {
                        "code": "7310865004703",
                        "product_name": "Oat Milk Barista",
                        "brands": "Oatly",
                        "nutriments": {
                            "energy-kcal_100g": 59,
                            "proteins_100g": 1.1,
                            "carbohydrates_100g": 6.7,
                            "fat_100g": 3.0,
                            "fiber_100g": 0.8,
                            "sodium_100g": 0.1,
                            "vitamin-d_100g": 0.0000011,
                        },
                        "serving_quantity": 250,
                    },
                },
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    openfoodfacts.set_client(client)
    try:
        res_off = await call("search_food", {"barcode": "7310865004703"})
        assert len(res_off["rows"]) == 1
        off_row = res_off["rows"][0]
        assert off_row[0] is None  # id is null for OFF
        assert off_row[1] == "openfoodfacts"
        assert off_row[2] == "Oat Milk Barista"
        assert off_row[3] == "Oatly"
        assert off_row[5] == 59
        assert off_row[6] == 1.1
        assert off_row[11] == {"sodium": 0.1, "vitamin_d": 0.0000011}
    finally:
        openfoodfacts.set_client(None)


async def test_search_food_off_failure_returns_warning(owner: Engine) -> None:
    # Seed personal food
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO foods (name, kcal_100g, protein_100g, carbs_100g, fat_100g, source) "
                "VALUES ('Oats', 370, 13, 60, 7, 'custom')"
            )
        )

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.Client(transport=httpx.MockTransport(failing_handler))
    openfoodfacts.set_client(client)
    try:
        # Should return personal match + warning, never raise
        res = await call("search_food", {"query": "Oats"})
        assert len(res["rows"]) >= 1
        assert res["rows"][0][2] == "Oats"
        assert "warnings" in res
        assert any("Open Food Facts" in w for w in res["warnings"])
    finally:
        openfoodfacts.set_client(None)


async def test_search_food_validation() -> None:
    msg = await call_error("search_food", {})
    assert "either query or barcode" in msg


async def test_save_food_happy_path_and_validation(owner: Engine) -> None:
    res = await call(
        "save_food",
        {
            "name": "Chicken Breast",
            "kcal_100g": 165.0,
            "protein_100g": 31.0,
            "carbs_100g": 0.0,
            "fat_100g": 3.6,
            "brand": "Butcher",
            "default_serving_g": 150.0,
            "micros_100g": {"iron": 0.001, "zinc": 0.001},
        },
    )
    food_id = res["id"]
    assert isinstance(food_id, int)

    # Verify saved in DB
    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT name, kcal_100g, protein_100g, micros_100g FROM foods WHERE id = :id"),
            {"id": food_id},
        ).one()
    assert row.name == "Chicken Breast"
    assert float(row.kcal_100g) == 165.0
    assert row.micros_100g == {"iron": 0.001, "zinc": 0.001}

    # Validation: kcal > 950
    msg = await call_error(
        "save_food",
        {
            "name": "Invalid Oil",
            "kcal_100g": 999.0,
            "protein_100g": 0.0,
            "carbs_100g": 0.0,
            "fat_100g": 100.0,
        },
    )
    assert "950" in msg

    # Validation: macros sum > 100
    msg2 = await call_error(
        "save_food",
        {
            "name": "Magic Powder",
            "kcal_100g": 400.0,
            "protein_100g": 50.0,
            "carbs_100g": 40.0,
            "fat_100g": 20.0,
        },
    )
    assert "exceeds 100 g" in msg2


async def test_log_meal_with_food_id_and_without(owner: Engine) -> None:
    # Save a food first
    food_res = await call(
        "save_food",
        {
            "name": "Basmati Rice",
            "kcal_100g": 130.0,
            "protein_100g": 2.7,
            "carbs_100g": 28.0,
            "fat_100g": 0.3,
            "micros_100g": {"magnesium": 0.05, "vitamin_b6": 0.001},
        },
    )
    food_id = food_res["id"]

    # 1. Log with food_id: macros computed per grams
    res1 = await call(
        "log_meal",
        {
            "meal": "lunch",
            "items": [{"food_id": food_id, "grams": 200.0}],
            "confidence": "exact",
        },
    )
    assert len(res1["entry_ids"]) == 1
    assert res1["daily_totals"] is not None
    assert res1["daily_totals"]["kcal"] == 260
    assert res1["daily_totals"]["carbs_g"] == 56.0
    with owner.connect() as conn:
        entry_row = conn.execute(
            text("SELECT micros FROM nutrition_entries WHERE id = :id"),
            {"id": res1["entry_ids"][0]},
        ).one()
    assert entry_row.micros == {"magnesium": 0.1, "vitamin_b6": 0.002}

    # 2. Log without food_id: requires kcal, protein_g, carbs_g, fat_g; no micros
    res2 = await call(
        "log_meal",
        {
            "meal": "lunch",
            "items": [
                {
                    "description": "Chicken Curry",
                    "grams": 300.0,
                    "kcal": 450.0,
                    "protein_g": 35.0,
                    "carbs_g": 15.0,
                    "fat_g": 20.0,
                }
            ],
            "confidence": "estimated",
        },
    )
    assert len(res2["entry_ids"]) == 1
    assert res2["daily_totals"]["kcal"] == 710  # 260 + 450
    with owner.connect() as conn:
        entry_row2 = conn.execute(
            text("SELECT micros FROM nutrition_entries WHERE id = :id"),
            {"id": res2["entry_ids"][0]},
        ).one()
    assert entry_row2.micros is None

    # 3. Validation: missing macros without food_id
    msg = await call_error(
        "log_meal",
        {
            "meal": "snack",
            "items": [{"description": "Apple", "grams": 150.0}],
        },
    )
    assert "kcal, protein_g, carbs_g and fat_g are required" in msg


async def test_log_meal_repeat_entry_ids(owner: Engine) -> None:
    # Log initial meal
    res1 = await call(
        "log_meal",
        {
            "meal": "breakfast",
            "items": [
                {
                    "description": "Eggs and toast",
                    "grams": 250.0,
                    "kcal": 380.0,
                    "protein_g": 22.0,
                    "carbs_g": 30.0,
                    "fat_g": 18.0,
                }
            ],
        },
    )
    entry_id = res1["entry_ids"][0]

    # Repeat yesterday's breakfast as today's lunch
    tomorrow_ts = dt.datetime.combine(today() + dt.timedelta(days=1), dt.time(13), dt.UTC)
    res2 = await call(
        "log_meal",
        {
            "meal": "lunch",
            "repeat_entry_ids": [entry_id],
            "ts": tomorrow_ts.isoformat(),
        },
    )
    assert len(res2["entry_ids"]) == 1
    new_entry_id = res2["entry_ids"][0]
    assert new_entry_id != entry_id

    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT description, kcal, meal FROM nutrition_entries WHERE id = :id"),
            {"id": new_entry_id},
        ).one()
    assert row.description == "Eggs and toast"
    assert row.kcal == 380.0
    assert row.meal == "lunch"


async def test_update_nutrition_entry_macro_scaling(owner: Engine) -> None:
    food = await call(
        "save_food",
        {
            "name": "Peanut Butter",
            "kcal_100g": 600.0,
            "protein_100g": 25.0,
            "carbs_100g": 20.0,
            "fat_100g": 50.0,
            "micros_100g": {"potassium": 0.6, "vitamin_e": 0.008},
        },
    )
    # Log 50 g (half)
    meal = await call(
        "log_meal",
        {
            "meal": "snack",
            "items": [{"food_id": food["id"], "grams": 50.0}],
        },
    )
    entry_id = meal["entry_ids"][0]
    with owner.connect() as conn:
        e1 = conn.execute(
            text("SELECT micros FROM nutrition_entries WHERE id = :id"),
            {"id": entry_id},
        ).one()
    assert e1.micros == {"potassium": 0.3, "vitamin_e": 0.004}

    # Update grams to 100 g -> should rescale to 100g macros and micros
    updated = await call("update_nutrition_entry", {"entry_id": entry_id, "grams": 100.0})
    assert updated["grams"] == 100.0
    assert updated["kcal"] == 600.0
    assert updated["protein_g"] == 25.0
    assert updated["fat_g"] == 50.0
    assert updated["micros"] == {"potassium": 0.6, "vitamin_e": 0.008}

    # Non-existent entry
    msg = await call_error("update_nutrition_entry", {"entry_id": 999999, "grams": 50.0})
    assert "not found" in msg


async def test_delete_nutrition_entry_soft_delete(owner: Engine) -> None:
    meal = await call(
        "log_meal",
        {
            "meal": "snack",
            "items": [
                {
                    "description": "Cookie",
                    "kcal": 200.0,
                    "protein_g": 2.0,
                    "carbs_g": 30.0,
                    "fat_g": 8.0,
                }
            ],
        },
    )
    entry_id = meal["entry_ids"][0]

    # Delete
    del_res = await call("delete_nutrition_entry", {"entry_id": entry_id})
    assert del_res["deleted"] is True

    # Check soft deleted in DB
    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT deleted_at FROM nutrition_entries WHERE id = :id"), {"id": entry_id}
        ).one()
    assert row.deleted_at is not None

    # Deleting again raises not found
    msg = await call_error("delete_nutrition_entry", {"entry_id": entry_id})
    assert "not found" in msg


async def test_log_body_metric(owner: Engine) -> None:
    res = await call("log_body_metric", {"weight_kg": 80.5, "waist_cm": 82.0})
    assert isinstance(res["id"], int)
    assert res["weight_kg"] == 80.5
    assert res["avg_7d_kg"] == 80.5

    # Validation: weight outside range
    msg = await call_error("log_body_metric", {"weight_kg": 25.0})
    assert "between 30 and 250" in msg or "greater than or equal to 30" in msg

    # Validation: empty call
    msg2 = await call_error("log_body_metric", {})
    assert "at least one of" in msg2


async def test_log_checkin(owner: Engine) -> None:
    today_date = today()
    res = await call(
        "log_checkin",
        {
            "date": today_date.isoformat(),
            "energy": 4,
            "soreness": 2,
            "stress": 3,
            "motivation": 5,
            "notes": "Feeling great",
        },
    )
    assert res["energy"] == 4
    assert res["soreness"] == 2
    assert res["notes"] == "Feeling great"

    # Upsert: only update soreness
    res_up = await call(
        "log_checkin",
        {
            "date": today_date.isoformat(),
            "soreness": 4,
        },
    )
    assert res_up["energy"] == 4  # preserved
    assert res_up["soreness"] == 4  # updated
    assert res_up["notes"] == "Feeling great"  # preserved

    # Validation: rating out of bounds
    msg = await call_error("log_checkin", {"energy": 6})
    assert "between 1 and 5" in msg or "less than or equal to 5" in msg


async def test_log_exercise_session(owner: Engine) -> None:
    now = dt.datetime.now(dt.UTC)
    res = await call(
        "log_exercise_session",
        {
            "activity_type": "bjj",
            "start_ts": now.isoformat(),
            "duration_min": 75,
            "rpe": 8,
            "avg_hr": 145,
            "notes": "Hard sparring rounds",
        },
    )
    assert isinstance(res["id"], int)

    with owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT activity_type, duration_min, rpe, avg_hr, source "
                "FROM exercise_sessions WHERE id = :id"
            ),
            {"id": res["id"]},
        ).one()
    assert row.activity_type == "bjj"
    assert row.duration_min == 75
    assert row.source == "manual"
    assert row.rpe == 8
    assert row.avg_hr == 145

    # Validation: empty activity
    msg = await call_error(
        "log_exercise_session",
        {
            "activity_type": "",
            "start_ts": now.isoformat(),
            "duration_min": 60,
        },
    )
    assert "activity_type cannot be empty" in msg
