"""Tests for MCP journal and sleep settings tools."""

import datetime as dt
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import Engine, text

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


async def test_log_journal_and_upsert(owner: Engine) -> None:
    yesterday = today() - dt.timedelta(days=1)

    # 1. Log with date=None defaults to yesterday
    res = await call(
        "log_journal",
        {
            "entries": [
                {"behavior": "alcohol", "amount": 2.0, "note": "red wine"},
                {"behavior": "sauna", "note": "20 min"},
            ]
        },
    )
    assert res["local_date"] == yesterday.isoformat()
    assert len(res["entries"]) == 2
    entries_map = {e["behavior"]: e for e in res["entries"]}
    assert entries_map["alcohol"]["amount"] == 2.0
    assert entries_map["alcohol"]["note"] == "red wine"
    assert entries_map["sauna"]["amount"] is None
    assert entries_map["sauna"]["note"] == "20 min"

    # 2. Upsert same date and behavior: update amount and note
    res2 = await call(
        "log_journal",
        {
            "date": yesterday.isoformat(),
            "entries": [
                {"behavior": "alcohol", "amount": 3.0, "note": "updated to 3 drinks"},
            ],
        },
    )
    assert len(res2["entries"]) == 2  # alcohol and sauna
    alc = next(e for e in res2["entries"] if e["behavior"] == "alcohol")
    assert alc["amount"] == 3.0
    assert alc["note"] == "updated to 3 drinks"


async def test_log_journal_validation() -> None:
    # Invalid behavior name: uppercase / spaces
    err1 = await call_error(
        "log_journal",
        {"entries": [{"behavior": "Bad Behavior"}]},
    )
    assert "invalid behavior key" in err1.lower()

    # Empty entries
    err2 = await call_error("log_journal", {"entries": []})
    assert "entries" in err2.lower()

    # Negative amount
    err3 = await call_error(
        "log_journal",
        {"entries": [{"behavior": "alcohol", "amount": -1.0}]},
    )
    assert "negative" in err3.lower() or "greater than or equal to 0" in err3.lower()


async def test_get_and_delete_journal(owner: Engine) -> None:
    d1 = today() - dt.timedelta(days=3)
    d2 = today() - dt.timedelta(days=2)

    await call(
        "log_journal",
        {
            "date": d1.isoformat(),
            "entries": [{"behavior": "stretching"}],
        },
    )
    res2 = await call(
        "log_journal",
        {
            "date": d2.isoformat(),
            "entries": [{"behavior": "magnesium"}],
        },
    )
    entry_id = res2["entries"][0]["id"]

    # Retrieve journal entries
    res_get = await call(
        "get_journal",
        {"start": d1.isoformat(), "end": d2.isoformat()},
    )
    assert len(res_get["entries"]) >= 2

    # Soft delete one entry
    del_res = await call("delete_journal_entry", {"entry_id": entry_id})
    assert del_res["deleted"] is True
    assert del_res["id"] == entry_id

    # Verify soft-deleted entry is no longer returned
    res_after = await call(
        "get_journal",
        {"start": d1.isoformat(), "end": d2.isoformat()},
    )
    active_ids = [e["id"] for e in res_after["entries"]]
    assert entry_id not in active_ids


