"""daily_range() and the single-pass v_body_daily (revision 0013) against the views they
replace for range reads, on a seeded history."""

import datetime as dt
from zoneinfo import ZoneInfo

from alembic import command
from sqlalchemy import Engine, text

from health_coach.db.admin import alembic_config
from health_coach.db.engine import Role, get_engine
from tests.seed import seed_history

PRAGUE = ZoneInfo("Europe/Prague")


def _rows(engine: Engine, sql: str, **params: object) -> list[tuple[object, ...]]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def test_daily_range_on_an_empty_database(owner: Engine) -> None:
    today = dt.datetime.now(PRAGUE).date()
    assert _rows(get_engine(Role.ro), "SELECT * FROM daily_range(:s, :e)", s=today, e=today) == []


def test_daily_range_matches_v_daily(owner: Engine) -> None:
    seed_history(owner, days=200, hr_days=1)
    with owner.begin() as conn:
        # A second weigh-in later the same day, and a deleted one earlier
        conn.execute(
            text(
                "INSERT INTO body_metrics (ts, local_date, weight_kg, waist_cm, source, "
                "deleted_at) VALUES "
                "(CURRENT_DATE + time '21:00', CURRENT_DATE, 90, 85.5, 'x', NULL), "
                "(CURRENT_DATE + time '01:00', CURRENT_DATE, 70, NULL, 'x', now())"
            )
        )
    today = dt.datetime.now(PRAGUE).date()
    ro = get_engine(Role.ro)
    ranges = [
        (today, today),
        (today - dt.timedelta(days=6), today),
        (today - dt.timedelta(days=89), today),
        (today - dt.timedelta(days=400), today + dt.timedelta(days=5)),  # beyond both ends
        (today - dt.timedelta(days=30), today - dt.timedelta(days=20)),
    ]
    for start, end in ranges:
        expected = _rows(
            ro,
            "SELECT * FROM v_daily WHERE local_date BETWEEN :s AND :e ORDER BY local_date",
            s=start,
            e=end,
        )
        got = _rows(ro, "SELECT * FROM daily_range(:s, :e) ORDER BY local_date", s=start, e=end)
        assert got == expected, (start, end)
        assert got
    assert _rows(ro, "SELECT * FROM daily_range(:s, :e)", s=today, e=today - dt.timedelta(1)) == []


def test_single_pass_body_daily_matches_revision_0001(owner: Engine) -> None:
    seed_history(owner, days=200, hr_days=1)
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO body_metrics (ts, local_date, weight_kg, body_fat_pct, waist_cm, "
                "source, deleted_at) VALUES "
                "(CURRENT_DATE + time '05:00', CURRENT_DATE, NULL, 17.5, NULL, 'x', NULL), "
                "(CURRENT_DATE + time '22:00', CURRENT_DATE, 90, 25, 85.5, 'x', NULL), "
                "(CURRENT_DATE + time '01:00', CURRENT_DATE, 70, NULL, 80, 'x', now())"
            )
        )
    sql = "SELECT * FROM v_body_daily ORDER BY local_date"
    single_pass = _rows(owner, sql)
    cfg = alembic_config()
    command.downgrade(cfg, "0012")
    try:
        original = _rows(owner, sql)
    finally:
        command.upgrade(cfg, "head")
    assert len(single_pass) > 150
    assert single_pass == original
