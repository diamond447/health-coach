"""Runtime settings, read from the environment (and `.env` in development)."""

from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HC_", extra="ignore")

    timezone: str = "UTC"
    log_level: str = "INFO"

    # Postgres connections. The owner runs migrations; services use least-privilege
    # roles (0001_roles.sql). Passwords in these URLs are applied to the roles by
    # `health-coach db sync-roles`; a URL without password leaves the role NOLOGIN.
    database_url: SecretStr = SecretStr("postgresql+psycopg://health:health@localhost:5432/health")
    ro_database_url: SecretStr = SecretStr("postgresql+psycopg://coach_ro@localhost:5432/health")
    rw_database_url: SecretStr = SecretStr("postgresql+psycopg://coach_rw@localhost:5432/health")
    ingest_database_url: SecretStr = SecretStr("postgresql+psycopg://ingest@localhost:5432/health")
    web_journal_database_url: SecretStr | None = None
    # Optional read-only login for Grafana; the role stays NOLOGIN when unset.
    grafana_db_password: SecretStr | None = None

    @field_validator("web_journal_database_url", mode="before")
    @classmethod
    def _empty_web_journal_url_is_none(cls, v: Any) -> Any:
        if v == "" or (isinstance(v, SecretStr) and v.get_secret_value() == ""):
            return None
        return v

    # Fernet key that encrypts OAuth tokens in the database.
    token_key: SecretStr | None = None

    # Google Health API (OAuth client of type "Web application" or "Desktop").
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # Loopback redirect registered on the client. The CLI asks you to paste the URL the
    # browser was redirected to, so nothing has to listen on it.
    google_redirect_uri: str = "http://localhost:8765/callback"
    # Read-only scopes (verified against Google Health API reference revision 20261007).
    google_scopes: list[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
            "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
            "https://www.googleapis.com/auth/googlehealth.nutrition.readonly",
        ]
    )
    google_api_base: str = "https://health.googleapis.com/v4"

    # openGym instance (HC_OPENGYM_URL, HC_OPENGYM_VERSION).
    opengym_url: str | None = None
    opengym_version: str = "1.4.1"

    # Remote access (docs/adr/0001): Authentik issues the tokens, this server checks them.
    # Public URL of the MCP endpoint exactly as entered in Claude, e.g.
    # https://coach.example.com/mcp
    public_url: str | None = None
    # Issuer of the Authentik provider, e.g. https://auth.example.com/application/o/health-coach/
    auth_issuer: str | None = None
    # OAuth client ID of the provider (the `aud` of its access tokens).
    auth_audience: str | None = None
    # JWKS URL; defaults to <issuer>/jwks/ (Authentik). Can point at an internal URL.
    auth_jwks_url: str | None = None
    # Token subjects allowed in (with Authentik: usernames, sub_mode user_username).
    auth_allowed_subjects: list[str] = Field(default_factory=list)
    # Run without auth. Only for a loopback-only development setup.
    auth_disabled: bool = False

    # MCP server (Streamable HTTP).
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8080
    # Host header values the MCP endpoint accepts (DNS rebinding protection).
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost:*", "127.0.0.1:*"])

    # Open Food Facts API base URL.
    off_base_url: str = "https://world.openfoodfacts.org"

    # Daily WHOOP-style scoring settings. The profile values (HC_HR_MAX, HC_BIRTH_YEAR,
    # HC_SEX) are fallbacks: the coach's set_profile values in app_settings win
    # (see health_coach.profile).
    # Maximum heart rate. Fallback: Tanaka 208 - 0.7*age; if age unknown, 190.
    hr_max: int | None = None
    # Birth year. Age = current year - birth_year.
    birth_year: int | None = None
    # Biological sex. Selects Banister coefficients; None uses the mean of both curves.
    sex: Literal["male", "female"] | None = None
    # Baseline sleep need in minutes (HC_SLEEP_NEED_BASE_MIN).
    sleep_need_base_min: int = 480

    # ntfy push notifications.
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: SecretStr | None = None
    # Access token for servers that require auth (HC_NTFY_TOKEN), sent as a bearer token.
    ntfy_token: SecretStr | None = None
    notify_lang: Literal["en", "cs"] = "en"

    # Healthstats web app
    web_host: str = "127.0.0.1"
    web_port: int = 8090
    web_allowed_users: list[str] = Field(default_factory=list)
    web_user_header: str = "X-authentik-username"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
