"""Tests for the ntfy client."""

import httpx
import pytest
from pydantic import SecretStr

from health_coach.config import get_settings
from health_coach.notify.ntfy import NtfyClient


def _capture() -> tuple[httpx.Client, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"id": "ntfy-1"})

    return httpx.Client(transport=httpx.MockTransport(handler)), sent


def test_sends_bearer_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ntfy_topic", SecretStr("topic"))
    monkeypatch.setattr(get_settings(), "ntfy_token", SecretStr("tk_test"))
    client, sent = _capture()

    NtfyClient(url="https://ntfy.example.com", client=client).send(title="t", body="b")

    assert sent[0].headers["Authorization"] == "Bearer tk_test"


@pytest.mark.parametrize("token", [None, SecretStr("")])
def test_no_auth_header_without_token(
    monkeypatch: pytest.MonkeyPatch, token: SecretStr | None
) -> None:
    monkeypatch.setattr(get_settings(), "ntfy_topic", SecretStr("topic"))
    monkeypatch.setattr(get_settings(), "ntfy_token", token)
    client, sent = _capture()

    NtfyClient(url="https://ntfy.example.com", client=client).send(title="t", body="b")

    assert "Authorization" not in sent[0].headers
