import datetime as dt
import json
from typing import Any

import httpx
import pytest
from mcp import Client
from pydantic import SecretStr
from sqlalchemy import Engine, text

from health_coach.config import get_settings
from health_coach.mcp_server.common import today
from health_coach.mcp_server.server import create_server
from health_coach.notify import ntfy

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


async def test_targets_and_coach_log_integration(owner: Engine) -> None:
    d1 = today() - dt.timedelta(days=30)
    d2 = today()

    # 1. Set initial targets
    t1 = await call(
        "set_targets",
        {
            "effective_from": d1.isoformat(),
            "phase": "bulk",
            "kcal": 2800,
            "protein_g": 160,
            "reason": "Starting winter lean bulk",
            "weekly_rate_min_kg": 0.2,
            "weekly_rate_max_kg": 0.35,
        },
    )
    assert isinstance(t1["target_id"], int)
    assert isinstance(t1["coach_log_id"], int)

    # 2. Update targets
    t2 = await call(
        "set_targets",
        {
            "effective_from": d2.isoformat(),
            "phase": "cut",
            "kcal": 2300,
            "protein_g": 180,
            "reason": "Transitioning to cut",
            "weekly_rate_min_kg": -0.4,
            "weekly_rate_max_kg": -0.2,
        },
    )
    assert isinstance(t2["target_id"], int)

    # 3. get_targets returns current and history
    targets_info = await call("get_targets", {"date": d2.isoformat()})
    assert targets_info["current"]["phase"] == "cut"
    assert targets_info["current"]["kcal"] == 2300
    assert len(targets_info["history"]["rows"]) == 2

    # 4. Verify decision entry written in coach_log by set_targets
    with owner.connect() as conn:
        log_entry = conn.execute(
            text("SELECT title, body, kind, tags FROM coach_log WHERE id = :id"),
            {"id": t2["coach_log_id"]},
        ).one()
    assert log_entry.kind == "decision"
    assert log_entry.title == f"Targets from {d2}: cut 2300 kcal"
    assert "Transitioning to cut" in log_entry.body
    assert "phase: bulk -> cut" in log_entry.body
    assert "kcal: 2800 -> 2300" in log_entry.body
    assert "targets" in log_entry.tags

    # 5. Verify the decision shows up in get_context_snapshot (coach_log_recent)
    snap = await call("get_context_snapshot")
    recent_titles = [row[3] for row in snap["coach_log_recent"]["rows"]]
    assert f"Targets from {d2}: cut 2300 kcal" in recent_titles


async def test_read_and_write_coach_log(owner: Engine) -> None:
    # Write entries
    w1 = await call(
        "write_coach_log",
        {
            "kind": "observation",
            "title": "Sleep deficit noted",
            "body": "Average sleep dropped under 7 hours this week.",
            "tags": ["sleep", "recovery"],
        },
    )
    w2 = await call(
        "write_coach_log",
        {
            "kind": "plan",
            "title": "Deload week upcoming",
            "body": "Plan deload for next week due to high fatigue.",
            "tags": ["training", "fatigue"],
        },
    )
    assert isinstance(w1["id"], int)
    assert isinstance(w2["id"], int)

    # Read with filter by kind
    obs = await call("read_coach_log", {"kind": "observation"})
    assert len(obs["rows"]) == 1
    assert obs["rows"][0][3] == "Sleep deficit noted"

    # Read with filter by tag
    rec = await call("read_coach_log", {"tag": "recovery"})
    assert len(rec["rows"]) == 1
    assert rec["rows"][0][3] == "Sleep deficit noted"

    # Read with search
    searched = await call("read_coach_log", {"search": "fatigue"})
    assert len(searched["rows"]) == 1
    assert searched["rows"][0][3] == "Deload week upcoming"

    # Validation: empty title or body
    msg = await call_error(
        "write_coach_log",
        {
            "kind": "note",
            "title": "",
            "body": "Some note",
        },
    )
    assert "title cannot be empty" in msg


async def test_manage_goal(owner: Engine) -> None:
    # 1. Create goal
    g1 = await call(
        "manage_goal",
        {
            "action": "create",
            "name": "Squat 140 kg",
            "metric": "e1rm_kg",
            "target_value": 140.0,
            "deadline": (today() + dt.timedelta(days=90)).isoformat(),
            "notes": "Target for end of mesocycle",
        },
    )
    assert g1["id"] is not None
    assert g1["status"] == "open"
    assert g1["closed_at"] is None
    goal_id = g1["id"]

    # 2. Update goal
    g2 = await call(
        "manage_goal",
        {
            "action": "update",
            "goal_id": goal_id,
            "target_value": 145.0,
            "notes": "Raised target to 145 kg",
        },
    )
    assert g2["target_value"] == 145.0
    assert g2["notes"] == "Raised target to 145 kg"

    # 3. Close goal (default status: achieved)
    g3 = await call(
        "manage_goal",
        {
            "action": "close",
            "goal_id": goal_id,
        },
    )
    assert g3["status"] == "achieved"
    assert g3["closed_at"] is not None

    # Validation: close invalid status
    msg = await call_error(
        "manage_goal",
        {
            "action": "close",
            "goal_id": goal_id,
            "status": "open",
        },
    )
    assert "must be achieved or abandoned" in msg


async def test_send_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. When topic is not configured -> ToolError
    monkeypatch.setattr(get_settings(), "ntfy_topic", None)
    msg = await call_error(
        "send_notification",
        {"title": "Test Title", "body": "Test notification body"},
    )
    assert "notifications are not configured" in msg

    # 2. Configured and mocked HTTP POST
    monkeypatch.setattr(get_settings(), "ntfy_topic", SecretStr("test-secret-topic"))
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"id": "ntfy-123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    try:
        res = await call(
            "send_notification",
            {
                "title": "Nový rekord",
                "body": "New squat PR achieved: 140 kg!",
                "priority": 4,
                "tags": ["trophy", "fitness"],
            },
        )
        assert res["sent"] is True
        assert len(sent_requests) == 1
        sent = json.loads(sent_requests[0].content)
        assert sent == {
            "topic": "test-secret-topic",
            "title": "Nový rekord",
            "message": "New squat PR achieved: 140 kg!",
            "priority": 4,
            "tags": ["trophy", "fitness"],
        }
    finally:
        ntfy.set_client(None)
