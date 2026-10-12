"""Tests for the fit multi-user openGym MCP server."""

import datetime as dt
import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from pydantic import SecretStr
from starlette.testclient import TestClient

from health_coach import __version__
from health_coach.fit.server import create_fit_server
from health_coach.fit.settings import FitSettings
from health_coach.fit.store import FitStore, FitTokenKeyError
from health_coach.fit.tools import current_subject_var, mock_transport_var
from health_coach.mcp_server.auth import AuthConfigError
from health_coach.opengym import catalogue

pytestmark = pytest.mark.anyio

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
ISSUER = "https://auth.example.test/application/o/fit/"
FIT_AUDIENCE = ["fit-client-claude", "fit-client-chatgpt"]
PUBLIC_URL = "https://fit.example.test/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    return " ".join(getattr(c, "text", "") for c in content)


class FakeOpenGym:
    """Mock openGym REST server simulating pair redeem, me, data GET/PUT, revisions and 409."""

    def __init__(self) -> None:
        self.pairings: dict[str, dict[str, Any]] = {
            "PAIRALIC": {"id": "user_alice", "name": "Alice"},
            "PAIRBOBB": {"id": "user_bob", "name": "Bob"},
        }
        self.tokens: dict[str, dict[str, Any]] = {}
        self.conflict_once = False
        self.expired_tokens: set[str] = set()
        self.renew_on_me: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth_header = request.headers.get("Authorization", "")
        token = (
            auth_header.removeprefix("Bearer ").strip()
            if auth_header.startswith("Bearer ")
            else None
        )

        # 1. Pairing redeem
        if path == "/api/pair/redeem" and request.method == "POST":
            body = json.loads(request.content.decode())
            code = body.get("code")
            if code in self.pairings:
                user = self.pairings[code]
                tok = f"tok_{code}"
                self.tokens[tok] = {
                    "user": user,
                    "rev": 1,
                    "state": {
                        "unit": "kg",
                        "customEx": [],
                        "routines": [],
                        "workouts": [],
                        "dayPlan": {},
                        "week": {},
                        "_unknown_marker": "keep_me",
                    },
                }
                return httpx.Response(200, json={"token": tok, "user": user})
            return httpx.Response(400, json={"error": "invalid code"})

        # Check authentication for remaining endpoints
        if not token or token not in self.tokens or token in self.expired_tokens:
            return httpx.Response(401, json={"error": "unauthorized"})

        user_data = self.tokens[token]

        # 2. /api/me
        if path == "/api/me" and request.method == "GET":
            renewed = self.renew_on_me.get(token)
            resp: dict[str, Any] = {"user": user_data["user"]}
            if renewed:
                # Replace token
                self.tokens[renewed] = user_data
                resp["token"] = renewed
            return httpx.Response(200, json=resp)

        # 3. GET /api/data
        if path == "/api/data" and request.method == "GET":
            return httpx.Response(200, json={"state": user_data["state"], "rev": user_data["rev"]})

        # 4. PUT /api/data
        if path == "/api/data" and request.method == "PUT":
            body = json.loads(request.content.decode())
            base_rev = body.get("baseRev")
            new_state = body.get("state", {})

            if self.conflict_once:
                self.conflict_once = False
                user_data["rev"] += 1
                return httpx.Response(
                    409,
                    json={
                        "error": "conflict",
                        "state": user_data["state"],
                        "rev": user_data["rev"],
                    },
                )

            if base_rev is not None and base_rev != user_data["rev"]:
                user_data["rev"] += 1
                return httpx.Response(
                    409,
                    json={
                        "error": "conflict",
                        "state": user_data["state"],
                        "rev": user_data["rev"],
                    },
                )

            user_data["state"] = new_state
            user_data["rev"] += 1
            return httpx.Response(200, json={"ok": True, "rev": user_data["rev"]})

        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fake_og() -> FakeOpenGym:
    return FakeOpenGym()


@pytest.fixture
def fit_env(tmp_path: Any, fake_og: FakeOpenGym) -> tuple[FitSettings, FitStore]:
    db_file = str(tmp_path / "fit.db")
    settings = FitSettings(
        opengym_url="https://opengym.local",
        db_path=db_file,
        token_key=SecretStr(TEST_FERNET_KEY),
        auth_disabled=True,
        dev_subject="alice",
    )
    store = FitStore(settings)
    mock_transport_var.set(httpx.MockTransport(fake_og.handler))
    return settings, store


