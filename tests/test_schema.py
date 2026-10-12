import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from health_coach.db.engine import Role, get_engine

VIEWS = [
    "v_body_daily",
    "v_weight_trend",
    "v_nutrition_daily",
    "v_strength_volume_weekly",
    "v_exercise_e1rm",
    "v_daily",
    "v_recovery_baseline",
]
PRAGUE = ZoneInfo("Europe/Prague")


def _today() -> dt.date:
    return dt.datetime.now(PRAGUE).date()


@pytest.mark.parametrize("view", VIEWS)
def test_views_are_empty_on_empty_db(owner: Engine, view: str) -> None:
    with get_engine(Role.ro).connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {view}")).scalar_one() == 0


def test_downgrade_and_upgrade_again(owner: Engine) -> None:
    from health_coach.db.admin import upgrade

    upgrade("base")
    upgrade("head")
    with owner.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM v_daily")).scalar_one() == 0


@pytest.mark.parametrize("table", ["oauth_tokens", "raw_payloads", "mcp_audit"])
def test_coach_ro_cannot_read_secrets(owner: Engine, table: str) -> None:
    with get_engine(Role.ro).connect() as conn, pytest.raises(DBAPIError, match="permission"):
        conn.execute(text(f"SELECT * FROM {table}"))


def test_coach_ro_is_read_only(owner: Engine) -> None:
    with get_engine(Role.ro).connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("INSERT INTO checkins (local_date, energy) VALUES (current_date, 3)"))


def test_coach_ro_session_settings(owner: Engine) -> None:
    with get_engine(Role.ro).connect() as conn:
        assert conn.execute(text("SHOW work_mem")).scalar_one() == "32MB"
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "5s"
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"


def test_sessions_and_v_daily_use_the_configured_time_zone(owner: Engine) -> None:
    with get_engine(Role.ro).connect() as conn:
        assert conn.execute(text("SHOW TimeZone")).scalar_one() == "Europe/Prague"
    with owner.begin() as conn:
        defaults = conn.execute(
            text(
                "SELECT unnest(setconfig) FROM pg_db_role_setting s "
                "JOIN pg_database d ON d.oid = s.setdatabase "
                "WHERE d.datname = current_database() AND s.setrole = 0"
            )
        ).scalars()
        assert "TimeZone=Europe/Prague" in list(defaults)
        conn.execute(
            text("INSERT INTO checkins (local_date, energy) VALUES (:d, 3)"),
            {"d": _today() - dt.timedelta(days=2)},
        )
    with get_engine(Role.ro).connect() as conn:
        assert conn.execute(text("SELECT max(local_date) FROM v_daily")).scalar_one() == _today()


def test_coach_rw_writes_logs_but_not_wearables(owner: Engine) -> None:
    with get_engine(Role.rw).begin() as conn:
        conn.execute(text("INSERT INTO checkins (local_date, energy) VALUES (current_date, 3)"))
        conn.execute(text("INSERT INTO mcp_audit (tool, duration_ms) VALUES ('x', 1)"))
    with get_engine(Role.rw).connect() as conn, pytest.raises(DBAPIError, match="permission"):
        conn.execute(
            text("INSERT INTO daily_activity (local_date, steps) VALUES (current_date, 1)")
        )


def test_ingest_writes_wearables_but_not_coaching_state(owner: Engine) -> None:
    with get_engine(Role.ingest).begin() as conn:
        conn.execute(
            text("INSERT INTO daily_activity (local_date, steps) VALUES (current_date, 1)")
        )
    with get_engine(Role.ingest).connect() as conn, pytest.raises(DBAPIError, match="permission"):
        conn.execute(
            text(
                "INSERT INTO targets (effective_from, phase, kcal, protein_g, reason) "
                "VALUES (current_date, 'bulk', 2700, 150, 'x')"
            )
        )


def _weigh(conn, day: dt.date, kg: float, hour: int = 7, source: str = "chat") -> None:  # type: ignore[no-untyped-def]
    ts = dt.datetime.combine(day, dt.time(hour), PRAGUE)
    conn.execute(
        text(
            "INSERT INTO body_metrics (ts, local_date, weight_kg, source) "
            "VALUES (:ts, :d, :kg, :src)"
        ),
        {"ts": ts, "d": day, "kg": kg, "src": source},
    )


def test_body_daily_keeps_earliest_weight(owner: Engine) -> None:
    day = _today()
    with owner.begin() as conn:
        _weigh(conn, day, 79.0, hour=20, source="wger")
        _weigh(conn, day, 78.2, hour=7, source="google_health")
    with owner.connect() as conn:
        row = conn.execute(text("SELECT weight_kg FROM v_body_daily")).one()
    assert row.weight_kg == Decimal("78.20")


def test_weight_trend_weekly_rate(owner: Engine) -> None:
    start = _today() - dt.timedelta(days=27)
    with owner.begin() as conn:
        for i in range(28):
            _weigh(conn, start + dt.timedelta(days=i), 78.0 + 0.05 * i)  # +0.35 kg/week
    with owner.connect() as conn:
        rows = conn.execute(text("SELECT * FROM v_weight_trend ORDER BY local_date")).all()
    assert len(rows) == 28
    assert rows[0].weekly_rate_kg is None
    assert rows[-1].avg_7d_kg == Decimal("79.20")
    # The smoothed trend lags a linear gain, but its slope converges to the true rate.
    assert Decimal("0.30") <= rows[-1].weekly_rate_kg <= Decimal("0.36")


