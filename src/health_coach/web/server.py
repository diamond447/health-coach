"""Starlette web application for healthstats PWA.

Runs behind a forward-auth reverse proxy; enforces defence-in-depth header check
on all /api/* routes when HC_WEB_ALLOWED_USERS is non-empty. Connects to the database
with Role.ro, plus Role.web_journal for journal entry writes. Serves static files and
client-side routing fallback.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.parse
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import uvicorn
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from health_coach import __version__
from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.journal import BEHAVIOR_RE
from health_coach.mcp_server.common import jsonable, today
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


def _check_csrf(request: Request) -> JSONResponse | None:
    # 1. Custom header check on both PUT and DELETE
    if request.headers.get("x-healthstats") != "1":
        return JSONResponse(
            {"error": "forbidden", "detail": "Missing or invalid X-Healthstats header"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    # 2. Content-Type check for PUT
    if request.method == "PUT":
        ct = request.headers.get("content-type", "")
        media_type = ct.split(";")[0].strip().lower()
        if media_type != "application/json":
            return JSONResponse(
                {"error": "forbidden", "detail": "Content-Type must be application/json"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

    # 3. Origin / Referer check
    raw_host = (
        request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        or request.headers.get("host")
        or ""
    ).lower()

    if not raw_host:
        return JSONResponse(
            {"error": "forbidden", "detail": "Missing host header"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    origin = request.headers.get("origin")
    source_url = origin if origin is not None else request.headers.get("referer")
    if not source_url:
        return JSONResponse(
            {"error": "forbidden", "detail": "Missing Origin and Referer headers"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    try:
        source_host = (
            (
                urllib.parse.urlsplit(source_url).netloc
                or urllib.parse.urlsplit("//" + source_url).netloc
            )
            .strip()
            .lower()
        )
    except Exception:
        return JSONResponse(
            {"error": "forbidden", "detail": "Invalid Origin or Referer header"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    if not source_host or source_host != raw_host:
        return JSONResponse(
            {"error": "forbidden", "detail": "Origin or Referer does not match Host"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    return None


def _validate_journal_date(date_str: Any) -> dt.date:
    if not date_str or not isinstance(date_str, str):
        raise ValueError("Field 'date' is required and must be a string YYYY-MM-DD")
    parts = date_str.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError(f"Invalid date {date_str!r}, expected YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(date_str)
    except ValueError as e:
        raise ValueError(f"Invalid date {date_str!r}, expected YYYY-MM-DD") from e
    today_val = today()
    if parsed > today_val:
        raise ValueError("Date cannot be in the future")
    if parsed < today_val - dt.timedelta(days=14):
        raise ValueError("Date cannot be older than 14 days")
    return parsed


def _validate_journal_behavior(behavior_str: Any) -> str:
    if not behavior_str or not isinstance(behavior_str, str):
        raise ValueError("Field 'behavior' is required and must be a string")
    b = behavior_str.strip()
    if not BEHAVIOR_RE.match(b):
        raise ValueError(f"Invalid behavior key {b!r}: must match ^[a-z][a-z0-9_]{{1,39}}$")
    return b


def _validate_journal_amount(amount_val: Any) -> Decimal | None:
    if amount_val is None:
        return None
    if isinstance(amount_val, bool) or not isinstance(amount_val, (int, float, Decimal, str)):
        raise ValueError("Amount must be a number between 0 and 9999.99 or null")
    try:
        amt = Decimal(str(amount_val))
    except (InvalidOperation, ValueError) as e:
        raise ValueError("Amount must be a valid number") from e
    if amt < Decimal("0") or amt > Decimal("9999.99"):
        raise ValueError("Amount must be between 0 and 9999.99")
    return amt


def _validate_journal_note(note_val: Any) -> str | None:
    if note_val is None:
        return None
    if not isinstance(note_val, str):
        raise ValueError("Note must be a string or null")
    n = note_val.strip()
    if len(n) > 200:
        raise ValueError("Note cannot exceed 200 characters")
    return n or None


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
        days = _parse_days(request.query_params.get("days"), default=30)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_sleep(conn, date_param, days=days)
    return JSONResponse(jsonable(data))


def api_strain(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
        days = _parse_days(request.query_params.get("days"), default=30)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_strain(conn, date_param, days=days)
    return JSONResponse(jsonable(data))


def api_activity(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
        days = _parse_days(request.query_params.get("days"), default=30, min_val=7, max_val=90)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_activity(conn, date_param, days=days)
    return JSONResponse(jsonable(data))


def api_night(request: Request) -> Response:
    try:
        date_param = _parse_date(request.query_params.get("date"))
        days = _parse_days(request.query_params.get("days"), default=30, min_val=7, max_val=90)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_night(conn, date_param, days=days)
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
        date_param = _parse_date(
            request.query_params.get("end") or request.query_params.get("date")
        )
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
    settings = getattr(request.app.state, "settings", None) or get_settings()
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_journal(
            conn,
            days=days,
            date_str=date_param,
            can_write=settings.web_journal_database_url is not None,
        )
    return JSONResponse(jsonable(data))


async def api_journal_entries(request: Request) -> Response:
    csrf_error = _check_csrf(request)
    if csrf_error:
        return csrf_error

    settings = getattr(request.app.state, "settings", None) or get_settings()
    if settings.web_journal_database_url is None:
        return JSONResponse(
            {"error": "journal_writes_disabled"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    if request.method == "PUT":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 2048:
                    return _bad_request("Body size exceeds 2 kB")
            except ValueError:
                return _bad_request("Invalid Content-Length header")

        body_bytes = await request.body()
        if len(body_bytes) > 2048:
            return _bad_request("Body size exceeds 2 kB")

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            return _bad_request("Malformed JSON body")

        if not isinstance(payload, dict):
            return _bad_request("JSON body must be an object")

        try:
            entry_date = _validate_journal_date(payload.get("date"))
            behavior = _validate_journal_behavior(payload.get("behavior"))
            amount = _validate_journal_amount(payload.get("amount"))
            note = _validate_journal_note(payload.get("note"))
        except ValueError as e:
            return _bad_request(str(e))

        def _do_write() -> dict[str, Any]:
            with get_engine(Role.web_journal).begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO journal_entries (local_date, behavior, amount, note, source) "
                        "VALUES (:d, :b, :amt, :note, 'web') "
                        "ON CONFLICT (local_date, behavior) WHERE deleted_at IS NULL DO UPDATE SET "
                        "amount = EXCLUDED.amount, "
                        # The app has no note field: keep a note the coach wrote.
                        "note = COALESCE(EXCLUDED.note, journal_entries.note), "
                        "updated_at = now()"
                    ),
                    {"d": entry_date, "b": behavior, "amt": amount, "note": note},
                )
            screen_date = entry_date + dt.timedelta(days=1)
            with get_engine(Role.ro).connect() as conn:
                return queries.query_journal(conn, days=60, date_str=screen_date.isoformat())

        data = await run_in_threadpool(_do_write)
        return JSONResponse(jsonable(data), headers={"Cache-Control": "no-store"})

    elif request.method == "DELETE":
        date_param = request.query_params.get("date")
        behavior_param = request.query_params.get("behavior")

        try:
            entry_date = _validate_journal_date(date_param)
            behavior = _validate_journal_behavior(behavior_param)
        except ValueError as e:
            return _bad_request(str(e))

        def _do_delete() -> bool:
            with get_engine(Role.web_journal).begin() as conn:
                res = conn.execute(
                    text(
                        "UPDATE journal_entries SET deleted_at = now(), updated_at = now() "
                        "WHERE local_date = :d AND behavior = :b AND deleted_at IS NULL "
                        "RETURNING id"
                    ),
                    {"d": entry_date, "b": behavior},
                ).first()
                return res is not None

        found = await run_in_threadpool(_do_delete)
        if not found:
            return JSONResponse(
                {"error": "not_found", "detail": "Active journal entry not found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )

        return JSONResponse(
            {"deleted": True, "date": entry_date.isoformat(), "behavior": behavior},
            headers={"Cache-Control": "no-store"},
        )

    return Response(status_code=405, headers={"Cache-Control": "no-store"})


def api_report(request: Request) -> Response:
    period_param = request.query_params.get("period", "week")
    if period_param not in ("week", "month"):
        return _bad_request(f"Invalid period {period_param!r}, expected 'week' or 'month'")
    try:
        end_param = _parse_date(request.query_params.get("end") or request.query_params.get("date"))
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_report(conn, period=period_param, end_str=end_param)
    return JSONResponse(jsonable(data))


def api_healthspan(request: Request) -> Response:
    try:
        weeks = _parse_days(request.query_params.get("weeks"), default=26, min_val=1, max_val=52)
    except ValueError as e:
        return _bad_request(str(e))
    with get_engine(Role.ro).connect() as conn:
        data = queries.query_healthspan(conn, weeks=weeks)
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
        Route("/api/activity", api_activity, methods=["GET"]),
        Route("/api/night", api_night, methods=["GET"]),
        Route("/api/sleep", api_sleep, methods=["GET"]),
        Route("/api/strain", api_strain, methods=["GET"]),
        Route("/api/nutrition", api_nutrition, methods=["GET"]),
        Route("/api/trends", api_trends, methods=["GET"]),
        Route("/api/calendar", api_calendar, methods=["GET"]),
        Route("/api/journal", api_journal, methods=["GET"]),
        Route("/api/journal/entries", api_journal_entries, methods=["PUT", "DELETE"]),
        Route("/api/report", api_report, methods=["GET"]),
        Route("/api/healthspan", api_healthspan, methods=["GET"]),
        # Catch-all for static assets and SPA routes
        Route("/{path:path}", spa_and_static_handler, methods=["GET"]),
    ]

    middleware = [
        Middleware(WebAuthMiddleware, settings=app_settings),
    ]

    app = Starlette(routes=routes, middleware=middleware)
    app.state.settings = app_settings
    return app


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
