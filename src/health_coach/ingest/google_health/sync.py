"""Pull Google Health data into raw_payloads and, through mappers, into typed tables.

Every fetch stores the untouched response first; mappers turn it into rows. Mappers can
be re-run over stored payloads (`health-coach remap google`) after a fix, so a wrong or
missing mapper never loses data. Intraday heart rate is the exception: its samples go
straight to heart_rate_samples and raw_payloads keeps a summary (see SUMMARY_ONLY).
"""

import datetime as dt
import hashlib
import json
import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from health_coach.config import get_settings
from health_coach.ingest import state
from health_coach.ingest.google_health.client import Fetcher
from health_coach.ingest.google_health.datatypes import DATA_TYPES, DataTypeSpec
from health_coach.nutrients import GH_EXCLUDED_NUTRIENTS, GH_NUTRIENT_MAP

log = logging.getLogger(__name__)

SOURCE = "google_health"


class Mapper(Protocol):
    """Writes the typed rows of one stored payload covering [start, end) (civil dates)
    and reconciles rows of that window that the payload no longer contains."""

    def __call__(
        self,
        conn: Connection,
        payload: dict[str, Any],
        spec: DataTypeSpec,
        tz: ZoneInfo,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> int: ...


def _parse_iso(s: str) -> dt.datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s).astimezone(dt.UTC)


def _parse_date(d_dict: dict[str, Any]) -> dt.date:
    return dt.date(d_dict["year"], d_dict["month"], d_dict["day"])


def _civil_date(civil: dict[str, Any] | None, fallback: dt.datetime, tz: ZoneInfo) -> dt.date:
    """Civil date the API reports (the user's own time zone at that moment), which is
    what the civil-time list filters select on; the configured zone is only a fallback."""
    if civil and civil.get("date"):
        return _parse_date(civil["date"])
    return fallback.astimezone(tz).date()


def _parse_duration_min(dur_str: str) -> int:
    val = float(dur_str.rstrip("s"))
    return round(val / 60)


