"""openGym REST client (see docs/opengym.md)."""

import copy
import logging
from collections.abc import Callable
from typing import Any

import httpx

from health_coach.config import Settings, get_settings
from health_coach.ingest.http import retrying

log = logging.getLogger(__name__)


class OpenGymError(RuntimeError):
    """Base error for openGym client operations."""


class OpenGymAuthError(OpenGymError):
    """Authentication or pairing failure."""


class OpenGymConflictError(OpenGymError):
    """Revision conflict on conditional state write (HTTP 409)."""

    def __init__(
        self,
        message: str,
        state: dict[str, Any] | None = None,
        rev: int | None = None,
    ) -> None:
        super().__init__(message)
        self.state = state
        self.rev = rev


class OpenGymClient:
    """HTTP client for openGym instance."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, new_token: str | None) -> None:
        self._token = new_token
        if new_token:
            self._http.headers["Authorization"] = f"Bearer {new_token}"
        else:
            self._http.headers.pop("Authorization", None)

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, token: str | None = None
    ) -> "OpenGymClient":
        settings = settings or get_settings()
        if not settings.opengym_url:
            raise OpenGymError("openGym is not configured (HC_OPENGYM_URL)")
        return cls(settings.opengym_url, token=token)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenGymClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            if method.upper() == "PUT":
                return self._request_direct(method, path, **kwargs)
            return self._request_retrying(method, path, **kwargs)
        except httpx.HTTPStatusError as exc:
            raise OpenGymError(
                f"{method} {path}: {exc.response.status_code} {exc.response.text[:300]}"
            ) from exc
        except httpx.TransportError as exc:
            raise OpenGymError(f"{method} {path} transport error: {exc}") from exc

    @retrying
    def _request_retrying(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request_direct(method, path, **kwargs)

    def _request_direct(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._http.request(method, path, **kwargs)
        if response.status_code == 401:
            raise OpenGymAuthError(f"{method} {path}: 401 Unauthorized")
        if response.status_code == 409:
            body = response.json() if response.content else {}
            raise OpenGymConflictError(
                f"{method} {path}: 409 Conflict",
                state=body.get("state") if isinstance(body, dict) else None,
                rev=body.get("rev") if isinstance(body, dict) else None,
            )
        if response.status_code >= 400 and response.status_code < 500:
            raise OpenGymError(f"{method} {path}: {response.status_code} {response.text[:300]}")
        response.raise_for_status()
        return response.json() if response.content else None

    def pair_redeem(self, code: str) -> dict[str, Any]:
        """Redeem a one-shot pairing code for an API bearer token."""
        result: dict[str, Any] = self._request(
            "POST", "/api/pair/redeem", json={"code": code.strip().upper()}
        )
        new_token = result.get("token")
        if new_token:
            self.token = new_token
        return result

    def me(self) -> dict[str, Any]:
        """Check session identity and receive renewed token if past half of session life."""
        result: dict[str, Any] = self._request("GET", "/api/me")
        new_token = result.get("token")
        if new_token:
            self.token = new_token
        return result

    def get_data(self) -> dict[str, Any]:
        """Fetch full user state and revision counter: {state, rev}."""
        result: dict[str, Any] = self._request("GET", "/api/data")
        return result

    def put_data(
        self,
        state: dict[str, Any],
        base_rev: int | None = None,
        base_wid: str | None = None,
    ) -> dict[str, Any]:
        """Conditional or unconditional state write.

        Does not send stamped=true so the server stamps additions/removals and tracks tombstones.
        Preserves all unknown fields in state.
        """
        payload: dict[str, Any] = {"state": state}
        if base_rev is not None:
            payload["baseRev"] = base_rev
        if base_wid is not None:
            payload["baseWid"] = base_wid
        result: dict[str, Any] = self._request("PUT", "/api/data", json=payload)
        return result

    def mutate(
        self,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Read state, apply pure function to deep copy, and PUT with CAS rev/wid check.

        Retries on HTTP 409 conflict up to max_attempts by re-applying fn to the returned document.
        """
        cur_doc: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            if cur_doc is None:
                cur_doc = self.get_data()

            state = cur_doc.get("state")
            if not isinstance(state, dict):
                state = {}
            base_rev = cur_doc.get("rev")
            base_wid = state.get("_wid") if isinstance(state, dict) else None

            new_state = fn(copy.deepcopy(state))

            try:
                return self.put_data(new_state, base_rev=base_rev, base_wid=base_wid)
            except OpenGymConflictError as err:
                if attempt >= max_attempts - 1:
                    raise
                if not isinstance(err.state, dict):
                    raise OpenGymConflictError(
                        f"Conflict response missing state dictionary: {err}"
                    ) from err
                cur_doc = {"state": err.state, "rev": err.rev}

        raise OpenGymConflictError("Exceeded maximum mutate attempts on state conflict")
