"""Typed tables. Views live in SQL files next to the migrations that create them.

Conventions (see docs/architecture.md, "Database"):
- timestamps are timestamptz in UTC; daily records also carry `local_date` (in HC_TIMEZONE)
- every table has `created_at` and `updated_at`; data tables also have `source`
- rows that tools may delete are soft-deleted through `deleted_at`
"""

import datetime as dt
import enum
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads it as a class attribute
        dt.datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


class Timestamps:
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _bigid() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


# --- Raw and sync state ---------------------------------------------------------------


class RawPayload(Timestamps, Base):
    __tablename__ = "raw_payloads"
    __table_args__ = (UniqueConstraint("source", "data_type", "range_start", "range_end"),)

    id: Mapped[int] = _bigid()
    source: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(Text)
    range_start: Mapped[dt.datetime]
    range_end: Mapped[dt.datetime]
    payload: Mapped[dict[str, Any]]
    fetched_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class SyncState(Timestamps, Base):
    __tablename__ = "sync_state"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    data_type: Mapped[str] = mapped_column(Text, primary_key=True)
    last_success_at: Mapped[dt.datetime | None]
    last_attempt_at: Mapped[dt.datetime | None]
    cursor: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_count: Mapped[int] = mapped_column(Integer, server_default="0")


class OAuthToken(Timestamps, Base):
    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    refresh_token_enc: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[dt.datetime | None]
    scopes: Mapped[list[str]] = mapped_column(server_default="{}")


# --- Wearable data --------------------------------------------------------------------


class DailyActivity(Timestamps, Base):
    __tablename__ = "daily_activity"

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    active_minutes: Mapped[int | None] = mapped_column(Integer)
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer)
    calories_out: Mapped[int | None] = mapped_column(Integer)
    floors: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, server_default="google_health")


class DailyVitals(Timestamps, Base):
    __tablename__ = "daily_vitals"

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    resting_hr: Mapped[int | None] = mapped_column(SmallInteger)
    hrv_rmssd_ms: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    spo2_avg: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    breathing_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    skin_temp_delta: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    cardio_fitness: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    source: Mapped[str] = mapped_column(Text, server_default="google_health")


class HeartRateSample(Base):
    """Intraday heart rate. Kept narrow on purpose: no updated_at, ~500k rows per year."""

    __tablename__ = "heart_rate_samples"

    ts: Mapped[dt.datetime] = mapped_column(primary_key=True)
    bpm: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(Text, server_default="google_health")
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class SleepSession(Timestamps, Base):
    __tablename__ = "sleep_sessions"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_sleep_sessions_local_date", "local_date"),
        Index("ix_sleep_sessions_start_ts", "start_ts"),
    )

    id: Mapped[int] = _bigid()
    external_id: Mapped[str] = mapped_column(Text)
    start_ts: Mapped[dt.datetime]
    end_ts: Mapped[dt.datetime]
    local_date: Mapped[dt.date] = mapped_column(Date, comment="Wake-up date, local time zone")
    duration_min: Mapped[int] = mapped_column(Integer, comment="Time asleep")
    time_in_bed_min: Mapped[int | None] = mapped_column(Integer)
    efficiency: Mapped[int | None] = mapped_column(SmallInteger)
    minutes_deep: Mapped[int | None] = mapped_column(Integer)
    minutes_light: Mapped[int | None] = mapped_column(Integer)
    minutes_rem: Mapped[int | None] = mapped_column(Integer)
    minutes_awake: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[int | None] = mapped_column(SmallInteger)
    is_main: Mapped[bool] = mapped_column(server_default=text("true"))
    source: Mapped[str] = mapped_column(Text, server_default="google_health")


class SleepStage(Base):
    __tablename__ = "sleep_stages"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sleep_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    start_ts: Mapped[dt.datetime] = mapped_column(primary_key=True)
    end_ts: Mapped[dt.datetime]
    stage: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class ExerciseSession(Timestamps, Base):
    """Workouts recorded by the watch, or logged by hand when the watch missed one."""

    __tablename__ = "exercise_sessions"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_exercise_sessions_local_date", "local_date"),
        Index("ix_exercise_sessions_start_ts", "start_ts"),
    )

    id: Mapped[int] = _bigid()
    external_id: Mapped[str | None] = mapped_column(Text)
    start_ts: Mapped[dt.datetime]
    end_ts: Mapped[dt.datetime]
    local_date: Mapped[dt.date] = mapped_column(Date)
    activity_type: Mapped[str] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr: Mapped[int | None] = mapped_column(SmallInteger)
    calories: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    hr_zone_minutes: Mapped[dict[str, Any] | None]
    rpe: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="google_health")
    deleted_at: Mapped[dt.datetime | None]


