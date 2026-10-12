"""Daily data-quality check: stale or failing syncs and logging gaps go to the phone."""

import logging

from sqlalchemy import Engine

from health_coach.mcp_server import quality
from health_coach.notify.ntfy import NtfyClient

log = logging.getLogger(__name__)


def collect(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return quality.sync_warnings(conn) + quality.logging_warnings(conn)


def check_and_notify(engine: Engine, notifier: NtfyClient | None = None) -> list[str]:
    warnings = collect(engine)
    if warnings:
        log.warning("data quality: %s", warnings)
        (notifier or NtfyClient()).send(
            "Data check",
            "\n".join(f"- {w}" for w in warnings),
            priority=3,
            tags=["warning"],
        )
    return warnings
