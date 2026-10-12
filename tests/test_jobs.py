import datetime as dt
import json

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text

from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.jobs.quality import check_and_notify
from health_coach.jobs.scheduler import build_scheduler
from health_coach.notify.ntfy import NtfyClient


def test_data_quality_job_only_with_ntfy() -> None:
    assert "data_quality" not in {j.id for j in build_scheduler(Settings()).get_jobs()}
    settings = Settings(ntfy_topic=SecretStr("t"))
    assert "data_quality" in {j.id for j in build_scheduler(settings).get_jobs()}


def test_quality_check_notifies_stale_sources_only(
    owner: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ntfy_topic", SecretStr("topic"))
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_state (source, data_type, last_success_at, error_count) VALUES "
                "('google_health', 'steps', :old, 0), ('opengym', 'workouts', now(), 0), "
                "('worker', 'derived', NULL, 0), ('google_health', 'steps:backfill', NULL, 0)"
            ),
            {"old": old},
        )
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    warnings = check_and_notify(get_engine(Role.ingest), NtfyClient(client=client))
    assert any(w.startswith("google_health data is stale") for w in warnings)
    assert not any("opengym" in w or "worker" in w or "backfill" in w for w in warnings)
    assert len(sent) == 1 and sent[0]["title"] == "Data check"


def test_prompts_are_served() -> None:
    import asyncio

    from mcp import Client

    from health_coach.mcp_server.server import create_server

    async def run() -> list[str]:
        async with Client(create_server()) as client:
            prompts = (await client.list_prompts()).prompts
            review = await client.get_prompt("weekly_review", {})
        assert "write_coach_log" in str(review.messages[0].content)
        return [p.name for p in prompts]

    assert set(asyncio.run(run())) == {"weekly_review", "coach_instructions"}
