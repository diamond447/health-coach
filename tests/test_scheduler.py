from pydantic import SecretStr

from health_coach.config import Settings
from health_coach.jobs.scheduler import build_scheduler


def test_scheduler_uses_local_timezone() -> None:
    assert Settings.model_fields["timezone"].default == "UTC"
    scheduler = build_scheduler(Settings(timezone="Europe/Prague"))
    assert str(scheduler.timezone) == "Europe/Prague"


def test_opengym_jobs_only_when_configured() -> None:
    assert {j.id for j in build_scheduler(Settings(opengym_url=None)).get_jobs()} == {
        "derived_snapshot",
        "scores_recent",
        "scores_week",
    }
    configured = Settings(
        opengym_url="http://localhost:3000",
        token_key=SecretStr("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="),
    )
    ids = {j.id for j in build_scheduler(configured).get_jobs()}
    assert "opengym_workouts" in ids
    assert "opengym_catalogue" in ids
    assert "scores_recent" in ids
    assert "scores_week" in ids


def test_ntfy_push_jobs_when_configured() -> None:
    settings = Settings(ntfy_topic=SecretStr("test-topic"))
    ids = {j.id for j in build_scheduler(settings).get_jobs()}
    assert "data_quality" in ids
    assert "morning_recovery" in ids
    assert "bedtime_reminder" in ids