def test_nutrition_daily_against_targets(owner: Engine) -> None:
    day = _today()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO targets (effective_from, phase, kcal, protein_g, reason) VALUES "
                "(:d0, 'maintenance', 2500, 140, 'old'), (:d1, 'bulk', 2700, 150, 'new')"
            ),
            {"d0": day - dt.timedelta(days=30), "d1": day},
        )
        _weigh(conn, day, 80.0)
        for meal, kcal, protein in (("breakfast", 600, 40), ("lunch", 900, 50)):
            conn.execute(
                text(
                    "INSERT INTO nutrition_entries (ts, local_date, meal, description, kcal, "
                    "protein_g, carbs_g, fat_g, confidence) VALUES "
                    "(now(), :d, :meal, 'x', :kcal, :p, 100, 20, 'estimated')"
                ),
                {"d": day, "meal": meal, "kcal": kcal, "p": protein},
            )
    with owner.connect() as conn:
        row = conn.execute(text("SELECT * FROM v_nutrition_daily")).one()
    assert row.kcal == 1500
    assert row.target_kcal == 2700
    assert row.kcal_vs_target == -1200
    assert row.protein_g_per_kg == Decimal("1.13")
    assert row.entries == 2


def _strength_fixture(conn) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "INSERT INTO exercises (id, name, primary_muscles, secondary_muscles) VALUES "
            "('73', 'Bench press', '{chest}', '{triceps,shoulders}'), "
            "('91', 'Squat', '{quads}', '{glutes}')"
        )
    )
    conn.execute(
        text("INSERT INTO strength_sessions (external_id, local_date) VALUES ('session-1', :d)"),
        {"d": _today()},
    )
    sets = [
        # exercise, set_no, reps, kg, rir, warmup
        ("73", 1, 10, 40, None, True),
        ("73", 2, 8, 80, 2, False),
        ("73", 3, 6, 85, 1, False),
        ("73", 4, 12, 60, 6, False),  # too easy: not a hard set, no e1RM
        ("91", 1, 5, 100, 2, False),
    ]
    for i, (ex, no, reps, kg, rir, warmup) in enumerate(sets):
        conn.execute(
            text(
                "INSERT INTO strength_sets (session_id, external_id, exercise_id, set_no, reps, "
                "weight_kg, rir, is_warmup) VALUES (1, :log, :ex, :no, :reps, :kg, :rir, :w)"
            ),
            {
                "log": f"set-{i}",
                "ex": ex,
                "no": no,
                "reps": reps,
                "kg": kg,
                "rir": rir,
                "w": warmup,
            },
        )


def test_strength_views(owner: Engine) -> None:
    with owner.begin() as conn:
        _strength_fixture(conn)
    with owner.connect() as conn:
        volume = {
            r.muscle: r.hard_sets
            for r in conn.execute(text("SELECT * FROM v_strength_volume_weekly")).all()
        }
        e1rm = {
            r.exercise: r.e1rm_kg for r in conn.execute(text("SELECT * FROM v_exercise_e1rm")).all()
        }
        daily = conn.execute(
            text("SELECT * FROM v_daily WHERE local_date = :d"), {"d": _today()}
        ).one()
    assert volume == {
        "chest": Decimal("2.0"),
        "triceps": Decimal("1.0"),
        "shoulders": Decimal("1.0"),
        "quads": Decimal("1.0"),
        "glutes": Decimal("0.5"),
    }
    assert e1rm == {"Bench press": Decimal("102.0"), "Squat": Decimal("116.7")}  # 85x6 beats 80x8
    assert daily.strength_sessions == 1
    assert daily.hard_sets == 3
    assert daily.tonnage_kg == Decimal("2370")  # working sets incl. the easy one


def test_recovery_baseline_zscores(owner: Engine) -> None:
    today = _today()
    with owner.begin() as conn:
        for i in range(30, 0, -1):
            conn.execute(
                text("INSERT INTO daily_vitals (local_date, resting_hr) VALUES (:d, :hr)"),
                {"d": today - dt.timedelta(days=i), "hr": 50 + (i % 2) * 2},  # 50/52
            )
        conn.execute(
            text("INSERT INTO daily_vitals (local_date, resting_hr) VALUES (:d, 56)"),
            {"d": today},
        )
    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM v_recovery_baseline WHERE local_date = :d"), {"d": today}
        ).one()
    assert row.rhr_n_30d == 30
    assert row.rhr_mean_30d == Decimal("51.0")
    assert row.rhr_z > 4


@pytest.mark.parametrize("role", [Role.ro, Role.rw, Role.ingest])
def test_no_temp_tables(owner: Engine, role: Role) -> None:
    with (
        get_engine(role).connect() as conn,
        pytest.raises(DBAPIError, match=r"permission|read-only"),
    ):
        conn.execute(text("CREATE TEMP TABLE t (x int)"))
