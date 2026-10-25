"""Tests for push notifications (morning recovery and bedtime reminder)."""

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import Engine, text

from health_coach.config import get_settings
from health_coach.db.engine import Role, get_engine
from health_coach.jobs.pushes import (
    format_bedtime_reminder,
    format_morning_recovery,
    run_bedtime_reminder,
    run_morning_recovery,
)
from health_coach.notify import ntfy
from health_coach.notify.ntfy import NotifyError

PRAGUE = ZoneInfo("Europe/Prague")


def test_formatting_en_and_cs() -> None:
    # 1. Morning recovery formatting
    cs_title, cs_body = format_morning_recovery(
        recovery=74,
        strain_target_low=11.9,
        strain_target_high=14.9,
        sleep_performance=88,
        sleep_actual_min=432,
        flags=None,
        lang="cs",
    )
    assert cs_title == "Recovery 74 % · zelená"
    assert cs_body == "Strain dnes 11,9\u201314,9 · spánek 88 % (7 h 12 min)"

    # English formatting
    en_title, en_body = format_morning_recovery(
        recovery=74,
        strain_target_low=11.9,
        strain_target_high=14.9,
        sleep_performance=88,
        sleep_actual_min=432,
        flags=None,
        lang="en",
    )
    assert en_title == "Recovery 74 % · green"
    assert en_body == "Strain target 11.9\u201314.9 · sleep 88 % (7 h 12 min)"

    # With flags
    cs_flags_title, cs_flags_body = format_morning_recovery(
        recovery=30,
        strain_target_low=6.5,
        strain_target_high=9.5,
        sleep_performance=65,
        sleep_actual_min=360,
        flags=["illness", "temperature"],
        lang="cs",
    )
    assert cs_flags_title == "Recovery 30 % · červená"
    assert "nemoc, teplota" in cs_flags_body

    # 2. Bedtime reminder formatting
    bt = dt.datetime(2026, 10, 25, 22, 0, tzinfo=PRAGUE)
    wake = dt.datetime(2026, 10, 26, 6, 30, tzinfo=PRAGUE)
    cs_bt_title, cs_bt_body = format_bedtime_reminder(
        planned_bedtime=bt,
        planned_wake=wake,
        sleep_need_min=485,
        tz=PRAGUE,
        lang="cs",
    )
    assert cs_bt_title == "Čas jít spát"
    assert cs_bt_body == "Jdi spát ve 22:00, budík 6:30 · potřeba 8 h 05 min"

    en_bt_title, en_bt_body = format_bedtime_reminder(
        planned_bedtime=bt,
        planned_wake=wake,
        sleep_need_min=485,
        tz=PRAGUE,
        lang="en",
    )
    assert en_bt_title == "Time for bed"
    assert en_bt_body == "Bedtime at 22:00, alarm 6:30 · need 8 h 05 min"


def test_morning_recovery_nothing_before_scores_exist(owner: Engine, monkeypatch: Any) -> None:
    day = dt.date(2026, 7, 10)
    engine = get_engine(Role.ingest)
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"id": "ntfy-1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    monkeypatch.setenv("HC_NTFY_TOPIC", "test-topic")
    get_settings.cache_clear()
    try:
        # Case 1: no daily_scores row
        assert run_morning_recovery(engine, day=day) is False
        assert len(sent_requests) == 0

        # Case 2: daily_scores row has recovery IS NULL
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_scores (local_date, algo_version) "
                    "VALUES (:d, 1) ON CONFLICT (local_date) DO NOTHING"
                ),
                {"d": day},
            )
        assert run_morning_recovery(engine, day=day) is False
        assert len(sent_requests) == 0

        # Case 3: daily_scores has recovery, but sleep_sessions has NO main sleep
        with owner.begin() as conn:
            conn.execute(
                text("UPDATE daily_scores SET recovery = 80 WHERE local_date = :d"),
                {"d": day},
            )
        assert run_morning_recovery(engine, day=day) is False
        assert len(sent_requests) == 0
    finally:
        ntfy.set_client(None)


