"""Run one ingest job with sync_state bookkeeping and failure alerts."""

import logging
from collections.abc import Callable

from health_coach.db.engine import Role, get_engine
from health_coach.ingest import state

log = logging.getLogger(__name__)

ALERT_AFTER_FAILURES = 3

# Set by the scheduler once notifications are configured: alert(title, body).
alert: Callable[[str, str], None] | None = None


def run_job(
    source: str,
    data_type: str,
    job: Callable[[], object],
    alert_now: tuple[type[Exception], ...] = (),
) -> None:
    """Run `job`; on failure record it in sync_state and alert on the third failure in a row
    (or on the first one for exceptions in `alert_now`, such as a revoked grant).

    The job marks its own success (inside its write transaction)."""
    try:
        job()
    except Exception as exc:
        log.exception("%s/%s sync failed", source, data_type)
        with get_engine(Role.ingest).begin() as conn:
            failures = state.mark_failure(conn, source, data_type, f"{type(exc).__name__}: {exc}")
        urgent = isinstance(exc, alert_now) and failures == 1
        if (failures == ALERT_AFTER_FAILURES or urgent) and alert is not None:
            try:
                alert(
                    f"{source} sync failing",
                    f"{data_type} failed {failures} times in a row: {type(exc).__name__}: {exc}",
                )
            except Exception:
                log.exception("could not send alert")
