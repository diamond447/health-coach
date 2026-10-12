"""Google Health API data types this project pulls.

Names are the kebab-case identifiers used in URLs. Verified against the Google Health
API v4 discovery document (revision 20261007).
"""

from dataclasses import dataclass
from enum import StrEnum


class Method(StrEnum):
    list = "list"  # raw points (sessions, measurements, daily summaries)
    daily_roll_up = "dailyRollUp"  # aggregates per civil day


@dataclass(frozen=True)
class DataTypeSpec:
    name: str
    method: Method
    max_range_days: int  # per request; larger ranges are chunked
    table: str  # typed table the mapper fills
    # Backfill fetches at most this many days back (None: from the requested date).
    backfill_days: int | None = None


DATA_TYPES: tuple[DataTypeSpec, ...] = (
    DataTypeSpec("steps", Method.daily_roll_up, 90, "daily_activity"),
    DataTypeSpec("distance", Method.daily_roll_up, 90, "daily_activity"),
    DataTypeSpec("floors", Method.daily_roll_up, 90, "daily_activity"),
    DataTypeSpec("active-minutes", Method.daily_roll_up, 14, "daily_activity"),
    DataTypeSpec("active-zone-minutes", Method.daily_roll_up, 90, "daily_activity"),
    DataTypeSpec("total-calories", Method.daily_roll_up, 14, "daily_activity"),
    DataTypeSpec("daily-resting-heart-rate", Method.list, 90, "daily_vitals"),
    DataTypeSpec("daily-heart-rate-variability", Method.list, 90, "daily_vitals"),
    DataTypeSpec("daily-oxygen-saturation", Method.list, 90, "daily_vitals"),
    DataTypeSpec("daily-respiratory-rate", Method.list, 90, "daily_vitals"),
    DataTypeSpec("daily-sleep-temperature-derivations", Method.list, 90, "daily_vitals"),
    DataTypeSpec("daily-vo2-max", Method.list, 90, "daily_vitals"),
    DataTypeSpec("sleep", Method.list, 30, "sleep_sessions"),
    DataTypeSpec("exercise", Method.list, 30, "exercise_sessions"),
    DataTypeSpec("weight", Method.list, 90, "body_metrics"),
    DataTypeSpec("body-fat", Method.list, 90, "body_metrics"),
    DataTypeSpec("nutrition-log", Method.list, 30, "nutrition_entries"),
    # Intraday samples (tens of thousands a day, one request per day): last so the backfill
    # does not hold up the rest, and only recent history, which nothing aggregates.
    DataTypeSpec("heart-rate", Method.list, 1, "heart_rate_samples", backfill_days=30),
)

BY_NAME = {spec.name: spec for spec in DATA_TYPES}
# Data that watches revise for days after the night (sleep scores, stages).
SLOW_SETTLING = ("sleep",)
