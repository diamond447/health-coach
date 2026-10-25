"""Push notifications for daily recovery and bedtime reminders."""

import datetime as dt
import logging
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text

from health_coach.analytics.scores import recovery_zone
from health_coach.config import get_settings
from health_coach.notify.ntfy import NtfyClient

log = logging.getLogger(__name__)

TEMPLATES: dict[str, dict[str, Any]] = {
    "en": {
        "morning_title": "Recovery {recovery} % · {zone}",
        "morning_body": "Strain target {target} · sleep {perf} % ({duration}){flags}",
        "bedtime_title": "Time for bed",
        "bedtime_body": "Bedtime at {bedtime}, alarm {wake} · need {need}",
        "zones": {"green": "green", "yellow": "yellow", "red": "red"},
        "flags": {
            "illness": "illness",
            "temperature": "temperature",
            "low_spo2": "low SpO2",
        },
    },
    "cs": {
        "morning_title": "Recovery {recovery} % · {zone}",
        "morning_body": "Strain dnes {target} · spánek {perf} % ({duration}){flags}",
        "bedtime_title": "Čas jít spát",
        "bedtime_body": "Jdi spát ve {bedtime}, budík {wake} · potřeba {need}",
        "zones": {"green": "zelená", "yellow": "žlutá", "red": "červená"},
        "flags": {
            "illness": "nemoc",
            "temperature": "teplota",
            "low_spo2": "nízké SpO2",
        },
    },
}


def _fmt_duration(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    h = minutes // 60
    m = minutes % 60
    return f"{h} h {m:02d} min"


def _fmt_time(t: dt.datetime | None, tz: ZoneInfo) -> str:
    if t is None:
        return "-"
    local_t = t.astimezone(tz) if t.tzinfo else t.replace(tzinfo=tz)
    return f"{local_t.hour}:{local_t.minute:02d}"


def _fmt_decimal(val: float | Decimal | None, lang: str, decimals: int = 1) -> str:
    if val is None:
        return "-"
    s = f"{float(val):.{decimals}f}"
    return s.replace(".", ",") if lang == "cs" else s


def format_morning_recovery(
    recovery: int,
    strain_target_low: float | Decimal | None,
    strain_target_high: float | Decimal | None,
    sleep_performance: int | None,
    sleep_actual_min: int | None,
    flags: list[str] | None = None,
    lang: str = "en",
) -> tuple[str, str]:
    tmpl = TEMPLATES.get(lang, TEMPLATES["en"])
    zone_raw = recovery_zone(recovery)
    zone_str = tmpl["zones"].get(zone_raw, zone_raw)

    title = tmpl["morning_title"].format(recovery=recovery, zone=zone_str)

    if strain_target_low is not None and strain_target_high is not None:
        target_str = (
            f"{_fmt_decimal(strain_target_low, lang)}\u2013{_fmt_decimal(strain_target_high, lang)}"
        )
    else:
        target_str = "-"

    perf_str = str(sleep_performance) if sleep_performance is not None else "-"
    duration_str = _fmt_duration(sleep_actual_min)

    flags_str = ""
    if flags:
        translated = [tmpl["flags"].get(f, f) for f in flags]
        flags_str = f" · {', '.join(translated)}"

    body = tmpl["morning_body"].format(
        target=target_str,
        perf=perf_str,
        duration=duration_str,
        flags=flags_str,
    )
    return title, body


def format_bedtime_reminder(
    planned_bedtime: dt.datetime,
    planned_wake: dt.datetime | None,
    sleep_need_min: int | None,
    tz: ZoneInfo,
    lang: str = "en",
) -> tuple[str, str]:
    tmpl = TEMPLATES.get(lang, TEMPLATES["en"])
    title = tmpl["bedtime_title"]
    bedtime_str = _fmt_time(planned_bedtime, tz)
    wake_str = _fmt_time(planned_wake, tz) if planned_wake else "-"
    need_str = _fmt_duration(sleep_need_min)
    body = tmpl["bedtime_body"].format(
        bedtime=bedtime_str,
        wake=wake_str,
        need=need_str,
    )
    return title, body


def run_morning_recovery(
    engine: Engine,
    day: dt.date | None = None,
    notifier: NtfyClient | None = None,
) -> bool:
    """Send morning recovery notification if eligible and not already sent."""
    settings = get_settings()
    tz = settings.tz
    target_date = day or dt.datetime.now(tz).date()

    with engine.begin() as conn:
        score_row = conn.execute(
            text(
                "SELECT recovery, strain_target_low, strain_target_high, "
                "       sleep_performance, sleep_actual_min, flags "
                "FROM daily_scores "
                "WHERE local_date = :d AND recovery IS NOT NULL"
            ),
            {"d": target_date},
        ).one_or_none()
        if score_row is None:
            return False

        has_sleep = conn.execute(
            text("SELECT 1 FROM sleep_sessions WHERE local_date = :d AND is_main LIMIT 1"),
            {"d": target_date},
        ).scalar_one_or_none()
        if not has_sleep:
            return False

        ins = conn.execute(
            text(
                "INSERT INTO notifications_sent (local_date, kind, sent_at) "
                "VALUES (:d, 'morning_recovery', now()) "
                "ON CONFLICT (local_date, kind) DO NOTHING "
                "RETURNING local_date"
            ),
            {"d": target_date},
        ).scalar_one_or_none()
        if ins is None:
            return False

    try:
        title, body = format_morning_recovery(
            recovery=score_row.recovery,
            strain_target_low=score_row.strain_target_low,
            strain_target_high=score_row.strain_target_high,
            sleep_performance=score_row.sleep_performance,
            sleep_actual_min=score_row.sleep_actual_min,
            flags=score_row.flags,
            lang=settings.notify_lang,
        )
        client = notifier or NtfyClient()
        client.send(title, body, priority=3, tags=["sunrise"])
        return True
    except Exception:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM notifications_sent "
                    "WHERE local_date = :d AND kind = 'morning_recovery'"
                ),
                {"d": target_date},
            )
        raise