async def test_unlinked_user_gets_clear_error(fit_env: tuple[FitSettings, FitStore]) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("unlinked_user")

    async with Client(server) as client:
        res = await client.call_tool("get_planned", {"days": 7})
        assert res.is_error
        text = " ".join(getattr(c, "text", "") for c in res.content)
        assert "not connected to an openGym account" in text
        assert "Pair the mobile app" in text
        assert "link_opengym" in text


async def test_linking_and_account(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        # Bad code
        bad_link = await client.call_tool("link_opengym", {"code": "SHORT"})
        assert bad_link.is_error

        # Successful pairing
        link_res = await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        assert not link_res.is_error
        data = link_res.structured_content
        assert data["status"] == "linked"
        assert data["openGym_username"] == "Alice"

        # Check account
        acc_res = await client.call_tool("get_account", {})
        assert not acc_res.is_error
        acc_data = acc_res.structured_content
        assert acc_data["status"] == "connected"
        assert acc_data["openGym_username"] == "Alice"
        assert acc_data["openGym_user_id"] == "user_alice"


async def test_plan_session_preserves_unknown_fields_and_routine_weights(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Plan a session with per-set weights
        plan_res = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-15",
                "name": "Upper Power",
                "exercises": [
                    {
                        "exercise_id": "bench_press",
                        "sets": [
                            {"reps": 8, "weight_kg": 80.0, "rir": 2},
                            {"reps": 8, "weight_kg": 85.0, "rir": 1},
                            {"reps": 6, "weight_kg": 90.0, "rir": 0},
                        ],
                        "rest_s": 180,
                        "notes": "Barbell bench press",
                    }
                ],
            },
        )
        assert not plan_res.is_error
        plan_data = plan_res.structured_content
        assert plan_data["status"] == "planned"
        assert plan_data["date"] == "2026-10-15"

        # Verify state in fake openGym
        og_user = fake_og.tokens["tok_PAIRALIC"]
        st = og_user["state"]
        assert st["_unknown_marker"] == "keep_me"
        assert "2026-10-15" in st["dayPlan"]
        r_id = st["dayPlan"]["2026-10-15"]
        routine = next(r for r in st["routines"] if r["id"] == r_id)
        assert routine["name"] == "Upper Power"
        assert routine["excludeFromProgression"] is True
        ex_cfg = routine["ex"][0]
        assert ex_cfg["id"] == "bench_press"
        assert ex_cfg["pyramidWeight"] == [80.0, 85.0, 90.0]
        assert ex_cfg["pyramid"] == [8, 8, 6]
        assert ex_cfg["prog"] == "off"

        # Check get_planned reflects the dayPlan
        planned_res = await client.call_tool("get_planned", {"days": 10})
        assert not planned_res.is_error
        sched = planned_res.structured_content["schedule"]
        day_15 = next((d for d in sched if d["date"] == "2026-10-15"), None)
        if day_15:
            assert day_15["planned"] == "routine"
            assert day_15["routine_name"] == "Upper Power"


async def test_plan_session_conflict_retry(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Trigger conflict once on PUT /api/data
        fake_og.conflict_once = True

        res = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-20",
                "name": "Leg Day",
                "exercises": [
                    {
                        "exercise_id": "squat",
                        "sets": 3,
                        "reps": 5,
                        "weight_kg": 100.0,
                    }
                ],
            },
        )
        assert not res.is_error
        assert res.structured_content["status"] == "planned"
        # Revision should have incremented twice: once for 409 conflict, once for retry success
        assert fake_og.tokens["tok_PAIRALIC"]["rev"] == 3