async def test_get_journal_insights_tool(owner: Engine) -> None:
    t = today()
    with owner.begin() as conn:
        # Seed 6 days with cold_exposure, 6 days without (sauna instead)
        # All ending before today so recovery is on day D+1 <= today
        for i in range(6):
            d = t - dt.timedelta(days=20 - i * 2)
            conn.execute(
                text(
                    "INSERT INTO journal_entries (local_date, behavior, source) "
                    "VALUES (:d, 'cold_exposure', 'test') "
                    "ON CONFLICT (local_date, behavior) WHERE deleted_at IS NULL DO NOTHING"
                ),
                {"d": d},
            )
            conn.execute(
                text(
                    "INSERT INTO daily_scores (local_date, recovery, algo_version) "
                    "VALUES (:d_next, 80, 1) "
                    "ON CONFLICT (local_date) DO UPDATE SET recovery = EXCLUDED.recovery"
                ),
                {"d_next": d + dt.timedelta(days=1)},
            )

        for i in range(6):
            d = t - dt.timedelta(days=19 - i * 2)
            conn.execute(
                text(
                    "INSERT INTO journal_entries (local_date, behavior, source) "
                    "VALUES (:d, 'sauna', 'test') "
                    "ON CONFLICT (local_date, behavior) WHERE deleted_at IS NULL DO NOTHING"
                ),
                {"d": d},
            )
            conn.execute(
                text(
                    "INSERT INTO daily_scores (local_date, recovery, algo_version) "
                    "VALUES (:d_next, 70, 1) "
                    "ON CONFLICT (local_date) DO UPDATE SET recovery = EXCLUDED.recovery"
                ),
                {"d_next": d + dt.timedelta(days=1)},
            )

    res = await call("get_journal_insights", {"days": 60})
    assert "insights" in res
    assert "insufficient" in res
    assert res["logged_days"] >= 12

    cold = next((i for i in res["insights"] if i["behavior"] == "cold_exposure"), None)
    assert cold is not None
    assert cold["with_count"] == 6
    assert cold["without_count"] >= 6
    assert cold["with_mean_recovery"] == 80.0


async def test_sleep_settings_tools(owner: Engine) -> None:
    # 1. Validation checks
    err1 = await call_error("set_sleep_settings", {"base_need_min": 200})
    assert "360" in err1

    err2 = await call_error("set_sleep_settings", {"alarm_time": "25:70"})
    assert "HH:MM" in err2 or "24-hour" in err2

    err3 = await call_error(
        "set_sleep_settings",
        {"alarm_time": "06:30", "clear_alarm": True},
    )
    assert "both" in err3.lower()

    # 2. Set valid sleep need and alarm
    res = await call(
        "set_sleep_settings",
        {"base_need_min": 510, "alarm_time": "6:45"},
    )
    assert res["sleep_need_base_min"] == 510
    assert res["alarm_time"] == "06:45"

    # 3. get_sleep_settings
    res_get = await call("get_sleep_settings")
    assert res_get["sleep_need_base_min"] == 510
    assert res_get["alarm_time"] == "06:45"

    # 4. Clear alarm
    res_cleared = await call("set_sleep_settings", {"clear_alarm": True})
    assert res_cleared["sleep_need_base_min"] == 510
    assert res_cleared["alarm_time"] is None


async def test_profile_tools(owner: Engine) -> None:
    # 1. Validation
    assert "at least one" in await call_error("set_profile", {})
    assert "hr_max" in await call_error("set_profile", {"hr_max": 300})
    assert "birth_year" in await call_error("set_profile", {"birth_year": today().year + 1})
    err = await call_error("set_profile", {"hr_max": 195, "clear": ["hr_max"]})
    assert "same key" in err

    # 2. Nothing stored: server configuration (unset in tests) and the defaults
    empty = await call("get_profile")
    assert empty["stored_keys"] == []
    assert empty["effective_hr_max"] == 190
    assert empty["hr_max_source"] == "default"

    # 3. Birth year only: Tanaka estimate
    year = today().year
    res = await call("set_profile", {"birth_year": year - 40, "sex": "female"})
    assert res["age"] == 40
    assert res["sex"] == "female"
    assert res["effective_hr_max"] == 180
    assert res["hr_max_source"] == "estimated from age (Tanaka)"

    # 4. Measured HRmax wins
    res = await call("set_profile", {"hr_max": 197})
    assert res["effective_hr_max"] == 197
    assert res["hr_max_source"] == "measured"
    assert res["stored_keys"] == ["birth_year", "hr_max", "sex"]

    # 5. Clear
    res = await call("set_profile", {"clear": ["hr_max", "sex"]})
    assert res["hr_max"] is None
    assert res["sex"] is None
    assert res["stored_keys"] == ["birth_year"]
