"""Database administration: migrations and role logins."""

from importlib.resources import files

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from health_coach.config import Settings, get_settings
from health_coach.db.engine import Role, get_engine


def alembic_config(settings: Settings | None = None) -> Config:
    settings = settings or get_settings()
    cfg = Config()
    cfg.set_main_option("script_location", str(files("health_coach.db") / "migrations"))
    url = settings.database_url.get_secret_value()
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(revision: str = "head", settings: Settings | None = None) -> None:
    command.upgrade(alembic_config(settings), revision)


def role_passwords(settings: Settings) -> dict[str, str | None]:
    """Login passwords per role, taken from the service URLs (None keeps NOLOGIN)."""
    passwords: dict[str, str | None] = {}
    for role, url in (
        (Role.ro, settings.ro_database_url),
        (Role.rw, settings.rw_database_url),
        (Role.ingest, settings.ingest_database_url),
        (Role.web_journal, settings.web_journal_database_url),
    ):
        if url is None or not url.get_secret_value():
            passwords[role.value] = None
            continue
        parsed = make_url(url.get_secret_value())
        if parsed.username != role.value:
            raise ValueError(f"{role.value} URL must log in as {role.value}, not {parsed.username}")
        passwords[role.value] = parsed.password
    grafana = settings.grafana_db_password
    passwords["grafana_ro"] = (
        grafana.get_secret_value() if (grafana and grafana.get_secret_value()) else None
    )
    return passwords


def sync_roles(settings: Settings | None = None) -> list[str]:
    """Give each service role LOGIN with its configured password and set the database
    time zone to HC_TIMEZONE. Returns updated roles."""
    settings = settings or get_settings()
    updated = []
    engine = get_engine(Role.owner)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        assert raw is not None
        for role, password in role_passwords(settings).items():
            if password:
                stmt = sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            else:
                stmt = sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(role))
            raw.execute(stmt)
            updated.append(role)
        # Default for sessions that do not set it (Grafana, psql); the app sets it itself.
        cur = raw.execute("SELECT current_database()").fetchone()
        assert cur is not None
        raw.execute(
            sql.SQL("ALTER DATABASE {} SET timezone TO {}").format(
                sql.Identifier(cur[0]), sql.Literal(settings.tz.key)
            )
        )
    return updated
