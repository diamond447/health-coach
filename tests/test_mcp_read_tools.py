import datetime as dt
import json
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


def _seed(owner: Engine) -> None:
    day = today()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO targets (effective_from, phase, kcal, protein_g, weekly_rate_min_kg, "
                "weekly_rate_max_kg, reason) VALUES (:d, 'bulk', 2700, 150, 0.2, 0.35, 'start')"
            ),
            {"d": day - dt.timedelta(days=60)},
        )
        for i in range(21):
            d = day - dt.timedelta(days=20 - i)
            conn.execute(
                text(
                    "INSERT INTO body_metrics (ts, local_date, weight_kg, source) "
                    "VALUES (:ts, :d, :kg, 'chat')"
                ),
                {"ts": dt.datetime.combine(d, dt.time(7), dt.UTC), "d": d, "kg": 78 + 0.04 * i},
            )
            conn.execute(
                text(
                    "INSERT INTO nutrition_entries (ts, local_date, meal, description, kcal, "
                    "protein_g, carbs_g, fat_g, confidence) VALUES "
                    "(:ts, :d, 'lunch', 'rice and chicken', 2650, 160, 300, 70, 'estimated')"
                ),
                {"ts": dt.datetime.combine(d, dt.time(12), dt.UTC), "d": d},
            )
            conn.execute(
                text("INSERT INTO daily_activity (local_date, steps) VALUES (:d, 9000)"),
                {"d": d},
            )
        conn.execute(
            text(
                "INSERT INTO coach_log (kind, title, body, tags) VALUES "
                "('decision', 'Start bulk', 'Start at 2700 kcal.', '{targets}')"
            )
        )


async def test_tools_are_listed_with_annotations() -> None:
    async with Client(create_server()) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    read_tools = {
        "get_context_snapshot",
        "get_schema",
        "get_data_coverage",
        "query_sql",
        "get_daily_overview",
        "get_weekly_summary",
        "get_weight_trend",
    }
    assert read_tools <= set(tools)
    for tool in tools.values():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.destructive_hint is not None, tool.name
        assert tool.annotations.idempotent_hint is not None, tool.name
        if tool.name in read_tools:
            assert tool.annotations.read_only_hint is True, tool.name


async def test_context_snapshot(owner: Engine) -> None:
    _seed(owner)
    snap = await call("get_context_snapshot")
    assert snap["targets"]["phase"] == "bulk"
    assert snap["weight"]["rate_vs_target"] == "in band"  # 0.28 kg/week
    assert len(snap["last_7_days"]["rows"]) == 7
    assert snap["coach_log_recent"]["rows"][0][3] == "Start bulk"
    assert any("stale" in w or "no sync" in w for w in snap["warnings"])
    # The snapshot must stay small enough for every conversation start.
    assert len(json.dumps(snap)) < 8000


async def test_context_snapshot_on_empty_db(owner: Engine) -> None:
    snap = await call("get_context_snapshot")
    assert snap["targets"] is None
    assert "no targets set yet: use set_targets" in snap["warnings"]


async def test_query_sql(owner: Engine) -> None:
    _seed(owner)
    res = await call(
        "query_sql",
        {
            "sql": "SELECT local_date, kcal_in FROM v_daily WHERE kcal_in IS NOT NULL "
            "AND local_date::text LIKE '20%' ORDER BY local_date",
            "max_rows": 5,
        },
    )
    assert res["columns"] == ["local_date", "kcal_in"]
    assert len(res["rows"]) == 5
    assert res["truncated"] is True


async def test_query_sql_rejects_writes(owner: Engine) -> None:
    msg = await call_error("query_sql", {"sql": "DELETE FROM coach_log"})
    assert "rejected" in msg


async def test_query_sql_reports_db_errors(owner: Engine) -> None:
    msg = await call_error("query_sql", {"sql": "SELECT no_such_column FROM v_daily"})
    assert "no_such_column" in msg


async def test_calls_are_audited(owner: Engine) -> None:
    await call("query_sql", {"sql": "SELECT 1 AS one"})
    await call_error("query_sql", {"sql": "DROP TABLE goals"})
    with owner.connect() as conn:
        rows = conn.execute(
            text("SELECT tool, rows_returned, error FROM mcp_audit ORDER BY id")
        ).all()
    assert [(r.tool, r.rows_returned) for r in rows] == [("query_sql", 1), ("query_sql", None)]
    assert rows[1].error and "rejected" in rows[1].error


async def test_get_schema(owner: Engine) -> None:
    overview = await call("get_schema")
    names = {r["name"] for r in overview["relations"]}
    assert {"v_daily", "nutrition_entries", "coach_log"} <= names
    assert names.isdisjoint({"oauth_tokens", "raw_payloads", "mcp_audit"})
    detail = await call("get_schema", {"table": "v_weight_trend"})
    assert any(c["name"] == "weekly_rate_kg" for c in detail["columns"])
    assert detail["examples"]


async def test_get_data_coverage(owner: Engine) -> None:
    _seed(owner)
    cov = await call("get_data_coverage")
    by_type = {r[0]: r for r in cov["coverage"]["rows"]}
    assert by_type["weight"][3] == 21
    assert by_type["sleep"][1] is None


async def test_daily_overview_and_range_cap(owner: Engine) -> None:
    _seed(owner)
    res = await call("get_daily_overview")
    assert len(res["rows"]) == 7
    msg = await call_error("get_daily_overview", {"start": "2020-01-01", "end": "2026-01-01"})
    assert "capped" in msg


async def test_weight_trend(owner: Engine) -> None:
    _seed(owner)
    res = await call("get_weight_trend", {"days": 14})
    assert len(res["rows"]) == 14
    assert res["current"]["target_band_kg"] == [0.2, 0.35]


async def test_weekly_summary(owner: Engine) -> None:
    _seed(owner)
    res = await call("get_weekly_summary")
    assert res["week"]["days_logged"] == 7
    assert res["week"]["kcal_avg"] == 2650
    assert res["week"]["days_kcal_on_target"] == 7
    assert res["week"]["days_protein_on_target"] == 7
    # The smoothed trend lags a fresh linear gain of 0.28 kg/week.
    assert 0.1 <= res["week"]["weight_change_kg"] <= 0.3
    assert "2026-W41" in await call_error("get_weekly_summary", {"iso_week": "41"})


async def test_query_sql_streams_and_bounds_large_results(owner: Engine) -> None:
    res = await call(
        "query_sql",
        {"sql": "SELECT g, md5(g::text) AS h FROM generate_series(1, 5000000) g", "max_rows": 3},
    )
    assert len(res["rows"]) == 3 and res["truncated"] is True
    wide = await call(
        "query_sql",
        {"sql": "SELECT string_agg(md5(g::text), '') AS s FROM generate_series(1, 2000) g"},
    )
    assert wide["rows"][0][0].endswith("...[truncated]")
    many = await call(
        "query_sql",
        {
            "sql": "SELECT string_agg(md5(g::text), '') AS s FROM generate_series(1, 60) g "
            "CROSS JOIN generate_series(1, 2000) n GROUP BY n",
            "max_rows": 2000,
        },
    )
    assert many["truncated"] is True and len(many["rows"]) < 2000


async def test_query_sql_keeps_percent_signs(owner: Engine) -> None:
    res = await call("query_sql", {"sql": "SELECT 'a%b' LIKE 'a%' AS ok"})
    assert res["rows"] == [[True]]
