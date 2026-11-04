import pytest
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
        "healthspan_recent",
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
    assert "healthspan_recent" in ids


def test_ntfy_push_jobs_when_configured() -> None:
    settings = Settings(ntfy_topic=SecretStr("test-topic"))
    ids = {j.id for j in build_scheduler(settings).get_jobs()}
    assert "data_quality" in ids
    assert "morning_recovery" in ids
    assert "bedtime_reminder" in ids


class _FakeClient:
    def __init__(self, *args: object) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _patch_ingest(monkeypatch: pytest.MonkeyPatch, rows: int) -> list[int]:
    from health_coach.ingest.google_health import client, sync
    from health_coach.jobs import scheduler, scores

    refreshed: list[int] = []
    monkeypatch.setattr(client, "GoogleHealthClient", _FakeClient)
    monkeypatch.setattr(
        sync, "sync_type", lambda c, e, spec, s, t: sync.TypeResult(spec.name, 1, rows)
    )
    monkeypatch.setattr(
        scores, "refresh_scores", lambda engine, days_back: refreshed.append(days_back)
    )
    monkeypatch.setattr(scheduler, "get_engine", lambda role: None)
    return refreshed


def test_scores_refresh_right_after_an_ingest_with_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from health_coach.jobs import scheduler

    refreshed = _patch_ingest(monkeypatch, rows=5)
    scheduler.google_health(1)
    scheduler.google_health(30, ("daily-vo2-max",))
    assert refreshed == [1, 7]  # capped at a week


def test_no_score_refresh_after_an_empty_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    from health_coach.jobs import scheduler

    refreshed = _patch_ingest(monkeypatch, rows=0)
    scheduler.google_health(1)
    assert refreshed == []


def test_scores_refresh_after_changed_opengym_workouts(monkeypatch: pytest.MonkeyPatch) -> None:
    from health_coach.ingest import opengym
    from health_coach.jobs import scheduler

    refreshed = _patch_ingest(monkeypatch, rows=0)
    monkeypatch.setattr(opengym, "sync_opengym_workouts", lambda engine: False)
    scheduler.opengym_workouts()
    assert refreshed == []
    monkeypatch.setattr(opengym, "sync_opengym_workouts", lambda engine: True)
    scheduler.opengym_workouts()
    assert refreshed == [7]


def test_all_jobs_with_full_configuration() -> None:
    settings = Settings(
        opengym_url="http://localhost:3000",
        token_key=SecretStr("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="),
        ntfy_topic=SecretStr("test-topic"),
        google_client_id="cid",
        google_client_secret=SecretStr("secret"),
    )
    jobs = {j.id: j for j in build_scheduler(settings).get_jobs()}
    assert set(jobs) == {
        "derived_snapshot",
        "scores_recent",
        "scores_week",
        "healthspan_recent",
        "opengym_workouts",
        "opengym_catalogue",
        "data_quality",
        "morning_recovery",
        "bedtime_reminder",
        "google_recent",
        "google_week",
        "google_month",
    }
    assert jobs["google_recent"].args == (1,)
    assert jobs["google_week"].args == (7,)
    assert jobs["google_month"].args[0] == 30


def test_all_jobs_registered_when_fully_configured() -> None:
    settings = Settings(
        opengym_url="http://localhost:3000",
        token_key=SecretStr("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="),
        ntfy_topic=SecretStr("test-topic"),
        google_client_id="client-id",
        google_client_secret=SecretStr("client-secret"),
    )
    assert {j.id for j in build_scheduler(settings).get_jobs()} == {
        "derived_snapshot",
        "scores_recent",
        "scores_week",
        "healthspan_recent",
        "opengym_workouts",
        "opengym_catalogue",
        "data_quality",
        "morning_recovery",
        "bedtime_reminder",
        "google_recent",
        "google_week",
        "google_month",
    }
