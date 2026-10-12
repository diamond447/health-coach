"""Group 2: free-form read-only SQL."""

import json
import time
from collections.abc import Sequence
from typing import Annotated, Any, cast

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from health_coach.db.engine import Role, get_engine
from health_coach.mcp_server.common import DATA_NOTE, READ, audited, jsonable
from health_coach.mcp_server.sql_guard import SqlRejected, check_sql

DEFAULT_ROWS = 200
MAX_ROWS = 2000
TIMEOUT_MS = 5000
MAX_CELL_CHARS = 2000
MAX_RESULT_BYTES = 200_000


def query_sql(
    sql: Annotated[str, Field(description="One SELECT or WITH ... SELECT statement (PostgreSQL).")],
    max_rows: Annotated[int, Field(ge=1, le=MAX_ROWS)] = DEFAULT_ROWS,
) -> dict[str, Any]:
    """Run a read-only SQL query against the health database.

    Use it for anything the analytics tools do not cover. Prefer the v_* views
    (call get_schema first). Only one SELECT/WITH statement; 5 s timeout; secrets,
    raw payloads and the audit log are not readable. Aggregate in SQL instead of
    pulling many rows.
    """
    try:
        statement = check_sql(sql)
    except SqlRejected as exc:
        raise ToolError(f"query rejected: {exc}") from exc

    started = time.monotonic()
    # A named (server-side) cursor streams rows, so a huge result never lands in this
    # process; only max_rows + 1 rows are fetched. No parameters are passed, so a % in
    # the query is not a placeholder.
    with get_engine(Role.ro).connect() as conn:
        raw = cast("psycopg.Connection[Any]", conn.connection.dbapi_connection)
        setup = raw.cursor()
        try:
            setup.execute("SET TRANSACTION READ ONLY")
            setup.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            with raw.cursor(name="hc_query_sql") as cur:
                cur.execute(statement)
                columns = [d[0] for d in cur.description or []]
                rows = cur.fetchmany(max_rows + 1)
        except psycopg.Error as exc:
            message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise ToolError(f"query failed: {message}") from exc
        finally:
            raw.rollback()
            # Session-level advisory locks survive a rollback; never leave one on a
            # pooled connection.
            setup.execute("SELECT pg_advisory_unlock_all()")
            raw.rollback()
            setup.close()

    out_rows, truncated = _bounded(rows, max_rows)
    return {
        "columns": columns,
        "rows": out_rows,
        "truncated": truncated,
        "execution_ms": int((time.monotonic() - started) * 1000),
        "note": DATA_NOTE,
    }


def _cell(value: object) -> object:
    v = jsonable(value)
    if isinstance(v, str) and len(v) > MAX_CELL_CHARS:
        return v[:MAX_CELL_CHARS] + " ...[truncated]"
    return v


def _bounded(rows: Sequence[Sequence[object]], max_rows: int) -> tuple[list[list[object]], bool]:
    """Rows as JSON values, capped by row count, cell length and total size."""
    out: list[list[object]] = []
    size = 0
    for row in rows[:max_rows]:
        cells = [_cell(v) for v in row]
        size += len(json.dumps(cells, default=str))
        if size > MAX_RESULT_BYTES:
            return out, True
        out.append(cells)
    return out, len(rows) > max_rows


def register(server: MCPServer) -> None:
    server.tool(annotations=READ)(audited(query_sql))