# --- Body and nutrition ---------------------------------------------------------------


class BodyMetric(Timestamps, Base):
    __tablename__ = "body_metrics"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_body_metrics_local_date", "local_date"),
        Index("ix_body_metrics_ts", "ts"),
    )

    id: Mapped[int] = _bigid()
    external_id: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[dt.datetime]
    local_date: Mapped[dt.date] = mapped_column(Date)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    other: Mapped[dict[str, Any] | None]
    source: Mapped[str] = mapped_column(Text)
    deleted_at: Mapped[dt.datetime | None]


class FoodSource(enum.StrEnum):
    custom = "custom"
    openfoodfacts = "openfoodfacts"
    wger = "wger"
    google_health = "google_health"


class Food(Timestamps, Base):
    __tablename__ = "foods"
    __table_args__ = (
        Index("ix_foods_barcode", "barcode"),
        Index("ix_foods_name_lower", text("lower(name)")),
    )

    id: Mapped[int] = _bigid()
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(Text)
    kcal_100g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    protein_100g: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    carbs_100g: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    fat_100g: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    fiber_100g: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    default_serving_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    source: Mapped[FoodSource] = mapped_column(_enum(FoodSource, "food_source"))
    external_id: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[dt.datetime | None]


class Meal(enum.StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"
    other = "other"


class Confidence(enum.StrEnum):
    exact = "exact"
    estimated = "estimated"
    photo = "photo"


class NutritionEntry(Timestamps, Base):
    """One eaten item. Macros are copied from the food so later edits keep history intact."""

    __tablename__ = "nutrition_entries"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_nutrition_entries_local_date", "local_date"),
        Index("ix_nutrition_entries_ts", "ts"),
        Index("ix_nutrition_entries_food_id", "food_id"),
    )

    id: Mapped[int] = _bigid()
    external_id: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[dt.datetime]
    local_date: Mapped[dt.date] = mapped_column(Date)
    meal: Mapped[Meal] = mapped_column(_enum(Meal, "meal"))
    food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"))
    description: Mapped[str] = mapped_column(Text)
    grams: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    kcal: Mapped[Decimal] = mapped_column(Numeric(7, 1))
    protein_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    carbs_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    fat_g: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    confidence: Mapped[Confidence] = mapped_column(_enum(Confidence, "confidence"))
    source: Mapped[str] = mapped_column(Text, server_default="chat")
    deleted_at: Mapped[dt.datetime | None]


class Checkin(Timestamps, Base):
    __tablename__ = "checkins"
    __table_args__ = (
        CheckConstraint("energy BETWEEN 1 AND 5", name="energy_1_5"),
        CheckConstraint("soreness BETWEEN 1 AND 5", name="soreness_1_5"),
        CheckConstraint("stress BETWEEN 1 AND 5", name="stress_1_5"),
        CheckConstraint("motivation BETWEEN 1 AND 5", name="motivation_1_5"),
    )

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    energy: Mapped[int | None] = mapped_column(SmallInteger)
    soreness: Mapped[int | None] = mapped_column(SmallInteger)
    stress: Mapped[int | None] = mapped_column(SmallInteger)
    motivation: Mapped[int | None] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="chat")


# --- Strength training (mirror of openGym) --------------------------------------------


class Exercise(Timestamps, Base):
    __tablename__ = "exercises"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    primary_muscles: Mapped[list[str]] = mapped_column(server_default="{}")
    secondary_muscles: Mapped[list[str]] = mapped_column(server_default="{}")
    equipment: Mapped[list[str]] = mapped_column(server_default="{}")
    source: Mapped[str] = mapped_column(Text, server_default="opengym")


class StrengthSession(Timestamps, Base):
    __tablename__ = "strength_sessions"
    __table_args__ = (Index("ix_strength_sessions_local_date", "local_date"),)

    id: Mapped[int] = _bigid()
    external_id: Mapped[str] = mapped_column(Text, unique=True)
    local_date: Mapped[dt.date] = mapped_column(Date)
    start_ts: Mapped[dt.datetime | None]
    end_ts: Mapped[dt.datetime | None]
    routine_id: Mapped[str | None] = mapped_column(Text)
    routine_name: Mapped[str | None] = mapped_column(Text)
    day_name: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="opengym")


class StrengthSet(Timestamps, Base):
    __tablename__ = "strength_sets"
    __table_args__ = (
        Index("ix_strength_sets_session_id", "session_id"),
        Index("ix_strength_sets_exercise_id", "exercise_id"),
    )

    id: Mapped[int] = _bigid()
    session_id: Mapped[int] = mapped_column(ForeignKey("strength_sessions.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(Text, unique=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.id"))
    set_no: Mapped[int] = mapped_column(SmallInteger)
    reps: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rir: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    is_warmup: Mapped[bool] = mapped_column(server_default=text("false"))
    source: Mapped[str] = mapped_column(Text, server_default="opengym")


