"""sync_state bookkeeping shared by all ingest jobs."""

import datetime as dt

from sqlalchemy import Connection, text

_UPSERT_SUCCESS = """
INSERT INTO sync_state (source, data_type, last_success_at, last_attempt_at, cursor,
                        last_error, error_count)
VALUES (:source, :data_type, :now, :now, :cursor, NULL, 0)
ON CONFLICT (source, data_type) DO UPDATE SET
    last_success_at = EXCLUDED.last_success_at,
    last_attempt_at = EXCLUDED.last_attempt_at,
    cursor = coalesce(EXCLUDED.cursor, sync_state.cursor),
    last_error = NULL,
    error_count = 0,
    updated_at = now()
"""

_UPSERT_FAILURE = """
INSERT INTO sync_state (source, data_type, last_attempt_at, last_error, error_count)
VALUES (:source, :data_type, :now, :error, 1)
ON CONFLICT (source, data_type) DO UPDATE SET
    last_attempt_at = EXCLUDED.last_attempt_at,
    last_error = EXCLUDED.last_error,
    error_count = sync_state.error_count + 1,
    updated_at = now()
RETURNING error_count
"""


def last_success(conn: Connection, source: str, data_type: str) -> dt.datetime | None:
    value: dt.datetime | None = conn.execute(
        text("SELECT last_success_at FROM sync_state WHERE source = :s AND data_type = :t"),
        {"s": source, "t": data_type},
    ).scalar()
    return value


def mark_success(conn: Connection, source: str, data_type: str, cursor: str | None = None) -> None:
    conn.execute(
        text(_UPSERT_SUCCESS),
        {
            "source": source,
            "data_type": data_type,
            "now": dt.datetime.now(dt.UTC),
            "cursor": cursor,
        },
    )


def mark_failure(conn: Connection, source: str, data_type: str, error: str) -> int:
    """Record a failed run; returns the number of consecutive failures."""
    count: int = conn.execute(
        text(_UPSERT_FAILURE),
        {
            "source": source,
            "data_type": data_type,
            "now": dt.datetime.now(dt.UTC),
            "error": error[:1000],
        },
    ).scalar_one()
    return count
