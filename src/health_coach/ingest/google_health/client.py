"""HTTP access to the Google Health API v4 (discovery revision 20261007).

Request shapes and parameters:
- List filters are prefixed with the snake_case data type name and use civil-time expressions.
- Page size is capped at 25 for session types (exercise, sleep), 10000 otherwise.
- dailyRollUp requests use CivilTimeInterval with date boundaries.
"""

import datetime as dt
from typing import Any, Protocol

import httpx
from sqlalchemy import Engine

from health_coach.config import Settings
from health_coach.ingest.google_health import oauth
from health_coach.ingest.google_health.datatypes import DataTypeSpec, Method
from health_coach.ingest.http import retrying

MAX_PAGES = 50


def _page_size(spec: DataTypeSpec) -> int:
    return 25 if spec.name in ("exercise", "sleep") else 10000


def _filter_expr(spec: DataTypeSpec, start: dt.date, end: dt.date) -> str:
    """Civil-time filter expression following Google Health API v4."""
    name_snake = spec.name.replace("-", "_")
    s_str = start.isoformat()
    e_str = end.isoformat()
    if spec.name.startswith("daily-"):
        return f'{name_snake}.date >= "{s_str}" AND {name_snake}.date < "{e_str}"'
    if spec.name == "sleep":
        return (
            f'sleep.interval.civil_end_time >= "{s_str}" AND '
            f'sleep.interval.civil_end_time < "{e_str}"'
        )
    if spec.name in ("exercise", "nutrition-log"):
        return (
            f'{name_snake}.interval.civil_start_time >= "{s_str}" AND '
            f'{name_snake}.interval.civil_start_time < "{e_str}"'
        )
    if spec.name in ("weight", "body-fat", "heart-rate"):
        return (
            f'{name_snake}.sample_time.civil_time >= "{s_str}" AND '
            f'{name_snake}.sample_time.civil_time < "{e_str}"'
        )
    return (
        f'{name_snake}.interval.civil_start_time >= "{s_str}" AND '
        f'{name_snake}.interval.civil_start_time < "{e_str}"'
    )


class Fetcher(Protocol):
    def fetch(self, spec: DataTypeSpec, start: dt.date, end: dt.date) -> dict[str, Any]:
        """Raw response for [start, end) (local civil dates), all pages merged."""
        ...


class GoogleHealthClient:
    def __init__(
        self, engine: Engine, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._transport = transport
        self._http = httpx.Client(
            base_url=settings.google_api_base, timeout=30, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GoogleHealthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        token = oauth.access_token(self._engine, self._settings, self._transport)
        return {"Authorization": f"Bearer {token}"}

    @retrying
    def _send(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401:
            # Token revoked between refresh and use: retried once with a fresh token.
            response = self._http.request(method, url, headers=self._headers(), **kwargs)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def _path(self, spec: DataTypeSpec) -> str:
        return f"/users/me/dataTypes/{spec.name}/dataPoints"

    def fetch(self, spec: DataTypeSpec, start: dt.date, end: dt.date) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            if spec.method is Method.daily_roll_up:
                body: dict[str, Any] = {
                    "range": {"start": _civil(start), "end": _civil(end)},
                    "windowSizeDays": 1,
                    "pageSize": _page_size(spec),
                }
                if token:
                    body["pageToken"] = token
                page = self._send("POST", f"{self._path(spec)}:dailyRollUp", json=body)
            else:
                params: dict[str, Any] = {
                    "pageSize": _page_size(spec),
                    "filter": _filter_expr(spec, start, end),
                }
                if token:
                    params["pageToken"] = token
                page = self._send("GET", self._path(spec), params=params)
            pages.append(page)
            token = page.get("nextPageToken")
            if not token:
                break
        return {"pages": pages}


def _civil(day: dt.date) -> dict[str, Any]:
    return {"date": {"year": day.year, "month": day.month, "day": day.day}}