async def test_training_history_and_trend(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    today = dt.datetime.now(settings.tz).date()

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Seed completed workouts in openGym
        og_user = fake_og.tokens["tok_PAIRALIC"]
        og_user["state"]["workouts"] = [
            {
                "id": "w1",
                "d": (today - dt.timedelta(days=7)).isoformat(),
                "name": "Chest A",
                "entries": [
                    {
                        "id": "bench_press",
                        "sets": [
                            {"w": 80.0, "r": 8, "done": True, "rir": 2, "warm": False},
                            {"w": 85.0, "r": 8, "done": True, "rir": 1, "warm": False},
                        ],
                    }
                ],
            },
            {
                "id": "w2",
                "d": today.isoformat(),
                "name": "Chest B",
                "entries": [
                    {
                        "id": "bench_press",
                        "sets": [
                            {"w": 90.0, "r": 6, "done": True, "rir": 0, "warm": False},
                        ],
                    }
                ],
            },
        ]

        # Full history
        hist_res = await client.call_tool("get_training_history", {"days": 14})
        assert not hist_res.is_error
        assert hist_res.structured_content["sessions_count"] == 2

        # Filtered by exercise with trend
        trend_res = await client.call_tool(
            "get_training_history", {"days": 14, "exercise": "bench_press"}
        )
        assert not trend_res.is_error
        trend_data = trend_res.structured_content
        assert trend_data["sessions_count"] == 2
        trend = trend_data["trend"]
        assert trend[0]["top_weight_kg"] == 85.0
        assert trend[1]["top_weight_kg"] == 90.0
        assert trend[1]["reps"] == 6
        assert trend[1]["e1rm_kg"] == 108.0  # 90 * (1 + 6/30) = 108.0


async def test_two_subjects_isolated(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)

    async with Client(server) as client:
        # Subject 1 (alice) pairs with ALICE
        current_subject_var.set("subject_alice")
        res1 = await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        assert not res1.is_error

        # Subject 2 (bob) pairs with BOB
        current_subject_var.set("subject_bob")
        res2 = await client.call_tool("link_opengym", {"code": "PAIRBOBB"})
        assert not res2.is_error

        # Subject 1 plans a workout
        current_subject_var.set("subject_alice")
        await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-18",
                "name": "Alice Workout",
                "exercises": [{"exercise_id": "curl", "sets": 3, "reps": 10, "weight_kg": 15.0}],
            },
        )

        # Subject 2 cannot see Alice's planned workout
        current_subject_var.set("subject_bob")
        b_acc = await client.call_tool("get_account", {})
        assert b_acc.structured_content["openGym_username"] == "Bob"

        b_plan = await client.call_tool("get_planned", {"days": 14})
        b_sched = b_plan.structured_content["schedule"]
        day_18 = next((d for d in b_sched if d["date"] == "2026-10-18"), None)
        assert day_18 is not None
        assert day_18["planned"] == "rest" or day_18.get("source") == "none"

        # Bob unlinks; Alice remains linked
        await client.call_tool("unlink_opengym", {})
        bob_check = await client.call_tool("get_account", {})
        assert bob_check.is_error

        current_subject_var.set("subject_alice")
        alice_check = await client.call_tool("get_account", {})
        assert not alice_check.is_error
        assert alice_check.structured_content["openGym_username"] == "Alice"


