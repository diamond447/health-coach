"""Engines per database role. Each service only gets the role it needs."""

from enum import StrEnum
from functools import cache

from sqlalchemy import Engine, create_engine

from health_coach.config import get_settings


class Role(StrEnum):
    owner = "owner"
    ro = "coach_ro"
    rw = "coach_rw"
    ingest = "ingest"


@cache
def get_engine(role: Role) -> Engine:
    settings = get_settings()
    url = {
        Role.owner: settings.database_url,
        Role.ro: settings.ro_database_url,
        Role.rw: settings.rw_database_url,
        Role.ingest: settings.ingest_database_url,
    }[role]
    # local_date and CURRENT_DATE in SQL follow the session time zone.
    return create_engine(
        url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        connect_args={"options": f"-c TimeZone={settings.tz.key}"},
    )
