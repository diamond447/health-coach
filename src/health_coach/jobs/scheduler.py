"""Worker process: runs ingest and analytics jobs on a schedule."""

import datetime as dt
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.ingest import state
from health_coach.jobs import runner
from health_coach.jobs.runner import run_job

log = logging.getLogger(__name__)


def opengym_workouts() -> None:
    from health_coach.ingest.opengym import sync_opengym_workouts

    engine = get_engine(Role.ingest)
    run_job("opengym", "workouts", lambda: sync_opengym_workouts(engine))


def opengym_catalogue() -> None:
    from health_coach.ingest.opengym import sync_opengym_catalogue

    engine = get_engine(Role.ingest)
    run_job("opengym", "catalogue", lambda: sync_opengym_catalogue(engine))


def google_health(days_back: int, only: tuple[str, ...] = ()) -> None:
    from health_coach.ingest.google_health.client import GoogleHealthClient
    from health_coach.ingest.google_health.datatypes import DATA_TYPES
    from health_coach.ingest.google_health.oauth import ReauthRequired
    from health_coach.ingest.google_health.sync import SOURCE, sync_type, window

    engine = get_engine(Role.ingest)
    start, end = window(days_back)
    with GoogleHealthClient(engine, get_settings()) as client:
        for spec in DATA_TYPES:
            if only and spec.name not in only:
                continue
            run_job(
                SOURCE,
                spec.name,
                lambda spec=spec: sync_type(client, engine, spec, start, end),  # type: ignore[misc]
                alert_now=(ReauthRequired,),
            )


def derived_snapshot() -> None:
    from health_coach.jobs.derived import snapshot_tdee
    from health_coach.mcp_server.common import today

    engine = get_engine(Role.ingest)
    run_job("worker", "derived", lambda: snapshot_tdee(engine, today()))


def data_quality() -> None:
    from health_coach.jobs.quality import check_and_notify

    run_job("worker", "data_quality", lambda: check_and_notify(get_engine(Role.ingest)))


def _alert(title: str, body: str) -> None:
    from health_coach.notify.ntfy import NtfyClient

    NtfyClient().send(title, body, priority=4, tags=["rotating_light"])


def _never_synced(source: str, data_type: str) -> bool:
    with get_engine(Role.ingest).connect() as conn:
        return state.last_success(conn, source, data_type) is None


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(
        timezone=settings.tz,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600},
    )
    scheduler.add_job(derived_snapshot, "cron", hour=4, minute=30, id="derived_snapshot")
    if settings.opengym_url and settings.token_key:
        now = dt.datetime.now(settings.tz)
        scheduler.add_job(
            opengym_workouts,
            "interval",
            minutes=15,
            id="opengym_workouts",
            next_run_time=now,
        )
        scheduler.add_job(opengym_catalogue, "cron", hour=3, minute=30, id="opengym_catalogue")
    else:
        log.warning("openGym not configured: openGym jobs disabled")
    if settings.ntfy_topic:
        scheduler.add_job(data_quality, "cron", hour=9, minute=0, id="data_quality")
    else:
        log.warning("ntfy not configured: alerts and data-quality notifications disabled")
    if settings.google_client_id and settings.google_client_secret and settings.token_key:
        from health_coach.ingest.google_health.datatypes import SLOW_SETTLING

        # Today and yesterday every 30 minutes; watches sync late and revise data, so
        # re-read a week every night and the slow-settling types for a month weekly.
        scheduler.add_job(
            google_health,
            "interval",
            minutes=30,
            args=[1],
            id="google_recent",
            next_run_time=dt.datetime.now(settings.tz),
        )
        scheduler.add_job(google_health, "cron", hour=4, minute=0, args=[7], id="google_week")
        scheduler.add_job(
            google_health,
            "cron",
            day_of_week="sun",
            hour=5,
            minute=0,
            args=[30, SLOW_SETTLING],
            id="google_month",
        )
    else:
        log.warning("Google Health not configured: Google jobs disabled")
    return scheduler


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.ntfy_topic:
        runner.alert = _alert
    scheduler = build_scheduler(settings)
    if settings.opengym_url and settings.token_key and _never_synced("opengym", "catalogue"):
        opengym_catalogue()
    log.info("worker started with %d jobs", len(scheduler.get_jobs()))
    scheduler.start()