async def test_401_session_expired_does_not_delete_link(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Expire token in openGym
        fake_og.expired_tokens.add("tok_PAIRALIC")

        res = await client.call_tool("get_account", {})
        assert res.is_error
        err_msg = " ".join(getattr(c, "text", "") for c in res.content)
        assert "openGym session expired or unauthorized (401)" in err_msg
        assert "link was preserved" in err_msg

        # Link is still in SQLite
        link = store.get_link("alice")
        assert link is not None


async def test_token_renewal_stored(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Configure fake openGym to return renewed token on /api/me
        fake_og.renew_on_me["tok_PAIRALIC"] = "tok_renewed_alice"

        res = await client.call_tool("get_account", {})
        assert not res.is_error

        # Store should now hold renewed token
        link = store.get_link("alice")
        assert link is not None
        assert link.token == "tok_renewed_alice"
        assert link.renewed_at is not None


async def test_additional_fit_tools(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # 1. schedule_week
        # First add a routine
        og_st = fake_og.tokens["tok_PAIRALIC"]["state"]
        og_st["routines"].append(
            {"id": "r1", "name": "Push Day", "ex": [], "fitPlanned": "2026-10-25"}
        )

        sched_res = await client.call_tool(
            "schedule_week", {"schedule": {"mon": "r1", "wed": "rest"}}
        )
        assert not sched_res.is_error
        assert fake_og.tokens["tok_PAIRALIC"]["state"]["week"]["1"] == ["r1"]

        # 2. update_routine
        upd_res = await client.call_tool(
            "update_routine", {"routine_id": "r1", "changes": {"name": "Push Heavy"}}
        )
        assert not upd_res.is_error
        assert fake_og.tokens["tok_PAIRALIC"]["state"]["routines"][0]["name"] == "Push Heavy"

        # 3. get_routines and get_routine
        routines_res = await client.call_tool("get_routines", {})
        assert not routines_res.is_error
        assert routines_res.structured_content["count"] == 1

        single_r = await client.call_tool("get_routine", {"routine_id": "r1"})
        assert not single_r.is_error
        assert single_r.structured_content["name"] == "Push Heavy"

        # 4. delete_planned
        fake_og.tokens["tok_PAIRALIC"]["state"]["dayPlan"]["2026-10-25"] = "r1"
        del_res = await client.call_tool("delete_planned", {"date": "2026-10-25"})
        assert not del_res.is_error
        assert "2026-10-25" not in fake_og.tokens["tok_PAIRALIC"]["state"]["dayPlan"]

        # 5. log_session
        log_res = await client.call_tool(
            "log_session",
            {
                "date": "2026-10-11",
                "exercises": [
                    {
                        "exercise_id": "deadlift",
                        "sets": [{"reps": 5, "weight_kg": 140.0, "rir": 2}],
                    }
                ],
                "notes": "Solid workout",
            },
        )
        assert not log_res.is_error
        workouts = fake_og.tokens["tok_PAIRALIC"]["state"]["workouts"]
        assert len(workouts) == 1
        assert workouts[0]["entries"][0]["id"] == "deadlift"


def make_jwt(key: Any = KEY, alg: str = "RS256", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": FIT_AUDIENCE[0],
        "sub": "owner_user",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


def test_fit_http_auth_and_cross_audience(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = str(tmp_path / "fit.db")
    settings = FitSettings(
        public_url=PUBLIC_URL,
        auth_issuer=ISSUER,
        auth_audience=FIT_AUDIENCE,
        db_path=db_file,
        token_key=SecretStr(TEST_FERNET_KEY),
        auth_disabled=False,
    )
    monkeypatch.setattr(
        "health_coach.mcp_server.auth.jwks_resolver", lambda _url: lambda _t: KEY.public_key()
    )

    app = create_fit_server(settings, with_auth=True).streamable_http_app(host="fit.example.test")

    with TestClient(app, base_url="http://fit.example.test") as client:
        # Public healthz
        healthz = client.get("/healthz")
        assert healthz.status_code == 200
        assert healthz.json()["version"] == __version__

        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        # Unauthenticated request gets 401 with WWW-Authenticate header
        unauth = client.post("/mcp", json=init_req, headers=headers)
        assert unauth.status_code == 401
        assert "Bearer" in unauth.headers.get("www-authenticate", "")

        # Protected resource metadata
        meta = client.get("/.well-known/oauth-protected-resource/mcp")
        assert meta.status_code == 200
        doc = meta.json()
        assert doc["resource"] == PUBLIC_URL
        assert doc["authorization_servers"] == [ISSUER]

        # Token for different audience (e.g. health-coach) is rejected by fit server
        hc_token = make_jwt(aud="health-coach-client")
        rejected = client.post(
            "/mcp", json=init_req, headers={**headers, "Authorization": f"Bearer {hc_token}"}
        )
        assert rejected.status_code == 401

        # Token with health-coach issuer and fit audience is rejected
        hc_iss_token = make_jwt(
            iss="https://auth.example.test/application/o/health-coach/",
            aud=FIT_AUDIENCE[0],
        )
        rejected_iss = client.post(
            "/mcp", json=init_req, headers={**headers, "Authorization": f"Bearer {hc_iss_token}"}
        )
        assert rejected_iss.status_code == 401

        # Token for fit audience is accepted
        fit_token = make_jwt(aud=FIT_AUDIENCE[0])
        accepted = client.post(
            "/mcp", json=init_req, headers={**headers, "Authorization": f"Bearer {fit_token}"}
        )
        assert accepted.status_code == 200


def test_injected_subject_is_ignored_when_auth_is_enabled() -> None:
    """The test hook must not override (or replace) a verified identity in production."""
    from mcp.server.mcpserver.exceptions import ToolError

    from health_coach.fit.tools import current_subject_var, get_subject

    settings = FitSettings(auth_disabled=False)
    reset = current_subject_var.set("someone-else")
    try:
        with pytest.raises(ToolError, match="Authentication required"):
            get_subject(settings)
    finally:
        current_subject_var.reset(reset)


async def test_plan_session_replace_never_rewrites_a_users_own_routine(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")
    session = {
        "date": "2026-10-15",
        "name": "Coach plan",
        "exercises": [{"exercise_id": "squat", "sets": [{"reps": 5, "weight_kg": 101.25}]}],
    }
    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        st.setdefault("routines", []).append({"id": "mine", "name": "My legs", "ex": []})
        st.setdefault("dayPlan", {})["2026-10-15"] = "mine"

        res = await client.call_tool("plan_session", {**session, "replace": True})
        assert not res.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        mine = next(r for r in st["routines"] if r["id"] == "mine")
        assert mine == {"id": "mine", "name": "My legs", "ex": []}
        planned_id = st["dayPlan"]["2026-10-15"]
        assert planned_id != "mine"
        planned = next(r for r in st["routines"] if r["id"] == planned_id)
        assert planned["ex"][0]["pyramidWeight"] == [101.25]

        # A second replace rewrites the server's own session in place.
        res = await client.call_tool("plan_session", {**session, "replace": True})
        assert not res.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        assert st["dayPlan"]["2026-10-15"] == planned_id
        assert sum(1 for r in st["routines"] if r.get("fitPlanned")) == 1


async def test_plan_session_writes_weights_in_the_profile_unit(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")
    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        fake_og.tokens["tok_PAIRALIC"]["state"]["unit"] = "lb"
        res = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-16",
                "name": "Bench",
                "exercises": [{"exercise_id": "bench", "sets": [{"reps": 5, "weight_kg": 100}]}],
            },
        )
        assert not res.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        routine = next(r for r in st["routines"] if r["id"] == st["dayPlan"]["2026-10-16"])
        assert routine["ex"][0]["pyramidWeight"] == [220.5]


def test_server_refuses_auth_disabled_on_non_loopback(tmp_path: Any) -> None:
    db_file = str(tmp_path / "fit.db")
    for host in ("0.0.0.0", "192.168.1.10", "example.com"):  # noqa: S104
        s = FitSettings(
            auth_disabled=True,
            mcp_host=host,
            db_path=db_file,
            token_key=SecretStr(TEST_FERNET_KEY),
        )
        with pytest.raises(AuthConfigError, match="only allowed on loopback host"):
            create_fit_server(s, with_auth=False)

    for host in ("127.0.0.1", "::1", "localhost"):
        s = FitSettings(
            auth_disabled=True,
            mcp_host=host,
            db_path=db_file,
            token_key=SecretStr(TEST_FERNET_KEY),
        )
        server = create_fit_server(s, with_auth=False)
        assert server.name == "fit"


def test_server_refuses_invalid_or_missing_fernet_key_on_startup(tmp_path: Any) -> None:
    db_file = str(tmp_path / "fit.db")
    s_invalid = FitSettings(
        auth_disabled=False,
        auth_issuer=ISSUER,
        auth_audience=FIT_AUDIENCE,
        public_url=PUBLIC_URL,
        token_key=SecretStr("not-a-valid-fernet-key"),
        db_path=db_file,
    )
    with pytest.raises(FitTokenKeyError, match="FIT_TOKEN_KEY is invalid"):
        create_fit_server(s_invalid, with_auth=False)

    s_none = FitSettings(
        auth_disabled=False,
        auth_issuer=ISSUER,
        auth_audience=FIT_AUDIENCE,
        public_url=PUBLIC_URL,
        token_key=None,
        db_path=db_file,
    )
    with pytest.raises(FitTokenKeyError, match="FIT_TOKEN_KEY is not set"):
        create_fit_server(s_none, with_auth=False)


async def test_search_exercises_catalogue_carries_no_auth_header(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    seen_requests: list[tuple[str, str, str | None]] = []

    def tracking_handler(req: httpx.Request) -> httpx.Response:
        seen_requests.append((req.method, str(req.url), req.headers.get("authorization")))
        return fake_og.handler(req)

    mock_transport_var.set(httpx.MockTransport(tracking_handler))
    catalogue._CATALOGUE_CACHE.clear()

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        res = await client.call_tool("search_exercises", {"query": "bench"})
        assert not res.is_error

    for _, url, auth in seen_requests:
        if "raw.githubusercontent.com" in url:
            assert auth is None


async def test_input_validation_plan_session_and_models(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Negative / invalid sets
        for bad_sets in (0, -1, 11):
            r = await client.call_tool(
                "plan_session",
                {
                    "date": "2026-10-20",
                    "name": "Invalid Sets",
                    "exercises": [{"exercise_id": "bench", "sets": bad_sets}],
                },
            )
            assert r.is_error

        # Invalid reps: 0, negative, > 100
        for bad_reps in (0, -5, 101):
            r = await client.call_tool(
                "plan_session",
                {
                    "date": "2026-10-20",
                    "name": "Invalid Reps",
                    "exercises": [{"exercise_id": "bench", "sets": 3, "reps": bad_reps}],
                },
            )
            assert r.is_error

        # Valid 'max' reps
        r_max = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-20",
                "name": "Max Reps",
                "exercises": [
                    {
                        "exercise_id": "bench",
                        "sets": [{"reps": "max", "weight_kg": 60}],
                    }
                ],
            },
        )
        assert not r_max.is_error

        # Invalid weights: negative, > 1000
        for bad_w in (-10.0, 1005.0):
            r = await client.call_tool(
                "plan_session",
                {
                    "date": "2026-10-21",
                    "name": "Invalid Weight",
                    "exercises": [{"exercise_id": "bench", "sets": 3, "weight_kg": bad_w}],
                },
            )
            assert r.is_error

        # Invalid rir / rpe / rest_s
        r_rir = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-21",
                "name": "Bad RIR",
                "exercises": [
                    {
                        "exercise_id": "bench",
                        "sets": [{"reps": 10, "weight_kg": 50, "rir": 15}],
                    }
                ],
            },
        )
        assert r_rir.is_error

        r_rest = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-21",
                "name": "Bad Rest",
                "exercises": [{"exercise_id": "bench", "sets": 3, "rest_s": 5000}],
            },
        )
        assert r_rest.is_error

        # Long name (> 80 chars)
        r_name = await client.call_tool(
            "plan_session",
            {"date": "2026-10-21", "name": "A" * 85, "exercises": [{"exercise_id": "bench"}]},
        )
        assert r_name.is_error

        # Dates out of -400..+400 range
        for bad_date in ("2024-01-01", "2029-01-01"):
            r_d = await client.call_tool(
                "plan_session",
                {"date": bad_date, "name": "Bad Date", "exercises": [{"exercise_id": "bench"}]},
            )
            assert r_d.is_error

        # More than 30 exercises
        exs = [{"exercise_id": f"ex_{i}", "sets": 3} for i in range(35)]
        r_exs = await client.call_tool(
            "plan_session",
            {"date": "2026-10-21", "name": "Too Many", "exercises": exs, "replace": True},
        )
        assert r_exs.is_error

        # Extra fields forbidden
        r_extra = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-21",
                "name": "Extra field",
                "exercises": [{"exercise_id": "bench", "sets": 3, "evil": {"x": 1}}],
            },
        )
        assert r_extra.is_error