def run_bedtime_reminder(
    engine: Engine,
    now: dt.datetime | None = None,
    notifier: NtfyClient | None = None,
) -> bool:
    """Send bedtime reminder notification if within window and not already sent."""
    settings = get_settings()
    tz = settings.tz
    current_now = now or dt.datetime.now(tz)
    if current_now.tzinfo is None:
        current_now = current_now.replace(tzinfo=tz)

    today = current_now.date()
    yesterday = today - dt.timedelta(days=1)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT local_date, planned_bedtime, planned_wake, sleep_need_min "
                "FROM daily_scores "
                "WHERE local_date IN (:yesterday, :today) AND planned_bedtime IS NOT NULL "
                "ORDER BY local_date DESC"
            ),
            {"yesterday": yesterday, "today": today},
        ).all()

        matching_row = None
        matching_bedtime: dt.datetime | None = None
        for row in rows:
            bt = row.planned_bedtime
            if bt.tzinfo is None:
                bt = bt.replace(tzinfo=tz)
            window_start = bt - dt.timedelta(minutes=30)
            window_end = bt + dt.timedelta(minutes=60)
            if window_start <= current_now < window_end:
                matching_row = row
                matching_bedtime = bt
                break

        if matching_row is None or matching_bedtime is None:
            return False

        row_date = matching_row.local_date
        ins = conn.execute(
            text(
                "INSERT INTO notifications_sent (local_date, kind, sent_at) "
                "VALUES (:d, 'bedtime_reminder', now()) "
                "ON CONFLICT (local_date, kind) DO NOTHING "
                "RETURNING local_date"
            ),
            {"d": row_date},
        ).scalar_one_or_none()
        if ins is None:
            return False

    try:
        title, body = format_bedtime_reminder(
            planned_bedtime=matching_bedtime,
            planned_wake=matching_row.planned_wake,
            sleep_need_min=matching_row.sleep_need_min,
            tz=tz,
            lang=settings.notify_lang,
        )
        client = notifier or NtfyClient()
        client.send(title, body, priority=3, tags=["bed"])
        return True
    except Exception:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM notifications_sent "
                    "WHERE local_date = :d AND kind = 'bedtime_reminder'"
                ),
                {"d": row_date},
            )
        raise
