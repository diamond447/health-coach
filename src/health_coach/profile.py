"""Personal profile for the scores: maximum heart rate, birth year and sex.

The values live in app_settings (set by the coach with set_profile), so they stay in the
private database. HC_HR_MAX, HC_BIRTH_YEAR and HC_SEX are fallbacks for deployments that
prefer environment configuration.
"""

import datetime as dt
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import Connection, text

from health_coach.config import Settings, get_settings

log = logging.getLogger(__name__)

Sex = Literal["male", "female"]

PROFILE_KEYS = ("hr_max", "birth_year", "sex")
HR_MAX_RANGE = (120, 230)
MIN_BIRTH_YEAR = 1900
DEFAULT_HR_MAX = 190


@dataclass(frozen=True)
class Profile:
    hr_max: int | None = None
    birth_year: int | None = None
    sex: Sex | None = None

    def age(self, year: int) -> int | None:
        if self.birth_year is None:
            return None
        return max(0, year - self.birth_year)

    def effective_hr_max(self, year: int) -> int:
        """Measured HRmax, else Tanaka (208 - 0.7 * age), else 190 bpm."""
        if self.hr_max is not None:
            return self.hr_max
        age = self.age(year)
        if age is not None:
            return round(208 - 0.7 * age)
        return DEFAULT_HR_MAX


def valid_hr_max(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        return None
    lo, hi = HR_MAX_RANGE
    return int(value) if lo <= value <= hi else None


def valid_birth_year(value: Any, current_year: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        return None
    return int(value) if MIN_BIRTH_YEAR <= value <= current_year else None


def valid_sex(value: Any) -> Sex | None:
    return cast(Sex, value) if value in ("male", "female") else None


def profile_from(app_settings: Mapping[str, Any], settings: Settings | None = None) -> Profile:
    """Resolve the profile: app_settings values win, HC_* settings are the fallback."""
    settings = settings or get_settings()
    current_year = dt.datetime.now(settings.tz).year
    checks = {
        "hr_max": valid_hr_max,
        "birth_year": lambda v: valid_birth_year(v, current_year),
        "sex": valid_sex,
    }
    resolved: dict[str, Any] = {}
    for key in PROFILE_KEYS:
        raw = app_settings.get(key)
        value = checks[key](raw) if raw is not None else None
        if raw is not None and value is None:
            log.warning("ignoring invalid %s setting: %r", key, raw)
        resolved[key] = value if value is not None else getattr(settings, key)
    return Profile(**resolved)


def load_profile(conn: Connection, settings: Settings | None = None) -> Profile:
    rows = conn.execute(
        text("SELECT key, value FROM app_settings WHERE key = ANY(:keys)"),
        {"keys": list(PROFILE_KEYS)},
    ).all()
    return profile_from({r.key: r.value for r in rows}, settings)