async def test_update_routine_fit_planned_enforcement_and_round_trip(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        st = fake_og.tokens["tok_PAIRALIC"]["state"]

        # 1. User's routine without fitPlanned cannot be updated
        st["routines"].append({"id": "user_rt", "name": "User Routine", "ex": []})
        upd_err = await client.call_tool(
            "update_routine",
            {"routine_id": "user_rt", "changes": {"name": "Hacked Routine"}},
        )
        assert upd_err.is_error
        assert "plan a new session instead" in _content_text(upd_err)

        # 2. Fit planned routine can be updated
        plan_res = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-22",
                "name": "Fit Routine",
                "exercises": [
                    {
                        "exercise_id": "bench",
                        "sets": 3,
                        "reps_min": 8,
                        "reps_max": 12,
                        "weight_kg": 75.0,
                        "rest_s": 90,
                        "note": "Stay tight",
                    }
                ],
            },
        )
        assert not plan_res.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        rid = st["dayPlan"]["2026-10-22"]

        # Fetch with get_routine
        get_res = await client.call_tool("get_routine", {"routine_id": rid})
        assert not get_res.is_error
        rt_data = get_res.structured_content

        # Exercises match input schema: pass directly back to update_routine
        ex_input = rt_data["exercises"]
        ex_input[0]["weight_kg"] = 80.0
        upd_ok = await client.call_tool(
            "update_routine",
            {"routine_id": rid, "changes": {"name": "Fit Routine Updated", "exercises": ex_input}},
        )
        assert not upd_ok.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        stored_rt = next(r for r in st["routines"] if r["id"] == rid)
        assert stored_rt["name"] == "Fit Routine Updated"
        assert stored_rt["ex"][0]["weight"] == 80.0
        assert stored_rt["ex"][0]["prog"] == "off"
        assert stored_rt["excludeFromProgression"] is True