# --- Coaching state -------------------------------------------------------------------


class Phase(enum.StrEnum):
    bulk = "bulk"
    cut = "cut"
    maintenance = "maintenance"
    deload = "deload"


class Target(Timestamps, Base):
    """Versioned nutrition and activity targets; current = latest effective_from <= today."""

    __tablename__ = "targets"
    __table_args__ = (Index("ix_targets_effective_from", "effective_from"),)

    id: Mapped[int] = _bigid()
    effective_from: Mapped[dt.date] = mapped_column(Date)
    phase: Mapped[Phase] = mapped_column(_enum(Phase, "phase"))
    kcal: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[int] = mapped_column(Integer, comment="Daily minimum")
    protein_max_g: Mapped[int | None] = mapped_column(Integer)
    carbs_g: Mapped[int | None] = mapped_column(Integer)
    fat_g: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[int | None] = mapped_column(Integer)
    weekly_rate_min_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), comment="Lower bound of the wanted weekly trend change (negative = loss)"
    )
    weekly_rate_max_kg: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="chat")


class GoalStatus(enum.StrEnum):
    open = "open"
    achieved = "achieved"
    abandoned = "abandoned"


class Goal(Timestamps, Base):
    __tablename__ = "goals"

    id: Mapped[int] = _bigid()
    name: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    deadline: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[GoalStatus] = mapped_column(
        _enum(GoalStatus, "goal_status"), server_default=GoalStatus.open.value
    )
    notes: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[dt.datetime | None]
    source: Mapped[str] = mapped_column(Text, server_default="chat")


class CoachLogKind(enum.StrEnum):
    decision = "decision"
    observation = "observation"
    plan = "plan"
    review = "review"
    note = "note"
    question = "question"


class CoachLog(Timestamps, Base):
    __tablename__ = "coach_log"
    __table_args__ = (
        Index("ix_coach_log_ts", "ts"),
        Index("ix_coach_log_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[int] = _bigid()
    ts: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    kind: Mapped[CoachLogKind] = mapped_column(_enum(CoachLogKind, "coach_log_kind"))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(server_default="{}")
    related_from: Mapped[dt.date | None] = mapped_column(Date)
    related_to: Mapped[dt.date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, server_default="chat")


class TdeeEstimate(Timestamps, Base):
    __tablename__ = "tdee_estimates"

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    avg_intake: Mapped[Decimal | None] = mapped_column(Numeric(6, 0))
    trend_change_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tdee: Mapped[Decimal | None] = mapped_column(Numeric(6, 0))
    confidence: Mapped[str] = mapped_column(Text, comment="high / medium / low / none")
    logged_days: Mapped[int] = mapped_column(SmallInteger)
    weigh_ins: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(Text, server_default="worker")


class DailyScore(Timestamps, Base):
    __tablename__ = "daily_scores"

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    recovery: Mapped[int | None] = mapped_column(SmallInteger)
    recovery_z: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    recovery_components: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    flags: Mapped[list[str]] = mapped_column(server_default="{}")
    strain: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    cardio_load: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    muscular_load: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    zone_minutes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    activities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    strain_target_low: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    strain_target_high: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    sleep_need_min: Mapped[int | None] = mapped_column(Integer)
    sleep_actual_min: Mapped[int | None] = mapped_column(Integer)
    sleep_debt_min: Mapped[int | None] = mapped_column(Integer)
    sleep_performance: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_efficiency: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_consistency: Mapped[int | None] = mapped_column(SmallInteger)
    planned_bedtime: Mapped[dt.datetime | None]
    planned_wake: Mapped[dt.datetime | None]
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    algo_version: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(Text, server_default="worker")


class JournalEntry(Timestamps, Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_entries_local_date", "local_date"),
        Index(
            "uq_journal_entries_local_date_behavior",
            "local_date",
            "behavior",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = _bigid()
    local_date: Mapped[dt.date] = mapped_column(Date)
    behavior: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="chat")
    deleted_at: Mapped[dt.datetime | None]


class AppSetting(Timestamps, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)


class NotificationSent(Base):
    __tablename__ = "notifications_sent"

    local_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    sent_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class McpAudit(Base):
    __tablename__ = "mcp_audit"
    __table_args__ = (Index("ix_mcp_audit_ts", "ts"),)

    id: Mapped[int] = _bigid()
    ts: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    tool: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, Any] | None]
    subject: Mapped[str | None] = mapped_column(Text, comment="Token subject of the caller")
    rows_returned: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
