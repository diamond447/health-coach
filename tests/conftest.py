"""Shared fixtures. Database tests need HC_TEST_DATABASE_URL (a superuser on a scratch
server); each test session creates and drops its own database."""

import os
import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, make_url, text

from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine

# Tests must not pick up a developer's .env.
Settings.model_config["env_file"] = None

# Fixed on purpose: roles are cluster-wide, so parallel test runs on one server must agree.
ROLE_PASSWORD = "test-role-password"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    base = os.environ.get("HC_TEST_DATABASE_URL")
    if not base:
        pytest.skip("HC_TEST_DATABASE_URL not set")
    name = "hc_test_" + secrets.token_hex(4)
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(base).set(database=name)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _role_url(owner_url: str, role: str) -> str:
    url = make_url(owner_url).set(username=role, password=ROLE_PASSWORD)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def migrated_db(database_url: str) -> Iterator[str]:
    """A database at head with service roles able to log in."""
    mp = pytest.MonkeyPatch()
    mp.setenv("HC_DATABASE_URL", database_url)
    mp.setenv("HC_RO_DATABASE_URL", _role_url(database_url, "coach_ro"))
    mp.setenv("HC_RW_DATABASE_URL", _role_url(database_url, "coach_rw"))
    mp.setenv("HC_INGEST_DATABASE_URL", _role_url(database_url, "ingest"))
    mp.setenv("HC_WEB_JOURNAL_DATABASE_URL", _role_url(database_url, "web_journal"))
    # The fixtures build data around Prague calendar days.
    mp.setenv("HC_TIMEZONE", "Europe/Prague")
    get_settings.cache_clear()
    get_engine.cache_clear()

    from health_coach.db.admin import sync_roles, upgrade

    upgrade()
    sync_roles()
    try:
        yield database_url
    finally:
        for role in Role:
            get_engine(role).dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        mp.undo()


@pytest.fixture
def owner(migrated_db: str) -> Iterator[Engine]:
    """Owner engine; every table is emptied after the test."""
    engine = get_engine(Role.owner)
    yield engine
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