async def test_duplicate_writes_and_idempotency(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    fail_put = {"count": 1}

    def flaky_put_handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PUT" and fail_put["count"] > 0:
            fail_put["count"] -= 1
            return httpx.Response(502, text="bad gateway")
        return fake_og.handler(req)

    mock_transport_var.set(httpx.MockTransport(flaky_put_handler))

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # PUT error is surfaced immediately (no tenacity retry loop on PUT)
        r = await client.call_tool(
            "log_session",
            {
                "date": "2026-10-11",
                "exercises": [
                    {
                        "exercise_id": "deadlift",
                        "sets": [{"reps": 5, "weight_kg": 140}],
                    }
                ],
            },
        )
        assert r.is_error
        assert "502" in _content_text(r)

        # Re-trying log_session generates a fresh attempt and succeeds
        r2 = await client.call_tool(
            "log_session",
            {
                "date": "2026-10-11",
                "exercises": [
                    {
                        "exercise_id": "deadlift",
                        "sets": [{"reps": 5, "weight_kg": 140}],
                    }
                ],
            },
        )
        assert not r2.is_error
        workouts = fake_og.tokens["tok_PAIRALIC"]["state"]["workouts"]
        assert len(workouts) == 1

        # plan_session idempotency
        plan_r = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-23",
                "name": "Leg Day",
                "exercises": [{"exercise_id": "squat", "sets": 3, "reps": 5, "weight_kg": 100}],
            },
        )
        assert not plan_r.is_error

        # Test 409 conflict lacking state dict aborts
        fake_og.conflict_once = True
        orig_handler = fake_og.handler

        def malformed_conflict_handler(req: httpx.Request) -> httpx.Response:
            if req.method == "PUT":
                return httpx.Response(409, json={"error": "conflict", "state": None, "rev": 2})
            return orig_handler(req)

        mock_transport_var.set(httpx.MockTransport(malformed_conflict_handler))
        bad_409 = await client.call_tool(
            "log_session",
            {"date": "2026-10-12", "exercises": [{"exercise_id": "bench", "sets": 3}]},
        )
        assert bad_409.is_error