def test_morning_recovery_sends_once_and_no_duplicate(owner: Engine, monkeypatch: Any) -> None:
    day = dt.date(2026, 7, 11)
    engine = get_engine(Role.ingest)
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"id": "ntfy-1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    monkeypatch.setenv("HC_NTFY_TOPIC", "test-topic")
    monkeypatch.setenv("HC_NOTIFY_LANG", "cs")
    get_settings.cache_clear()
    try:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_scores ("
                    "  local_date, recovery, strain_target_low, strain_target_high, "
                    "  sleep_performance, sleep_actual_min, algo_version"
                    ") VALUES (:d, 74, 11.9, 14.9, 88, 432, 1)"
                ),
                {"d": day},
            )
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions ("
                    "  external_id, local_date, start_ts, end_ts, duration_min, is_main, source"
                    ") VALUES ('sleep-1', :d, now() - interval '8 hours', now(), 432, true, 'g')"
                ),
                {"d": day},
            )

        # First run: should send
        res1 = run_morning_recovery(engine, day=day)
        assert res1 is True
        assert len(sent_requests) == 1
        payload = json.loads(sent_requests[0].content)
        assert payload["title"] == "Recovery 74 % · zelená"
        assert payload["message"] == "Strain dnes 11,9\u201314,9 · spánek 88 % (7 h 12 min)"

        # Verify notifications_sent row
        with owner.connect() as conn:
            sent_row = conn.execute(
                text(
                    "SELECT * FROM notifications_sent "
                    "WHERE local_date = :d AND kind = 'morning_recovery'"
                ),
                {"d": day},
            ).one_or_none()
            assert sent_row is not None

        # Second run: should NOT duplicate
        res2 = run_morning_recovery(engine, day=day)
        assert res2 is False
        assert len(sent_requests) == 1
    finally:
        ntfy.set_client(None)


def test_morning_recovery_retries_after_send_failure(owner: Engine, monkeypatch: Any) -> None:
    day = dt.date(2026, 7, 12)
    engine = get_engine(Role.ingest)
    should_fail = True

    def handler(request: httpx.Request) -> httpx.Response:
        if should_fail:
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, json={"id": "ntfy-ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    monkeypatch.setenv("HC_NTFY_TOPIC", "test-topic")
    get_settings.cache_clear()
    try:
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_scores (local_date, recovery, algo_version) "
                    "VALUES (:d, 70, 1)"
                ),
                {"d": day},
            )
            conn.execute(
                text(
                    "INSERT INTO sleep_sessions ("
                    "  external_id, local_date, start_ts, end_ts, duration_min, is_main, source"
                    ") VALUES ('sleep-f', :d, now() - interval '7 hours', now(), 420, true, 'g')"
                ),
                {"d": day},
            )

        # Attempt 1: fails
        with pytest.raises(NotifyError):
            run_morning_recovery(engine, day=day)

        # notifications_sent row must have been deleted so it retries
        with owner.connect() as conn:
            cnt = conn.execute(
                text(
                    "SELECT count(*) FROM notifications_sent "
                    "WHERE local_date = :d AND kind = 'morning_recovery'"
                ),
                {"d": day},
            ).scalar_one()
            assert cnt == 0

        # Attempt 2: succeeds
        should_fail = False
        res = run_morning_recovery(engine, day=day)
        assert res is True

        with owner.connect() as conn:
            cnt2 = conn.execute(
                text(
                    "SELECT count(*) FROM notifications_sent "
                    "WHERE local_date = :d AND kind = 'morning_recovery'"
                ),
                {"d": day},
            ).scalar_one()
            assert cnt2 == 1
    finally:
        ntfy.set_client(None)