def _iter_points(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if "pages" in payload:
        items: list[dict[str, Any]] = []
        for page in payload["pages"]:
            pts = page.get(key, [])
            if isinstance(pts, list):
                items.extend(pts)
        return items
    res = payload.get(key, [])
    if isinstance(res, list):
        return res
    return []


# --- Daily values: one column of daily_activity or daily_vitals per data type ----------


def _rollup_day(dp: dict[str, Any]) -> dict[str, Any] | None:
    day: dict[str, Any] | None = dp.get("civilStartTime", {}).get("date")
    return day


def _decimal(value: Any, places: int) -> Decimal | None:
    return Decimal(str(round(value, places))) if value is not None else None


def _active_minutes(dp: dict[str, Any]) -> int:
    levels = dp.get("activeMinutes", {}).get("activeMinutesRollupByActivityLevel", [])
    if any(item.get("activityLevel") in ("MODERATE", "VIGOROUS") for item in levels):
        return sum(
            int(item.get("activeMinutesSum", 0))
            for item in levels
            if item.get("activityLevel") in ("MODERATE", "VIGOROUS")
        )
    return sum(int(item.get("activeMinutesSum", 0)) for item in levels)


def _active_zone_minutes(dp: dict[str, Any]) -> int:
    azm = dp.get("activeZoneMinutes", {})
    return (
        int(azm.get("sumInFatBurnHeartZone", 0))
        + int(azm.get("sumInCardioHeartZone", 0))
        + int(azm.get("sumInPeakHeartZone", 0))
    )


def _hrv(data: dict[str, Any]) -> Decimal | None:
    val = data.get("averageHeartRateVariabilityMilliseconds")
    if val is None:
        val = data.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")
    return _decimal(val, 1)


def _skin_temp_delta(data: dict[str, Any]) -> Decimal | None:
    nightly = data.get("nightlyTemperatureCelsius")
    baseline = data.get("baselineTemperatureCelsius")
    if nightly is None or baseline is None:
        return None
    return Decimal(str(round(nightly - baseline, 2)))


@dataclass(frozen=True)
class DailyField:
    """Where a daily data type comes from in the payload and which column it fills.

    Rollups (activity) carry the day in civilStartTime and the value in the data point;
    daily summaries (vitals) nest both under `key`."""

    table: str
    column: str
    value: Callable[[dict[str, Any]], Any]
    key: str | None = None  # daily summary object; None for rollups

    def rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        points = "dataPoints" if self.key else "rollupDataPoints"
        for dp in _iter_points(payload, points):
            data = dp.get(self.key, {}) if self.key else dp
            day = data.get("date") if self.key else _rollup_day(dp)
            if not day:
                continue
            out.append({"local_date": _parse_date(day), "value": self.value(data)})
        return out

    def upsert(self) -> str:
        # Identifiers come from DAILY_FIELDS below, never from input. Unchanged days are
        # not rewritten, so updated_at (and as_of) only move when a value changes.
        t, c = self.table, self.column
        return (
            f"INSERT INTO {t} (local_date, {c}, source) "  # noqa: S608
            f"VALUES (:local_date, :value, '{SOURCE}') "
            f"ON CONFLICT (local_date) DO UPDATE SET {c} = EXCLUDED.{c}, updated_at = now() "
            f"WHERE {t}.{c} IS DISTINCT FROM EXCLUDED.{c}"
        )


def _count(field: str, default: Any = 0) -> Callable[[dict[str, Any]], Any]:
    def value(dp: dict[str, Any]) -> Any:
        v = dp.get(field, {}).get("countSum")
        return int(v) if v is not None else default

    return value


DAILY_FIELDS: dict[str, DailyField] = {
    "steps": DailyField("daily_activity", "steps", _count("steps")),
    "distance": DailyField(
        "daily_activity",
        "distance_km",
        lambda dp: (
            Decimal(str(round(int(mm) / 1_000_000, 3)))
            if (mm := dp.get("distance", {}).get("millimetersSum")) is not None
            else None
        ),
    ),
    "floors": DailyField("daily_activity", "floors", _count("floors")),
    "active-minutes": DailyField("daily_activity", "active_minutes", _active_minutes),
    "active-zone-minutes": DailyField(
        "daily_activity", "active_zone_minutes", _active_zone_minutes
    ),
    "total-calories": DailyField(
        "daily_activity",
        "calories_out",
        lambda dp: (
            round(kcal) if (kcal := dp.get("totalCalories", {}).get("kcalSum")) is not None else 0
        ),
    ),
    "daily-resting-heart-rate": DailyField(
        "daily_vitals",
        "resting_hr",
        lambda d: int(d["beatsPerMinute"]) if "beatsPerMinute" in d else None,
        key="dailyRestingHeartRate",
    ),
    "daily-heart-rate-variability": DailyField(
        "daily_vitals", "hrv_rmssd_ms", _hrv, key="dailyHeartRateVariability"
    ),
    "daily-oxygen-saturation": DailyField(
        "daily_vitals",
        "spo2_avg",
        lambda d: _decimal(d.get("averagePercentage"), 1),
        key="dailyOxygenSaturation",
    ),
    "daily-respiratory-rate": DailyField(
        "daily_vitals",
        "breathing_rate",
        lambda d: _decimal(d.get("breathsPerMinute"), 1),
        key="dailyRespiratoryRate",
    ),
    "daily-sleep-temperature-derivations": DailyField(
        "daily_vitals", "skin_temp_delta", _skin_temp_delta, key="dailySleepTemperatureDerivations"
    ),
    "daily-vo2-max": DailyField(
        "daily_vitals",
        "cardio_fitness",
        lambda d: _decimal(d.get("vo2Max"), 1),
        key="dailyVo2Max",
    ),
}


def _daily_mapper(field: DailyField) -> Mapper:
    def mapper(
        conn: Connection,
        payload: dict[str, Any],
        spec: DataTypeSpec,
        tz: ZoneInfo,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> int:
        rows = field.rows(payload)
        if rows:
            conn.execute(text(field.upsert()), rows)
        return len(rows)

    return mapper


def _map_heart_rate(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    # Samples are never removed on re-sync: the list filter selects them by the user's
    # civil time, which need not match a window in the configured zone (travel), and a
    # deleted sample is not something the watch does.
    rows = []
    for dp in _iter_points(payload, "dataPoints"):
        hr = dp.get("heartRate", {})
        pt = hr.get("sampleTime", {}).get("physicalTime")
        if not pt:
            continue
        rows.append({"ts": _parse_iso(pt), "bpm": int(hr["beatsPerMinute"]), "source": SOURCE})
    if rows:
        # A day at 5-second sampling is ~17,000 samples: one pipelined executemany instead
        # of a round trip each, and samples already stored are left alone.
        conn.execute(
            text(
                "INSERT INTO heart_rate_samples (ts, bpm, source) "
                "VALUES (:ts, :bpm, :source) "
                "ON CONFLICT (ts) DO UPDATE SET bpm = EXCLUDED.bpm "
                "WHERE heart_rate_samples.bpm IS DISTINCT FROM EXCLUDED.bpm"
            ),
            rows,
        )
    return len(rows)


def _map_sleep(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    seen_ids: list[str] = []
    count = 0
    for dp in _iter_points(payload, "dataPoints"):
        s = dp.get("sleep", {})
        interval = s.get("interval", {})
        st = interval.get("startTime")
        et = interval.get("endTime")
        if not st or not et:
            continue
        start_ts = _parse_iso(st)
        end_ts = _parse_iso(et)
        ext_id = dp.get("name") or f"sleep:{start_ts.isoformat()}"
        seen_ids.append(ext_id)
        local_date = _civil_date(interval.get("civilEndTime"), end_ts, tz)

        summary = s.get("summary", {})
        dur_val = summary.get("minutesAsleep")
        duration_min = (
            int(dur_val) if dur_val is not None else round((end_ts - start_ts).total_seconds() / 60)
        )
        tib_val = summary.get("minutesInSleepPeriod")
        time_in_bed_min = (
            int(tib_val) if tib_val is not None else round((end_ts - start_ts).total_seconds() / 60)
        )
        efficiency = round(duration_min * 100 / time_in_bed_min) if time_in_bed_min > 0 else None

        minutes_deep = minutes_light = minutes_rem = minutes_awake = None
        for stg in summary.get("stagesSummary", []):
            stype = stg.get("type")
            mins = int(stg.get("minutes", 0))
            if stype == "DEEP":
                minutes_deep = mins
            elif stype == "LIGHT":
                minutes_light = mins
            elif stype == "REM":
                minutes_rem = mins
            elif stype == "AWAKE":
                minutes_awake = mins
        if minutes_awake is None and summary.get("minutesAwake") is not None:
            minutes_awake = int(summary["minutesAwake"])

        metadata = s.get("metadata", {})
        if "mainSleep" in metadata:
            is_main = bool(metadata["mainSleep"])
        elif "nap" in metadata:
            is_main = not bool(metadata["nap"])
        else:
            is_main = True

        session_id = conn.execute(
            text(
                "INSERT INTO sleep_sessions ("
                "    external_id, start_ts, end_ts, local_date, duration_min, time_in_bed_min,"
                "    efficiency, minutes_deep, minutes_light, minutes_rem, minutes_awake,"
                "    sleep_score, is_main, source"
                ") "
                "VALUES ("
                "    :external_id, :start_ts, :end_ts, :local_date, "
                "    :duration_min, :time_in_bed_min, "
                "    :efficiency, :minutes_deep, :minutes_light, :minutes_rem, :minutes_awake,"
                "    NULL, :is_main, :source"
                ") "
                "ON CONFLICT (source, external_id) DO UPDATE SET "
                "    start_ts = EXCLUDED.start_ts,"
                "    end_ts = EXCLUDED.end_ts,"
                "    local_date = EXCLUDED.local_date,"
                "    duration_min = EXCLUDED.duration_min,"
                "    time_in_bed_min = EXCLUDED.time_in_bed_min,"
                "    efficiency = EXCLUDED.efficiency,"
                "    minutes_deep = EXCLUDED.minutes_deep,"
                "    minutes_light = EXCLUDED.minutes_light,"
                "    minutes_rem = EXCLUDED.minutes_rem,"
                "    minutes_awake = EXCLUDED.minutes_awake,"
                "    is_main = EXCLUDED.is_main,"
                "    updated_at = now() "
                "WHERE (sleep_sessions.start_ts, sleep_sessions.end_ts, sleep_sessions.local_date,"
                "       sleep_sessions.duration_min, sleep_sessions.time_in_bed_min,"
                "       sleep_sessions.efficiency, sleep_sessions.minutes_deep,"
                "       sleep_sessions.minutes_light, sleep_sessions.minutes_rem,"
                "       sleep_sessions.minutes_awake, sleep_sessions.is_main) "
                "IS DISTINCT FROM (EXCLUDED.start_ts, EXCLUDED.end_ts, EXCLUDED.local_date,"
                "       EXCLUDED.duration_min, EXCLUDED.time_in_bed_min, EXCLUDED.efficiency,"
                "       EXCLUDED.minutes_deep, EXCLUDED.minutes_light, EXCLUDED.minutes_rem,"
                "       EXCLUDED.minutes_awake, EXCLUDED.is_main) "
                "RETURNING id"
            ),
            {
                "external_id": ext_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "local_date": local_date,
                "duration_min": duration_min,
                "time_in_bed_min": time_in_bed_min,
                "efficiency": efficiency,
                "minutes_deep": minutes_deep,
                "minutes_light": minutes_light,
                "minutes_rem": minutes_rem,
                "minutes_awake": minutes_awake,
                "is_main": is_main,
                "source": SOURCE,
            },
        ).scalar()
        if session_id is None:  # unchanged, so the upsert returned nothing
            session_id = conn.execute(
                text("SELECT id FROM sleep_sessions WHERE source = :s AND external_id = :e"),
                {"s": SOURCE, "e": ext_id},
            ).scalar_one()

        stages = [
            {
                "session_id": session_id,
                "start_ts": _parse_iso(stg["startTime"]),
                "end_ts": _parse_iso(stg["endTime"]),
                "stage": stg.get("type", "").lower(),
            }
            for stg in s.get("stages", [])
        ]
        conn.execute(
            text(
                "DELETE FROM sleep_stages WHERE session_id = :session_id "
                "AND start_ts <> ALL(:starts)"
            ),
            {"session_id": session_id, "starts": [st["start_ts"] for st in stages]},
        )
        if stages:
            conn.execute(
                text(
                    "INSERT INTO sleep_stages (session_id, start_ts, end_ts, stage) "
                    "VALUES (:session_id, :start_ts, :end_ts, :stage) "
                    "ON CONFLICT (session_id, start_ts) DO UPDATE SET "
                    "    end_ts = EXCLUDED.end_ts, stage = EXCLUDED.stage "
                    "WHERE (sleep_stages.end_ts, sleep_stages.stage) "
                    "IS DISTINCT FROM (EXCLUDED.end_ts, EXCLUDED.stage)"
                ),
                stages,
            )
        count += 1

    if start is not None and end is not None:
        if seen_ids:
            conn.execute(
                text(
                    "DELETE FROM sleep_sessions WHERE source = :s "
                    "AND local_date >= :start AND local_date < :end "
                    "AND NOT (external_id = ANY(:seen))"
                ),
                {"s": SOURCE, "start": start, "end": end, "seen": seen_ids},
            )
        else:
            conn.execute(
                text(
                    "DELETE FROM sleep_sessions WHERE source = :s "
                    "AND local_date >= :start AND local_date < :end"
                ),
                {"s": SOURCE, "start": start, "end": end},
            )
    return count


def _map_exercise(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    seen_ids: list[str] = []
    count = 0
    for dp in _iter_points(payload, "dataPoints"):
        ex = dp.get("exercise", {})
        interval = ex.get("interval", {})
        st = interval.get("startTime")
        et = interval.get("endTime")
        if not st or not et:
            continue
        start_ts = _parse_iso(st)
        end_ts = _parse_iso(et)
        ext_id = dp.get("name") or f"exercise:{start_ts.isoformat()}"
        seen_ids.append(ext_id)
        local_date = _civil_date(interval.get("civilStartTime"), start_ts, tz)

        act_type = ex.get("exerciseType", "workout").lower()
        dur_str = ex.get("activeDuration")
        duration_min = (
            _parse_duration_min(dur_str)
            if dur_str
            else round((end_ts - start_ts).total_seconds() / 60)
        )
        ms = ex.get("metricsSummary", {})
        avg_hr = (
            int(ms["averageHeartRateBeatsPerMinute"])
            if ms.get("averageHeartRateBeatsPerMinute") is not None
            else None
        )
        calories = round(ms["caloriesKcal"]) if ms.get("caloriesKcal") is not None else None
        dist_mm = ms.get("distanceMillimeters")
        dist_km = Decimal(str(round(dist_mm / 1_000_000, 3))) if dist_mm is not None else None

        hr_zone_mins: dict[str, int] | None = None
        if "heartRateZoneDurations" in ms:
            durations = ms["heartRateZoneDurations"]
            hr_zone_mins = {}
            for z_key in ("lightTime", "moderateTime", "vigorousTime", "peakTime"):
                if z_key in durations:
                    zone_label = z_key.removesuffix("Time")
                    hr_zone_mins[zone_label] = _parse_duration_min(durations[z_key])

        notes = ex.get("notes")
        conn.execute(
            text(
                "INSERT INTO exercise_sessions ("
                "    external_id, start_ts, end_ts, local_date, activity_type, duration_min,"
                "    avg_hr, max_hr, calories, distance_km, hr_zone_minutes, rpe, notes,"
                "    source, deleted_at"
                ") "
                "VALUES ("
                "    :external_id, :start_ts, :end_ts, :local_date, :activity_type, :duration_min,"
                "    :avg_hr, NULL, :calories, :distance_km, CAST(:hr_zone_minutes AS jsonb), NULL,"
                "    :notes, :source, NULL"
                ") "
                "ON CONFLICT (source, external_id) DO UPDATE SET "
                "    start_ts = EXCLUDED.start_ts,"
                "    end_ts = EXCLUDED.end_ts,"
                "    local_date = EXCLUDED.local_date,"
                "    activity_type = EXCLUDED.activity_type,"
                "    duration_min = EXCLUDED.duration_min,"
                "    avg_hr = EXCLUDED.avg_hr,"
                "    calories = EXCLUDED.calories,"
                "    distance_km = EXCLUDED.distance_km,"
                "    hr_zone_minutes = EXCLUDED.hr_zone_minutes,"
                "    notes = EXCLUDED.notes,"
                "    deleted_at = NULL,"
                "    updated_at = now() "
                "WHERE exercise_sessions.deleted_at IS NOT NULL "
                "   OR (exercise_sessions.start_ts, exercise_sessions.end_ts,"
                "       exercise_sessions.local_date, exercise_sessions.activity_type,"
                "       exercise_sessions.duration_min, exercise_sessions.avg_hr,"
                "       exercise_sessions.calories, exercise_sessions.distance_km,"
                "       exercise_sessions.hr_zone_minutes, exercise_sessions.notes) "
                "   IS DISTINCT FROM (EXCLUDED.start_ts, EXCLUDED.end_ts, EXCLUDED.local_date,"
                "       EXCLUDED.activity_type, EXCLUDED.duration_min, EXCLUDED.avg_hr,"
                "       EXCLUDED.calories, EXCLUDED.distance_km, EXCLUDED.hr_zone_minutes,"
                "       EXCLUDED.notes)"
            ),
            {
                "external_id": ext_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "local_date": local_date,
                "activity_type": act_type,
                "duration_min": duration_min,
                "avg_hr": avg_hr,
                "calories": calories,
                "distance_km": dist_km,
                "hr_zone_minutes": json.dumps(hr_zone_mins) if hr_zone_mins else None,
                "notes": notes,
                "source": SOURCE,
            },
        )
        count += 1

    if start is not None and end is not None:
        if seen_ids:
            conn.execute(
                text(
                    "UPDATE exercise_sessions SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND local_date >= :start AND local_date < :end "
                    "AND NOT (external_id = ANY(:seen))"
                ),
                {"s": SOURCE, "start": start, "end": end, "seen": seen_ids},
            )
        else:
            conn.execute(
                text(
                    "UPDATE exercise_sessions SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND local_date >= :start AND local_date < :end"
                ),
                {"s": SOURCE, "start": start, "end": end},
            )
    return count


def _map_weight(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    seen_ids: list[str] = []
    count = 0
    for dp in _iter_points(payload, "dataPoints"):
        w = dp.get("weight", {})
        pt = w.get("sampleTime", {}).get("physicalTime")
        if not pt:
            continue
        ts = _parse_iso(pt)
        ext_id = dp.get("name") or f"weight:{ts.isoformat()}"
        seen_ids.append(ext_id)
        local_date = _civil_date(w.get("sampleTime", {}).get("civilTime"), ts, tz)
        grams = w.get("weightGrams")
        weight_kg = Decimal(str(round(grams / 1000, 2))) if grams is not None else None
        conn.execute(
            text(
                "INSERT INTO body_metrics ("
                "    source, external_id, ts, local_date, weight_kg, deleted_at"
                ") "
                "VALUES ("
                "    :source, :external_id, :ts, :local_date, :weight_kg, NULL"
                ") "
                "ON CONFLICT (source, external_id) DO UPDATE SET "
                "    ts = EXCLUDED.ts,"
                "    local_date = EXCLUDED.local_date,"
                "    weight_kg = EXCLUDED.weight_kg,"
                "    deleted_at = NULL,"
                "    updated_at = now() "
                "WHERE body_metrics.deleted_at IS NOT NULL "
                "   OR (body_metrics.ts, body_metrics.local_date, body_metrics.weight_kg) "
                "   IS DISTINCT FROM (EXCLUDED.ts, EXCLUDED.local_date, EXCLUDED.weight_kg)"
            ),
            {
                "source": SOURCE,
                "external_id": ext_id,
                "ts": ts,
                "local_date": local_date,
                "weight_kg": weight_kg,
            },
        )
        count += 1

    if start is not None and end is not None:
        if seen_ids:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND weight_kg IS NOT NULL "
                    "AND local_date >= :start AND local_date < :end "
                    "AND NOT (external_id = ANY(:seen))"
                ),
                {"s": SOURCE, "start": start, "end": end, "seen": seen_ids},
            )
        else:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND weight_kg IS NOT NULL "
                    "AND local_date >= :start AND local_date < :end"
                ),
                {"s": SOURCE, "start": start, "end": end},
            )
    return count


def _map_body_fat(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    seen_ids: list[str] = []
    count = 0
    for dp in _iter_points(payload, "dataPoints"):
        bf = dp.get("bodyFat", {})
        pt = bf.get("sampleTime", {}).get("physicalTime")
        if not pt:
            continue
        ts = _parse_iso(pt)
        ext_id = dp.get("name") or f"body-fat:{ts.isoformat()}"
        seen_ids.append(ext_id)
        local_date = _civil_date(bf.get("sampleTime", {}).get("civilTime"), ts, tz)
        pct = bf.get("percentage")
        body_fat_pct = Decimal(str(round(pct, 1))) if pct is not None else None
        conn.execute(
            text(
                "INSERT INTO body_metrics ("
                "    source, external_id, ts, local_date, body_fat_pct, deleted_at"
                ") "
                "VALUES ("
                "    :source, :external_id, :ts, :local_date, :body_fat_pct, NULL"
                ") "
                "ON CONFLICT (source, external_id) DO UPDATE SET "
                "    ts = EXCLUDED.ts,"
                "    local_date = EXCLUDED.local_date,"
                "    body_fat_pct = EXCLUDED.body_fat_pct,"
                "    deleted_at = NULL,"
                "    updated_at = now() "
                "WHERE body_metrics.deleted_at IS NOT NULL "
                "   OR (body_metrics.ts, body_metrics.local_date, body_metrics.body_fat_pct) "
                "   IS DISTINCT FROM (EXCLUDED.ts, EXCLUDED.local_date, EXCLUDED.body_fat_pct)"
            ),
            {
                "source": SOURCE,
                "external_id": ext_id,
                "ts": ts,
                "local_date": local_date,
                "body_fat_pct": body_fat_pct,
            },
        )
        count += 1

    if start is not None and end is not None:
        if seen_ids:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND body_fat_pct IS NOT NULL "
                    "AND local_date >= :start AND local_date < :end "
                    "AND NOT (external_id = ANY(:seen))"
                ),
                {"s": SOURCE, "start": start, "end": end, "seen": seen_ids},
            )
        else:
            conn.execute(
                text(
                    "UPDATE body_metrics SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND body_fat_pct IS NOT NULL "
                    "AND local_date >= :start AND local_date < :end"
                ),
                {"s": SOURCE, "start": start, "end": end},
            )
    return count


def _map_nutrition_log(
    conn: Connection,
    payload: dict[str, Any],
    spec: DataTypeSpec,
    tz: ZoneInfo,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> int:
    seen_ids: list[str] = []
    count = 0
    for dp in _iter_points(payload, "dataPoints"):
        nl = dp.get("nutritionLog", {})
        interval = nl.get("interval", {})
        st = interval.get("startTime")
        if not st:
            continue
        ts = _parse_iso(st)
        ext_id = dp.get("name") or f"nutrition-log:{ts.isoformat()}"
        seen_ids.append(ext_id)
        local_date = _civil_date(interval.get("civilStartTime"), ts, tz)

        meal_raw = nl.get("mealType", "ANYTIME").upper()
        if meal_raw in ("BREAKFAST", "BEFORE_BREAKFAST"):
            meal = "breakfast"
        elif meal_raw in ("LUNCH", "BEFORE_LUNCH"):
            meal = "lunch"
        elif meal_raw in ("DINNER", "BEFORE_DINNER", "AFTER_DINNER"):
            meal = "dinner"
        elif meal_raw == "SNACK":
            meal = "snack"
        else:
            meal = "other"

        description = nl.get("foodDisplayName") or "Food"
        energy = nl.get("energy", {})
        kcal = Decimal(str(round(energy.get("kcal", 0), 1)))
        carbs = Decimal(str(round(nl.get("totalCarbohydrate", {}).get("grams", 0), 1)))
        fat = Decimal(str(round(nl.get("totalFat", {}).get("grams", 0), 1)))
        protein = Decimal("0.0")
        fiber = None
        micros: dict[str, float] = {}
        for n in nl.get("nutrients", []):
            nutr = n.get("nutrient")
            q_g = n.get("quantity", {}).get("grams", 0)
            if nutr == "PROTEIN":
                protein = Decimal(str(round(q_g, 1)))
            elif nutr == "DIETARY_FIBER":
                fiber = Decimal(str(round(q_g, 1)))
            elif nutr in GH_EXCLUDED_NUTRIENTS:
                continue
            elif nutr in GH_NUTRIENT_MAP:
                k = GH_NUTRIENT_MAP[nutr]
                try:
                    q_f = float(q_g)
                except (ValueError, TypeError):
                    continue
                if q_f > 0:
                    # FOLATE and FOLIC_ACID both map to folate and one may already
                    # include the other: keep the larger value instead of adding them.
                    micros[k] = round(max(micros.get(k, 0.0), q_f), 8)

        serving = nl.get("serving", {})
        grams: Decimal | None = None
        if serving:
            amt = serving.get("amount")
            unit = str(serving.get("foodMeasurementUnitDisplayName", "")).lower()
            if unit in ("g", "gram", "grams") and amt is not None:
                grams = Decimal(str(round(amt, 1)))

        food_micros_100g: dict[str, float] | None = None
        if micros:
            if grams and grams > 0:
                m_ratio = 100.0 / float(grams)
                food_micros_100g = {k: round(v * m_ratio, 8) for k, v in micros.items()}
            else:
                food_micros_100g = dict(micros)

        food_id = None
        food_ref = nl.get("food")
        food_obj = dp.get("food")
        food_ext_id = (
            food_ref
            if isinstance(food_ref, str)
            else (food_obj.get("name") if isinstance(food_obj, dict) else None)
        )
        if food_ext_id:
            existing = conn.execute(
                text(
                    "SELECT id FROM foods WHERE source = 'google_health' AND external_id = :ext_id"
                ),
                {"ext_id": food_ext_id},
            ).scalar()
            if existing is not None:
                food_id = existing
                if food_micros_100g:
                    conn.execute(
                        text(
                            "UPDATE foods SET micros_100g = CAST(:micros_100g AS jsonb) "
                            "WHERE id = :id AND micros_100g IS NULL"
                        ),
                        {"micros_100g": json.dumps(food_micros_100g), "id": food_id},
                    )
            else:
                food_name = (
                    food_obj.get("displayName") if isinstance(food_obj, dict) else None
                ) or description
                brand = food_obj.get("brand") if isinstance(food_obj, dict) else None
                def_serving = grams or Decimal("100.0")
                if grams and grams > 0:
                    ratio = Decimal("100") / grams
                    k100 = round(kcal * ratio, 1)
                    p100 = round(protein * ratio, 1)
                    c100 = round(carbs * ratio, 1)
                    f100 = round(fat * ratio, 1)
                    fib100 = round(fiber * ratio, 1) if fiber is not None else None
                else:
                    k100, p100, c100, f100, fib100 = kcal, protein, carbs, fat, fiber
                food_id = conn.execute(
                    text(
                        "INSERT INTO foods (name, brand, kcal_100g, protein_100g, carbs_100g, "
                        "fat_100g, fiber_100g, default_serving_g, source, external_id, "
                        "micros_100g) "
                        "VALUES (:name, :brand, :k100, :p100, :c100, :f100, :fib100, "
                        ":def_serving, 'google_health', :ext_id, CAST(:micros_100g AS jsonb)) "
                        "RETURNING id"
                    ),
                    {
                        "name": food_name,
                        "brand": brand,
                        "k100": k100,
                        "p100": p100,
                        "c100": c100,
                        "f100": f100,
                        "fib100": fib100,
                        "def_serving": def_serving,
                        "ext_id": food_ext_id,
                        "micros_100g": json.dumps(food_micros_100g) if food_micros_100g else None,
                    },
                ).scalar_one()

        conn.execute(
            text(
                "INSERT INTO nutrition_entries ("
                "    source, external_id, ts, local_date, meal, food_id, description,"
                "    grams, kcal, protein_g, carbs_g, fat_g, fiber_g, confidence, "
                "    deleted_at, micros"
                ") "
                "VALUES ("
                "    :source, :external_id, :ts, :local_date, :meal, :food_id, :description,"
                "    :grams, :kcal, :protein_g, :carbs_g, :fat_g, :fiber_g, 'exact', "
                "    NULL, CAST(:micros AS jsonb)"
                ") "
                "ON CONFLICT (source, external_id) DO UPDATE SET "
                "    ts = EXCLUDED.ts,"
                "    local_date = EXCLUDED.local_date,"
                "    meal = EXCLUDED.meal,"
                "    food_id = EXCLUDED.food_id,"
                "    description = EXCLUDED.description,"
                "    grams = EXCLUDED.grams,"
                "    kcal = EXCLUDED.kcal,"
                "    protein_g = EXCLUDED.protein_g,"
                "    carbs_g = EXCLUDED.carbs_g,"
                "    fat_g = EXCLUDED.fat_g,"
                "    fiber_g = EXCLUDED.fiber_g,"
                "    confidence = EXCLUDED.confidence,"
                "    micros = EXCLUDED.micros,"
                "    deleted_at = NULL,"
                "    updated_at = now() "
                "WHERE nutrition_entries.deleted_at IS NOT NULL "
                "   OR (nutrition_entries.ts, nutrition_entries.local_date,"
                "       nutrition_entries.meal, nutrition_entries.food_id,"
                "       nutrition_entries.description, nutrition_entries.grams,"
                "       nutrition_entries.kcal, nutrition_entries.protein_g,"
                "       nutrition_entries.carbs_g, nutrition_entries.fat_g,"
                "       nutrition_entries.fiber_g, nutrition_entries.confidence,"
                "       nutrition_entries.micros) "
                "   IS DISTINCT FROM (EXCLUDED.ts, EXCLUDED.local_date, EXCLUDED.meal,"
                "       EXCLUDED.food_id, EXCLUDED.description, EXCLUDED.grams, EXCLUDED.kcal,"
                "       EXCLUDED.protein_g, EXCLUDED.carbs_g, EXCLUDED.fat_g, EXCLUDED.fiber_g,"
                "       EXCLUDED.confidence, EXCLUDED.micros)"
            ),
            {
                "source": SOURCE,
                "external_id": ext_id,
                "ts": ts,
                "local_date": local_date,
                "meal": meal,
                "food_id": food_id,
                "description": description,
                "grams": grams,
                "kcal": kcal,
                "protein_g": protein,
                "carbs_g": carbs,
                "fat_g": fat,
                "fiber_g": fiber,
                "micros": json.dumps(micros) if micros else None,
            },
        )
        count += 1

    if start is not None and end is not None:
        if seen_ids:
            conn.execute(
                text(
                    "UPDATE nutrition_entries SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND local_date >= :start AND local_date < :end "
                    "AND NOT (external_id = ANY(:seen))"
                ),
                {"s": SOURCE, "start": start, "end": end, "seen": seen_ids},
            )
        else:
            conn.execute(
                text(
                    "UPDATE nutrition_entries SET deleted_at = now() WHERE source = :s "
                    "AND deleted_at IS NULL AND local_date >= :start AND local_date < :end"
                ),
                {"s": SOURCE, "start": start, "end": end},
            )
    return count


MAPPERS: dict[str, Mapper] = {
    **{name: _daily_mapper(field) for name, field in DAILY_FIELDS.items()},
    "heart-rate": _map_heart_rate,
    "sleep": _map_sleep,
    "exercise": _map_exercise,
    "weight": _map_weight,
    "body-fat": _map_body_fat,
    "nutrition-log": _map_nutrition_log,
}


def chunks(start: dt.date, end: dt.date, max_days: int) -> Iterator[tuple[dt.date, dt.date]]:
    """Split [start, end) into pieces of at most max_days."""
    cursor = start
    while cursor < end:
        nxt = min(cursor + dt.timedelta(days=max_days), end)
        yield cursor, nxt
        cursor = nxt


# A re-fetched payload that has not changed keeps its stored value (no new TOAST copy of
# a large document) and its updated_at; fetched_at always records the fetch.
_UPSERT_RAW = """
INSERT INTO raw_payloads (source, data_type, range_start, range_end, payload, fetched_at)
VALUES (:source, :data_type, :start, :end, CAST(:payload AS jsonb), now())
ON CONFLICT (source, data_type, range_start, range_end) DO UPDATE SET
    payload = CASE WHEN raw_payloads.payload IS DISTINCT FROM EXCLUDED.payload
                   THEN EXCLUDED.payload ELSE raw_payloads.payload END,
    updated_at = CASE WHEN raw_payloads.payload IS DISTINCT FROM EXCLUDED.payload
                      THEN now() ELSE raw_payloads.updated_at END,
    fetched_at = now()
"""

# Intraday heart rate is the bulk of all payloads (a day at one sample a minute is
# ~170 kB of JSONB, re-fetched every 30 minutes) and heart_rate_samples already holds
# every sample, so by default only a summary is kept (HC_GOOGLE_RAW_HEART_RATE=true keeps
# the full payload). `remap` skips summaries.
SUMMARY_ONLY = {"heart-rate"}


def _stored_payload(spec: DataTypeSpec, payload: dict[str, Any], canonical: str) -> str:
    if spec.name not in SUMMARY_ONLY or get_settings().google_raw_heart_rate:
        return canonical
    summary = {
        "summary_only": True,
        "points": len(_iter_points(payload, "dataPoints")),
        "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    return json.dumps(summary)


def _bounds(day: dt.date, tz: ZoneInfo) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), tz)


def store_and_map(
    conn: Connection,
    spec: DataTypeSpec,
    start: dt.date,
    end: dt.date,
    payload: dict[str, Any],
    tz: ZoneInfo,
) -> int:
    conn.execute(
        text(_UPSERT_RAW),
        {
            "source": SOURCE,
            "data_type": spec.name,
            "start": _bounds(start, tz),
            "end": _bounds(end, tz),
            "payload": _stored_payload(spec, payload, json.dumps(payload)),
        },
    )
    mapper = MAPPERS.get(spec.name)
    if mapper is None:
        return 0
    return mapper(conn, payload, spec, tz, start=start, end=end)


@dataclass
class TypeResult:
    data_type: str
    chunks: int
    rows: int


def sync_type(
    fetcher: Fetcher, engine: Engine, spec: DataTypeSpec, start: dt.date, end: dt.date
) -> TypeResult:
    """Fetch [start, end) for one data type, chunked to the API's range limit."""
    tz = get_settings().tz
    done = rows = 0
    for chunk_start, chunk_end in chunks(start, end, spec.max_range_days):
        payload = fetcher.fetch(spec, chunk_start, chunk_end)
        with engine.begin() as conn:
            rows += store_and_map(conn, spec, chunk_start, chunk_end, payload, tz)
        done += 1
    with engine.begin() as conn:
        state.mark_success(conn, SOURCE, spec.name)
    return TypeResult(spec.name, done, rows)


def window(days_back: int, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """[today - days_back, tomorrow): includes today, which is still filling up."""
    today = today or dt.datetime.now(get_settings().tz).date()
    return today - dt.timedelta(days=days_back), today + dt.timedelta(days=1)


def backfill(
    fetcher: Fetcher,
    engine: Engine,
    since: dt.date,
    specs: Sequence[DataTypeSpec] = DATA_TYPES,
    today: dt.date | None = None,
    on_error: Callable[[DataTypeSpec, Exception], None] | None = None,
) -> list[TypeResult]:
    """Fetch history from `since`, resumable: progress per data type is kept in
    sync_state (data_type '<name>:backfill', cursor = first day not yet fetched). Types with
    `backfill_days` start no earlier than that many days ago."""
    tz = get_settings().tz
    end = (today or dt.datetime.now(tz).date()) + dt.timedelta(days=1)
    results = []
    for spec in specs:
        key = f"{spec.name}:backfill"
        with engine.connect() as conn:
            cursor = conn.execute(
                text("SELECT cursor FROM sync_state WHERE source = :s AND data_type = :t"),
                {"s": SOURCE, "t": key},
            ).scalar()
        start = max(since, dt.date.fromisoformat(cursor)) if cursor else since
        if spec.backfill_days is not None:
            start = max(start, end - dt.timedelta(days=spec.backfill_days))
        done = rows = 0
        try:
            for chunk_start, chunk_end in chunks(start, end, spec.max_range_days):
                payload = fetcher.fetch(spec, chunk_start, chunk_end)
                with engine.begin() as conn:
                    rows += store_and_map(conn, spec, chunk_start, chunk_end, payload, tz)
                    state.mark_success(conn, SOURCE, key, cursor=chunk_end.isoformat())
                done += 1
        except Exception as exc:
            log.exception("backfill of %s stopped; rerun to resume", spec.name)
            if on_error is None:
                raise
            on_error(spec, exc)
        results.append(TypeResult(spec.name, done, rows))
    return results


def remap(engine: Engine, data_types: Sequence[str] | None = None) -> dict[str, int]:
    """Re-run mappers over stored raw payloads."""
    tz = get_settings().tz
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT data_type, range_start, range_end, payload FROM raw_payloads "
                "WHERE source = :s ORDER BY data_type, range_start"
            ),
            {"s": SOURCE},
        ).all()
        by_name = {spec.name: spec for spec in DATA_TYPES}
        for row in rows:
            if data_types and row.data_type not in data_types:
                continue
            spec = by_name.get(row.data_type)
            mapper = MAPPERS.get(row.data_type)
            if spec is None or mapper is None or row.payload.get("summary_only"):
                continue
            start = row.range_start.astimezone(tz).date()
            end = row.range_end.astimezone(tz).date()
            cnt = mapper(conn, row.payload, spec, tz, start=start, end=end)
            counts[row.data_type] = counts.get(row.data_type, 0) + cnt
    return counts