async def test_rep_ranges_and_pyramid_weight_distinction(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # Rep range with flat weight -> NO pyramid or pyramidWeight written
        r1 = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-24",
                "name": "Range Session",
                "exercises": [
                    {
                        "exercise_id": "bench",
                        "sets": 3,
                        "reps_min": 8,
                        "reps_max": 12,
                        "weight_kg": 60.0,
                    }
                ],
            },
        )
        assert not r1.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        r_id1 = st["dayPlan"]["2026-10-24"]
        cfg1 = next(r for r in st["routines"] if r["id"] == r_id1)["ex"][0]
        assert "pyramid" not in cfg1
        assert "pyramidWeight" not in cfg1
        assert cfg1["weight"] == 60.0
        assert cfg1["repsMin"] == 8
        assert cfg1["repsMax"] == 12
        assert cfg1["prog"] == "off"

        # Per-set reps -> pyramid and pyramidWeight written
        r2 = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-25",
                "name": "Pyramid Session",
                "exercises": [
                    {
                        "exercise_id": "squat",
                        "sets": [
                            {"reps": 10, "weight_kg": 80.0},
                            {"reps": 8, "weight_kg": 90.0},
                        ],
                    }
                ],
            },
        )
        assert not r2.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        r_id2 = st["dayPlan"]["2026-10-25"]
        cfg2 = next(r for r in st["routines"] if r["id"] == r_id2)["ex"][0]
        assert cfg2["pyramid"] == [10, 8]
        assert cfg2["pyramidWeight"] == [80.0, 90.0]


async def test_lb_profiles_read_all_weights_in_kg(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        st["unit"] = "lb"

        # 220.462 lb = 100 kg
        st["routines"].append(
            {
                "id": "r_lb",
                "name": "LB Routine",
                "fitPlanned": "2026-10-26",
                "ex": [
                    {
                        "id": "bench",
                        "sets": 2,
                        "mode": "reps",
                        "reps": 5,
                        "weight": 220.5,
                        "pyramid": [5, 5],
                        "pyramidWeight": [220.5, 242.5],
                        "note": "heavy",
                    }
                ],
            }
        )
        st["workouts"].append(
            {
                "id": "w_lb",
                "d": "2026-10-10",
                "name": "LB Workout",
                "entries": [
                    {
                        "id": "bench",
                        "sets": [{"w": 220.5, "r": 5, "done": True, "rir": 1, "warm": False}],
                    }
                ],
            }
        )

        # get_routine converts to kg
        r_res = await client.call_tool("get_routine", {"routine_id": "r_lb"})
        assert not r_res.is_error
        ex0 = r_res.structured_content["exercises"][0]
        assert ex0["weight_kg"] == 100.02
        assert ex0["pyramid_weight"] == [100.02, 110.0]
        assert ex0["note"] == "heavy"

        # get_routines converts to kg
        rs_res = await client.call_tool("get_routines", {})
        assert not rs_res.is_error
        r_match = next(r for r in rs_res.structured_content["routines"] if r["id"] == "r_lb")
        assert r_match["exercises"][0]["weight_kg"] == 100.02

        # get_training_history converts to kg
        hist_res = await client.call_tool("get_training_history", {"days": 30, "exercise": "bench"})
        assert not hist_res.is_error
        assert hist_res.structured_content["trend"][0]["top_weight_kg"] == 100.0


async def test_exercise_notes_written_and_read_cleanly(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})

        # plan_session writes cfg.note
        r_plan = await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-27",
                "name": "Note Test",
                "exercises": [
                    {
                        "exercise_id": "press",
                        "sets": 3,
                        "reps": 8,
                        "weight_kg": 50.0,
                        "note": "Lock out shoulders",
                    }
                ],
            },
        )
        assert not r_plan.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        rid = st["dayPlan"]["2026-10-27"]
        rt = next(r for r in st["routines"] if r["id"] == rid)
        assert rt["ex"][0]["note"] == "Lock out shoulders"

        # get_routine reads note
        r_get = await client.call_tool("get_routine", {"routine_id": rid})
        assert not r_get.is_error
        assert r_get.structured_content["exercises"][0]["note"] == "Lock out shoulders"

        # log_session writes note
        r_log = await client.call_tool(
            "log_session",
            {
                "date": "2026-10-10",
                "exercises": [
                    {
                        "exercise_id": "press",
                        "sets": [{"reps": 8, "weight_kg": 50}],
                        "note": "Felt smooth",
                    }
                ],
            },
        )
        assert not r_log.is_error
        w = fake_og.tokens["tok_PAIRALIC"]["state"]["workouts"][-1]
        assert w["entries"][0]["note"] == "Felt smooth"


