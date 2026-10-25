"""Starlette web application for healthstats PWA.

Runs behind a forward-auth reverse proxy; enforces defence-in-depth header check
on all /api/* routes when HC_WEB_ALLOWED_USERS is non-empty. Connects to the database
with Role.ro only. Serves static files and client-side routing fallback.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from health_coach import __version__
from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server.common import jsonable
from health_coach.web import queries

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebAuthMiddleware(BaseHTTPMiddleware):
    """Enforce defence-in-depth username header on /api/* routes."""

    def __init__(self, app: Any, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Check /api/* routes
        if path.startswith("/api/"):
            allowed_users = self.settings.web_allowed_users
            if allowed_users:
                user = request.headers.get(self.settings.web_user_header)
                if not user or user not in allowed_users:
                    log.warning(
                        "Web API forbidden: user %r not in allowed users %r",
                        user,
                        allowed_users,
                    )
                    return JSONResponse(
                        {"error": "forbidden", "message": "User not authorized"},
                        status_code=403,
                        headers={"Cache-Control": "no-store"},
                    )

            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        # Non-API routes
        return await call_next(request)


# -----------------------------------------------------------------------------
# Input Validation Helpers
# -----------------------------------------------------------------------------


def _bad_request(detail: str) -> JSONResponse:
    return JSONResponse(
        {"error": "bad_request", "detail": detail},
        status_code=400,
        headers={"Cache-Control": "no-store"},
    )


def _parse_date(param: str | None) -> str | None:
    if not param:
        return None
    parts = param.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError(f"Invalid date {param!r}, expected YYYY-MM-DD")
    try:
        dt.date.fromisoformat(param)
    except ValueError as e:
        raise ValueError(f"Invalid date {param!r}, expected YYYY-MM-DD") from e
    return param


def _parse_month(param: str | None) -> str | None:
    if not param:
        return None
    parts = param.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError(f"Invalid month {param!r}, expected YYYY-MM")
    try:
        y = int(parts[0])
        m = int(parts[1])
        if not (1 <= m <= 12):
            raise ValueError(f"Month out of range (1..12): {m}")
        dt.date(y, m, 1)
    except ValueError as e:
        raise ValueError(f"Invalid month {param!r}, expected YYYY-MM") from e
    return param


def _parse_days(param: str | None, default: int, min_val: int = 7, max_val: int = 365) -> int:
    if not param:
        return default
    try:
        val = int(param)
    except ValueError as e:
        raise ValueError(f"Invalid days {param!r}, expected integer") from e
    return max(min_val, min(max_val, val))


# -----------------------------------------------------------------------------
# API Route Handlers (Synchronous so Starlette runs them in its threadpool)
# -----------------------------------------------------------------------------


def api_day(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_day(conn, date_param)
    return JSONResponse(jsonable(data))


def api_recovery(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
        days = _parse_days(request.query_params.get("days"), default=30)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_recovery(conn, date_param, days=days)
    return JSONResponse(jsonable(data))


def api_sleep(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_sleep(conn, date_param)
    return JSONResponse(jsonable(data))


def api_strain(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_strain(conn, date_param)
    return JSONResponse(jsonable(data))


def api_nutrition(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_nutrition(conn, date_param)
    return JSONResponse(jsonable(data))


def api_trends(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    days_param = request.query_params.get("days", "30")
    try:
        days = int(days_param)
    except ValueError:
        return _bad_request(f"Invalid days {days_param!r}, expected 7, 30, or 90")
    if days not in (7, 30, 90):
        return _bad_request(f"Invalid days {days}, expected 7, 30, or 90")
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_trends(conn, date_param, days=days)
    return JSONResponse(jsonable(data))


def api_calendar(request: Request) -> Response:
    try:
        month_param = _parse_month(request.query_params.get("month"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_calendar(conn, month_param)
    return JSONResponse(jsonable(data))


def api_journal(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
        days = _parse_days(request.query_params.get("days"), default=60)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_journal(conn, days=days, date_str=date_param)
    return JSONResponse(jsonable(data))


def api_report(request: Request) -> Response:
    period_param = request.query_params.get("period", "week")
    if period_param not in ("week", "month"):
        return _bad_request(f"Invalid period {period_param!r}, expected 'week' or 'month'")
    try:
        end_param = _parse_date(request.query_params.get("end"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_report(conn, period=period_param, end_str=end_param)
    return JSONResponse(jsonable(data))


def healthz(request: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


# -----------------------------------------------------------------------------
# Static and SPA Fallback Handler
# -----------------------------------------------------------------------------


async def spa_and_static_handler(request: Request) -> Response:
    """Serve static files or fall back to index.html for client-side routing."""
    rel_path = request.path_params.get("path", "").lstrip("/")

    if rel_path:
        # Prevent path traversal
        file_path = (STATIC_DIR / rel_path).resolve()
        if file_path.is_file() and file_path.is_relative_to(STATIC_DIR.resolve()):
            # Caching policy
            headers: dict[str, str] = {}
            if "/assets/" in file_path.as_posix():
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif file_path.name in ("sw.js", "index.html", "manifest.webmanifest"):
                headers["Cache-Control"] = "no-cache"
            return FileResponse(file_path, headers=headers)

    # Fallback to index.html
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})

    # Stub when static hasn't been built yet
    return HTMLResponse(
        "<!doctype html><html><head><title>Healthstats</title></head>"
        "<body style='background:#0B0D10;color:#F2F4F7;font-family:sans-serif;padding:32px;'>"
        "<h1>Healthstats PWA</h1>"
        "<p>Static build not found. Run <code>npm run build</code> in <code>web/</code>.</p>"
        "</body></html>",
        status_code=200,
        headers={"Cache-Control": "no-cache"},
    )


def create_app(settings: Settings | None = None) -> Starlette:
    app_settings = settings or get_settings()

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/api/day", api_day, methods=["GET"]),
        Route("/api/recovery", api_recovery, methods=["GET"]),
        Route("/api/sleep", api_sleep, methods=["GET"]),
        Route("/api/strain", api_strain, methods=["GET"]),
        Route("/api/nutrition", api_nutrition, methods=["GET"]),
        Route("/api/trends", api_trends, methods=["GET"]),
        Route("/api/calendar", api_calendar, methods=["GET"]),
        Route("/api/journal", api_journal, methods=["GET"]),
        Route("/api/report", api_report, methods=["GET"]),
        # Catch-all for static assets and SPA routes
        Route("/{path:path}", spa_and_static_handler, methods=["GET"]),
    ]

    middleware = [
        Middleware(WebAuthMiddleware, settings=app_settings),
    ]

    return Starlette(routes=routes, middleware=middleware)


def run(settings: Settings | None = None) -> None:
    app_settings = settings or get_settings()
    logging.getLogger().setLevel(app_settings.log_level)
    app = create_app(app_settings)
    uvicorn.run(
        app,
        host=app_settings.web_host,
        port=app_settings.web_port,
        log_level=app_settings.log_level.lower(),
    )
