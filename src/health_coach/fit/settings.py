"""Runtime settings for the fit MCP server (FIT_* environment variables)."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class FitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FIT_", extra="ignore")

    opengym_url: str | None = None
    opengym_version: str = "1.4.1"

    # SQLite database for user-token links
    db_path: str = "/data/fit.db"

    # Fernet key for encrypting openGym bearer tokens at rest
    token_key: SecretStr | None = None

    # Authentik OAuth settings
    public_url: str | None = None
    auth_issuer: str | None = None
    auth_audience: list[str] = Field(default_factory=list)
    auth_jwks_url: str | None = None
    auth_disabled: bool = False

    # Server configuration
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8081
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost:*", "127.0.0.1:*"])
    timezone: str = "UTC"
    log_level: str = "INFO"

    # Subject used when auth is disabled (local dev / testing)
    dev_subject: str = "dev-user"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_fit_settings() -> FitSettings:
    return FitSettings()
