"""Sleep screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.config import get_settings
from health_coach.mcp_server import quality
from health_coach.mcp_server.common import jsonable
from health_coach.web.queries._common import CZECH_WEEKDAYS, _get_daily_score_row, _parse_date


def query_sleep(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    settings = get_settings()

    # Main sleep session for the night ending on target_date
    main_session = (
        conn.execute(
            text(
                "SELECT id, start_ts, end_ts, duration_min, time_in_bed_min, efficiency "
                "FROM sleep_sessions "
                "WHERE local_date = :d AND is_main = true "
                "ORDER BY start_ts DESC LIMIT 1"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    # Fallback to any sleep session if no is_main
    if not main_session:
        main_session = (
            conn.execute(
                text(
                    "SELECT id, start_ts, end_ts, duration_min, time_in_bed_min, efficiency "
                    "FROM sleep_sessions WHERE local_date = :d "
                    "ORDER BY duration_min DESC NULLS LAST LIMIT 1"
                ),
                {"d": target_date},
            )
            .mappings()
            .first()
        )

    stages_list: list[dict[str, Any]] = []
    wake_count = 0
    stage_totals: dict[str, int] = {"awake": 0, "rem": 0, "light": 0, "deep": 0}

    if main_session:
        stg_rows = (
            conn.execute(
                text(
                    "SELECT stage, start_ts, end_ts "
                    "FROM sleep_stages WHERE session_id = :sid ORDER BY start_ts"
                ),
                {"sid": main_session["id"]},
            )
            .mappings()
            .all()
        )

        for s in stg_rows:
            stg_name = s["stage"]
            dur_sec = int((s["end_ts"] - s["start_ts"]).total_seconds())
            dur_m = round(dur_sec / 60)
            stages_list.append(
                {
                    "stage": stg_name,
                    "start_ts": jsonable(s["start_ts"]),
                    "end_ts": jsonable(s["end_ts"]),
                    "duration_sec": dur_sec,
                    "duration_min": dur_m,
                }
            )
            if stg_name in stage_totals:
                stage_totals[stg_name] += dur_m
            if stg_name == "awake":
                wake_count += 1

    # Sleep score and need from daily_scores
    score_row = _get_daily_score_row(conn, target_date)

    # Base need from app_settings or settings
    base_setting = conn.execute(
        text("SELECT value FROM app_settings WHERE key = 'sleep_need_base_min'")
    ).scalar()
    base_need = int(base_setting) if base_setting is not None else settings.sleep_need_base_min

    # Strain bonus from strain on day D-1
    prev_d = target_date - dt.timedelta(days=1)
    prev_score = _get_daily_score_row(conn, prev_d)
    prev_strain = (
        float(prev_score["strain"]) if prev_score and prev_score.get("strain") is not None else None
    )
    strain_bonus_min = round(max(0.0, prev_strain - 7.0) * 3) if prev_strain is not None else 0

    # Naps credit from naps on day D-1
    nap_mins = conn.execute(
        text(
            "SELECT coalesce(sum(duration_min), 0) FROM sleep_sessions "
            "WHERE local_date = :d AND is_main = false"
        ),
        {"d": prev_d},
    ).scalar_one()
    nap_credit_min = int(nap_mins)

    sleep_debt_min = (
        score_row["sleep_debt_min"]
        if score_row and score_row.get("sleep_debt_min") is not None
        else 0
    )
    sleep_need_min = (
        score_row["sleep_need_min"]
        if score_row and score_row.get("sleep_need_min") is not None
        else (base_need + sleep_debt_min + strain_bonus_min - nap_credit_min)
    )

    # Last trailing nights
    week_start = target_date - dt.timedelta(days=days - 1)
    week_scores = (
        conn.execute(
            text(
                "SELECT local_date, sleep_actual_min, sleep_need_min, sleep_performance "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_map = {r["local_date"]: r for r in week_scores}

    week_list: list[dict[str, Any]] = []
    w_d = week_start
    while w_d <= target_date:
        w_sc = week_map.get(w_d)
        actual = (
            w_sc["sleep_actual_min"] if w_sc and w_sc.get("sleep_actual_min") is not None else None
        )
        need = w_sc["sleep_need_min"] if w_sc and w_sc.get("sleep_need_min") is not None else None
        week_list.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "actual_min": actual,
                "need_min": need,
                "performance": w_sc["sleep_performance"] if w_sc else None,
            }
        )
        w_d += dt.timedelta(days=1)

    # Tonight's plan
    tonight_plan = {
        "planned_bedtime": jsonable(score_row["planned_bedtime"]) if score_row else None,
        "planned_wake": jsonable(score_row["planned_wake"]) if score_row else None,
        "sleep_need_min": score_row["sleep_need_min"] if score_row else base_need,
        "today_strain": float(score_row["strain"])
        if score_row and score_row.get("strain") is not None
        else None,
        "today_strain_bonus_min": (
            round(max(0.0, float(score_row["strain"]) - 7.0) * 3)
            if score_row and score_row.get("strain") is not None
            else 0
        ),
    }

    return {
        "date": target_date.isoformat(),
        "session": {
            "start_ts": jsonable(main_session["start_ts"]) if main_session else None,
            "end_ts": jsonable(main_session["end_ts"]) if main_session else None,
            "duration_min": main_session["duration_min"] if main_session else None,
            "time_in_bed_min": main_session["time_in_bed_min"] if main_session else None,
            "efficiency": main_session["efficiency"] if main_session else None,
            "wake_count": wake_count,
        },
        "performance": score_row["sleep_performance"] if score_row else None,
        "consistency": score_row["sleep_consistency"] if score_row else None,
        "stages": stages_list,
        "stage_totals": stage_totals,
        "need_breakdown": {
            "base_need_min": base_need,
            "debt_min": sleep_debt_min,
            "prev_strain": prev_strain,
            "strain_bonus_min": strain_bonus_min,
            "nap_credit_min": nap_credit_min,
            "total_need_min": sleep_need_min,
        },
        "week": week_list,
        "tonight_plan": tonight_plan,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 4. /api/strain
# -----------------------------------------------------------------------------