def test_bedtime_reminder_timing_and_deduplication(owner: Engine, monkeypatch: Any) -> None:
    day = dt.date(2026, 7, 13)
    engine = get_engine(Role.ingest)
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"id": "ntfy-bed"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    monkeypatch.setenv("HC_NTFY_TOPIC", "test-topic")
    monkeypatch.setenv("HC_NOTIFY_LANG", "cs")
    get_settings.cache_clear()
    try:
        bedtime = dt.datetime(2026, 7, 13, 22, 0, tzinfo=PRAGUE)
        wake = dt.datetime(2026, 7, 14, 6, 30, tzinfo=PRAGUE)
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_scores ("
                    "  local_date, planned_bedtime, planned_wake, sleep_need_min, algo_version"
                    ") VALUES (:d, :bt, :wake, 485, 1)"
                ),
                {"d": day, "bt": bedtime, "wake": wake},
            )

        # 1. Too early: now = 21:20 (bedtime - 40 min, outside [-30 min, +60 min])
        t_early = dt.datetime(2026, 7, 13, 21, 20, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_early) is False
        assert len(sent_requests) == 0

        # 2. Too late: now = 23:05 (bedtime + 65 min)
        t_late = dt.datetime(2026, 7, 13, 23, 5, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_late) is False
        assert len(sent_requests) == 0

        # 3. Inside window: now = 21:45 (bedtime - 15 min) -> sends!
        t_window = dt.datetime(2026, 7, 13, 21, 45, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_window) is True
        assert len(sent_requests) == 1
        payload = json.loads(sent_requests[0].content)
        assert payload["title"] == "Čas jít spát"
        assert payload["message"] == "Jdi spát ve 22:00, budík 6:30 · potřeba 8 h 05 min"

        # 4. Next run inside window: now = 21:50 -> no duplicate
        t_next = dt.datetime(2026, 7, 13, 21, 50, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_next) is False
        assert len(sent_requests) == 1
    finally:
        ntfy.set_client(None)


def test_bedtime_reminder_after_midnight(owner: Engine, monkeypatch: Any) -> None:
    day = dt.date(2026, 7, 20)
    engine = get_engine(Role.ingest)
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"id": "ntfy-bed-midnight"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ntfy.set_client(client)
    monkeypatch.setenv("HC_NTFY_TOPIC", "test-topic")
    monkeypatch.setenv("HC_NOTIFY_LANG", "cs")
    get_settings.cache_clear()
    try:
        # Planned bedtime for day 2026-07-20 is 00:30 on 2026-07-21
        bedtime = dt.datetime(2026, 7, 21, 0, 30, tzinfo=PRAGUE)
        wake = dt.datetime(2026, 7, 21, 8, 30, tzinfo=PRAGUE)
        with owner.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO daily_scores ("
                    "  local_date, planned_bedtime, planned_wake, sleep_need_min, algo_version"
                    ") VALUES (:d, :bt, :wake, 480, 1)"
                ),
                {"d": day, "bt": bedtime, "wake": wake},
            )

        # 1. At 23:55 on day D: window is [00:00, 01:30), so 23:55 is outside -> False
        t_early = dt.datetime(2026, 7, 20, 23, 55, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_early) is False
        assert len(sent_requests) == 0

        # 2. At 00:10 on day D+1: inside [00:00, 01:30) -> True, keys notifications_sent by D
        t_window = dt.datetime(2026, 7, 21, 0, 10, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_window) is True
        assert len(sent_requests) == 1
        payload = json.loads(sent_requests[0].content)
        assert payload["title"] == "Čas jít spát"
        assert payload["message"] == "Jdi spát ve 0:30, budík 8:30 · potřeba 8 h 00 min"

        # Check notifications_sent is keyed by day D (2026-07-20)
        with owner.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT local_date FROM notifications_sent "
                    "WHERE kind = 'bedtime_reminder' AND local_date = :d"
                ),
                {"d": day},
            ).one_or_none()
            assert row is not None
            assert row.local_date == day

        # 3. Next run inside window on day D+1: already sent -> False
        t_next = dt.datetime(2026, 7, 21, 0, 20, tzinfo=PRAGUE)
        assert run_bedtime_reminder(engine, now=t_next) is False
        assert len(sent_requests) == 1
    finally:
        ntfy.set_client(None)
