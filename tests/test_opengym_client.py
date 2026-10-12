"""Unit tests for OpenGymClient."""

import json
from typing import Any

import httpx
import pytest

from health_coach.opengym.client import (
    OpenGymAuthError,
    OpenGymClient,
    OpenGymConflictError,
    OpenGymError,
)


def test_pair_redeem_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/pair/redeem"
        data = json.loads(request.content)
        assert data == {"code": "ABCD1234"}
        return httpx.Response(
            200, json={"token": "test-token-123", "user": {"id": "u1", "name": "Athlete"}}
        )

    client = OpenGymClient("http://localhost:3000", transport=httpx.MockTransport(handler))
    res = client.pair_redeem("abcd1234")
    assert res["token"] == "test-token-123"
    assert client.token == "test-token-123"


def test_pair_redeem_invalid_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid or expired code"})

    client = OpenGymClient("http://localhost:3000", transport=httpx.MockTransport(handler))
    with pytest.raises(OpenGymError, match="400"):
        client.pair_redeem("badcode")


def test_me_and_token_renewal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer initial-token"
        return httpx.Response(
            200, json={"user": {"id": "u1", "name": "Athlete"}, "token": "renewed-token-456"}
        )

    client = OpenGymClient(
        "http://localhost:3000", token="initial-token", transport=httpx.MockTransport(handler)
    )
    res = client.me()
    assert res["token"] == "renewed-token-456"
    assert client.token == "renewed-token-456"


def test_me_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "not signed in"})

    client = OpenGymClient(
        "http://localhost:3000", token="expired-token", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(OpenGymAuthError):
        client.me()


def test_get_and_put_data() -> None:
    sample_state: dict[str, Any] = {"workouts": [], "routines": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/data":
            return httpx.Response(200, json={"state": sample_state, "rev": 5})
        if request.method == "PUT" and request.url.path == "/api/data":
            body = json.loads(request.content)
            assert body["baseRev"] == 5
            assert body["baseWid"] == "wid-1"
            return httpx.Response(200, json={"ok": True, "rev": 6, "wid": "wid-2"})
        return httpx.Response(404)

    client = OpenGymClient(
        "http://localhost:3000", token="tok", transport=httpx.MockTransport(handler)
    )
    doc = client.get_data()
    assert doc["rev"] == 5
    assert doc["state"] == sample_state

    put_res = client.put_data(sample_state, base_rev=5, base_wid="wid-1")
    assert put_res["ok"] is True
    assert put_res["rev"] == 6


def test_mutate_with_conflict_cas() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.method == "GET" and request.url.path == "/api/data":
            return httpx.Response(200, json={"state": {"counter": 1, "_wid": "w1"}, "rev": 1})
        if request.method == "PUT" and request.url.path == "/api/data":
            attempts += 1
            body = json.loads(request.content)
            if attempts == 1:
                # First attempt conflicts with concurrent write rev 2
                return httpx.Response(
                    409,
                    json={
                        "error": "conflict",
                        "rev": 2,
                        "state": {"counter": 10, "_wid": "w2"},
                    },
                )
            # Second attempt succeeds
            assert body["baseRev"] == 2
            assert body["baseWid"] == "w2"
            assert body["state"]["counter"] == 11
            return httpx.Response(200, json={"ok": True, "rev": 3, "wid": "w3"})
        return httpx.Response(404)

    client = OpenGymClient(
        "http://localhost:3000", token="tok", transport=httpx.MockTransport(handler)
    )

    def increment(s: dict[str, Any]) -> dict[str, Any]:
        s["counter"] = int(s.get("counter", 0)) + 1
        return s

    res = client.mutate(increment, max_attempts=3)
    assert res["ok"] is True
    assert res["rev"] == 3
    assert attempts == 2


def test_mutate_exceeds_max_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"state": {"_wid": "w1"}, "rev": 1})
        if request.method == "PUT":
            return httpx.Response(
                409, json={"error": "conflict", "rev": 2, "state": {"_wid": "w2"}}
            )
        return httpx.Response(404)

    client = OpenGymClient(
        "http://localhost:3000", token="tok", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(OpenGymConflictError):
        client.mutate(lambda s: s, max_attempts=3)
