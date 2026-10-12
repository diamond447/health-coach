"""Nightly derived metrics: 21-day TDEE estimate snapshot and mcp_audit cleanup."""

import datetime as dt
import logging

from sqlalchemy import Engine, text

from health_coach.analytics.tdee import estimate_from_db
from health_coach.ingest import state
from health_coach.mcp_server.common import rnd

log = logging.getLogger(__name__)

WINDOW_DAYS = 21
AUDIT_RETENTION_DAYS = 180

_UPSERT_TDEE = """
INSERT INTO tdee_estimates (
    local_date, window_days, avg_intake, trend_change_kg, tdee,
    confidence, logged_days, weigh_ins, source
) VALUES (
    :local_date, :window_days, :avg_intake, :trend_change_kg, :tdee,
    :confidence, :logged_days, :weigh_ins, 'worker'
) ON CONFLICT (local_date, window_days) DO UPDATE SET
    avg_intake = EXCLUDED.avg_intake,
    trend_change_kg = EXCLUDED.trend_change_kg,
    tdee = EXCLUDED.tdee,
    confidence = EXCLUDED.confidence,
    logged_days = EXCLUDED.logged_days,
    weigh_ins = EXCLUDED.weigh_ins,
    updated_at = now()
"""

_DELETE_AUDIT = """
DELETE FROM mcp_audit WHERE ts < :cutoff
"""


def snapshot_tdee(engine: Engine, day: dt.date) -> None:
    """Compute and store the 21-day TDEE estimate for `day`, and purge old audit logs.

    Writes to tdee_estimates (upsert on local_date, window_days), deletes mcp_audit rows
    older than 180 days, and marks success in sync_state for worker/derived.
    """
    with engine.begin() as conn:
        res, _, _ = estimate_from_db(conn, day, WINDOW_DAYS)
        conn.execute(
            text(_UPSERT_TDEE),
            {
                "local_date": day,
                "window_days": WINDOW_DAYS,
                "avg_intake": rnd(res.avg_intake, 10),
                "trend_change_kg": res.trend_change_kg,
                "tdee": rnd(res.tdee, 10),
                "confidence": res.confidence,
                "logged_days": res.logged_days,
                "weigh_ins": res.weigh_ins,
            },
        )

        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=AUDIT_RETENTION_DAYS)
        deleted = conn.execute(text(_DELETE_AUDIT), {"cutoff": cutoff}).rowcount
        log.info("derived: purged %d mcp_audit rows older than %s", deleted, cutoff)

        state.mark_success(conn, "worker", "derived")
