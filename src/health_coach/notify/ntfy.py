"""ntfy push notification client."""

import logging
from typing import Any

import httpx

from health_coach.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0

_custom_client: httpx.Client | None = None


class NotifyError(RuntimeError):
    pass


def set_client(client: httpx.Client | None) -> None:
    """Set or reset an injected httpx client (e.g. for testing with MockTransport)."""
    global _custom_client
    _custom_client = client


class NtfyClient:
    def __init__(
        self,
        url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.url = (url or settings.ntfy_url).rstrip("/")
        self.timeout = timeout
        self._injected_client = client

    def _get_client(self) -> httpx.Client:
        if self._injected_client is not None:
            return self._injected_client
        if _custom_client is not None:
            return _custom_client
        return httpx.Client(timeout=self.timeout)

    def send(
        self,
        title: str,
        body: str,
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.ntfy_topic or not settings.ntfy_topic.get_secret_value():
            raise NotifyError("notifications are not configured (HC_NTFY_TOPIC)")

        # JSON publishing to the server root: headers would have to be latin-1, and
        # titles may be in any language.
        payload: dict[str, Any] = {
            "topic": settings.ntfy_topic.get_secret_value(),
            "title": title,
            "message": body,
            "priority": priority,
        }
        if tags:
            payload["tags"] = tags

        headers = {}
        if settings.ntfy_token and settings.ntfy_token.get_secret_value():
            headers["Authorization"] = f"Bearer {settings.ntfy_token.get_secret_value()}"

        client = self._get_client()
        should_close = client is not self._injected_client and client is not _custom_client
        try:
            resp = client.post(self.url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotifyError(f"ntfy notification failed: {exc}") from exc
        finally:
            if should_close:
                client.close()


def send_notification(
    title: str,
    body: str,
    priority: int = 3,
    tags: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    ntfy = NtfyClient(client=client)
    ntfy.send(title=title, body=body, priority=priority, tags=tags)
    return {"sent": True, "title": title}