async def test_delete_planned_rest_override_and_gc_orphans(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        st = fake_og.tokens["tok_PAIRALIC"]["state"]

        # 1. Preserves 'rest' override
        st["dayPlan"]["2026-10-28"] = "rest"
        del_rest = await client.call_tool("delete_planned", {"date": "2026-10-28"})
        assert not del_rest.is_error
        assert del_rest.structured_content["status"] == "unchanged"
        assert st["dayPlan"]["2026-10-28"] == "rest"

        # 2. Deletes planned routine and GC's it
        await client.call_tool(
            "plan_session",
            {
                "date": "2026-10-29",
                "name": "To Delete",
                "exercises": [{"exercise_id": "row", "sets": 3, "reps": 10, "weight_kg": 60}],
            },
        )
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        rid = st["dayPlan"]["2026-10-29"]
        assert any(r["id"] == rid for r in st["routines"])

        del_ok = await client.call_tool("delete_planned", {"date": "2026-10-29"})
        assert not del_ok.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        assert "2026-10-29" not in st["dayPlan"]
        # Garbage-collected because fitPlanned and unreferenced
        assert not any(r["id"] == rid for r in st["routines"])

        # 3. User's routine is never GC'd
        st["routines"].append({"id": "user_r", "name": "Keep me", "ex": []})
        st["dayPlan"]["2026-10-30"] = "user_r"
        del_user = await client.call_tool("delete_planned", {"date": "2026-10-30"})
        assert not del_user.is_error
        st = fake_og.tokens["tok_PAIRALIC"]["state"]
        assert any(r["id"] == "user_r" for r in st["routines"])


async def test_token_renewal_after_7_days(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        link = store.get_link("alice")
        assert link is not None

        # Manually age the linked_at timestamp back 8 days
        old_time = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
        with store._session() as session:
            from health_coach.fit.store import Link

            row = session.get(Link, "alice")
            assert row is not None
            row.linked_at = old_time
            row.renewed_at = None
            session.commit()

        # Set renewal token in fake_og
        fake_og.renew_on_me["tok_PAIRALIC"] = "tok_RENEWED"

        # Calling any tool triggers /api/me renewal
        acc = await client.call_tool("get_account", {})
        assert not acc.is_error

        # Verify store has the new token and renewed_at updated
        updated_link = store.get_link("alice")
        assert updated_link is not None
        assert updated_link.token == "tok_RENEWED"
        assert updated_link.renewed_at is not None
        assert (dt.datetime.now(dt.UTC) - updated_link.renewed_at).total_seconds() < 60


async def test_get_planned_mirrors_effective_routine_ids(
    fit_env: tuple[FitSettings, FitStore], fake_og: FakeOpenGym
) -> None:
    settings, store = fit_env
    server = create_fit_server(settings, with_auth=False, store=store)
    current_subject_var.set("alice")

    async with Client(server) as client:
        await client.call_tool("link_opengym", {"code": "PAIRALIC"})
        st = fake_og.tokens["tok_PAIRALIC"]["state"]

        st["routines"].extend(
            [
                {"id": "r_a", "name": "Routine A", "ex": [{"id": "ex1", "sets": 3}]},
                {"id": "r_b", "name": "Routine B", "ex": [{"id": "ex2", "sets": 4}]},
            ]
        )

        # Multi-routine week: Monday has [r_a, r_b]
        st["week"]["1"] = ["r_a", "r_b"]

        res = await client.call_tool("get_planned", {"days": 7})
        assert not res.is_error
        sched = res.structured_content["schedule"]

        # Find Monday
        monday = next(d for d in sched if d["weekday"] == "Monday")
        assert len(monday["routines"]) == 2
        assert [r["routine_id"] for r in monday["routines"]] == ["r_a", "r_b"]
