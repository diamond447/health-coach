"""Performance smoke tests on a three-year synthetic history (tests/fixtures/seed_history.sql).

The thresholds are several times above what the queries take, so they hold on a slow CI
runner, but far below what a quadratic plan or a full scan would need. Deselect with
`-m "not perf"`."""

import time
from collections.abc import Callable
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

from health_coach.config import get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server.server import create_server
from health_coach.web.server import create_app
from tests.mcp_result import json_result
from tests.seed import seed_history

pytestmark = [pytest.mark.perf, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def best_ms(fn: Callable[[], Any], runs: int = 3) -> float:
    fn()  # warm caches and plans
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    return min(times)


async def test_three_year_history_stays_fast(owner: Engine) -> None:
    # One test, so the history is seeded once (~2 s).
    seed_history(owner, days=3 * 365, hr_days=7)
    with owner.begin() as conn:
        conn.execute(text("ANALYZE"))

    # The recursive weight trend took ~150 ms here, and ten times that for six years.
    with get_engine(Role.ro).connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM v_weight_trend")).scalar_one() > 700
        ms = best_ms(lambda: conn.execute(text("SELECT * FROM v_weight_trend")).all())
    assert ms < 50, f"v_weight_trend took {ms:.0f} ms"

    web = TestClient(create_app(get_settings()))
    for path, limit in (("/api/nutrition", 300), ("/api/report", 300), ("/api/trends", 300)):
        assert web.get(path).status_code == 200
        ms = best_ms(lambda path=path: web.get(path))  # type: ignore[misc]
        assert ms < limit, f"{path} took {ms:.0f} ms"

    async with Client(create_server()) as client:
        for tool, limit in (
            ("get_weekly_summary", 400),
            ("get_context_snapshot", 400),
            ("get_data_coverage", 300),
        ):
            json_result(await client.call_tool(tool, {}))
            times = []
            for _ in range(3):
                started = time.perf_counter()
                json_result(await client.call_tool(tool, {}))
                times.append((time.perf_counter() - started) * 1000)
            assert min(times) < limit, f"{tool} took {min(times):.0f} ms"
