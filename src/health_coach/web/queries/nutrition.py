"""Nutrition screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.tdee import estimate_from_db
from health_coach.config import get_settings
from health_coach.mcp_server import quality
from health_coach.mcp_server.tools.discovery import current_targets
from health_coach.nutrients import format_micros_summary
from health_coach.web.queries._common import CZECH_WEEKDAYS, MEAL_LABELS, _parse_date


def query_nutrition(conn: Connection, date_str: str | None = None) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    settings = get_settings()
    tz = settings.tz

    # Targets in force
    targets = current_targets(conn, target_date)

    # Totals on target_date
    totals_row = (
        conn.execute(
            text(
                "SELECT round(sum(kcal)) AS kcal, "
                "       round(sum(protein_g), 1) AS protein_g, "
                "       round(sum(carbs_g), 1) AS carbs_g, "
                "       round(sum(fat_g), 1) AS fat_g, "
                "       round(sum(fiber_g), 1) AS fiber_g "
                "FROM nutrition_entries WHERE local_date = :d AND deleted_at IS NULL"
            ),
            {"d": target_date},
        )
        .mappings()
        .first()
    )

    kcal = float(totals_row["kcal"]) if totals_row and totals_row["kcal"] is not None else 0.0
    protein_g = (
        float(totals_row["protein_g"])
        if totals_row and totals_row["protein_g"] is not None
        else 0.0
    )
    carbs_g = (
        float(totals_row["carbs_g"]) if totals_row and totals_row["carbs_g"] is not None else 0.0
    )
    fat_g = float(totals_row["fat_g"]) if totals_row and totals_row["fat_g"] is not None else 0.0
    fiber_g = (
        float(totals_row["fiber_g"]) if totals_row and totals_row["fiber_g"] is not None else 0.0
    )

    t_kcal = targets.get("kcal") if targets else None
    target_kcal = float(t_kcal) if t_kcal is not None else None
    t_prot = targets.get("protein_g") if targets else None
    target_protein = float(t_prot) if t_prot is not None else None
    t_carbs = targets.get("carbs_g") if targets else None
    target_carbs = float(t_carbs) if t_carbs is not None else None
    t_fat = targets.get("fat_g") if targets else None
    target_fat = float(t_fat) if t_fat is not None else None
    t_fiber = targets.get("fiber_g") if targets else None
    target_fiber = float(t_fiber) if t_fiber is not None else None

    # Meals grouped by meal type
    meal_entries = (
        conn.execute(
            text(
                "SELECT id, meal, description AS name, grams, kcal, "
                "       protein_g, carbs_g, fat_g, fiber_g, ts AS logged_at, micros "
                "FROM nutrition_entries WHERE local_date = :d AND deleted_at IS NULL "
                "ORDER BY ts ASC, id ASC"
            ),
            {"d": target_date},
        )
        .mappings()
        .all()
    )

    meals_dict: dict[str, dict[str, Any]] = {}
    last_logged_time: str | None = None
    entries_total = len(meal_entries)
    entries_with = 0
    total_micros: dict[str, float] = {}

    for m in meal_entries:
        m_micros = m["micros"]
        has_positive = (
            m_micros
            and isinstance(m_micros, dict)
            and any(v and float(v) > 0 for v in m_micros.values())
        )
        if has_positive:
            entries_with += 1
            for k, v in m_micros.items():
                if v and float(v) > 0:
                    total_micros[k] = total_micros.get(k, 0.0) + float(v)

        m_key = m["meal"] or "other"
        if m_key not in meals_dict:
            meals_dict[m_key] = {
                "key": m_key,
                "name": MEAL_LABELS.get(m_key, m_key.capitalize()),
                "time": None,
                "kcal": 0,
                "items": [],
            }
        m_logged = m["logged_at"]
        if m_logged:
            local_logged = m_logged.astimezone(tz)
            time_str = f"{local_logged.hour:02d}:{local_logged.minute:02d}"
            meals_dict[m_key]["time"] = time_str
            last_logged_time = time_str

        item_kcal = round(float(m["kcal"] or 0))
        meals_dict[m_key]["kcal"] += item_kcal
        meals_dict[m_key]["items"].append(
            {
                "name": m["name"],
                "protein_g": float(m["protein_g"]) if m["protein_g"] else 0.0,
                "carbs_g": float(m["carbs_g"]) if m["carbs_g"] is not None else None,
                "fat_g": float(m["fat_g"]) if m["fat_g"] is not None else None,
                "fiber_g": float(m["fiber_g"]) if m["fiber_g"] is not None else None,
                "kcal": item_kcal,
            }
        )

    meals_list = list(meals_dict.values())
    micros_list = format_micros_summary(total_micros)
    micros_coverage = {
        "entries_with": entries_with,
        "entries_total": entries_total,
    }

    # TDEE estimate (14 days window)
    tdee_res, _, _ = estimate_from_db(conn, target_date, window_days=14)
    tdee = tdee_res.tdee

    balance = round(kcal - tdee) if tdee is not None else None

    # 14-day mean balance
    past_14_start = target_date - dt.timedelta(days=13)
    past_14_kcals = conn.execute(
        text(
            "SELECT avg(kcal) FROM v_nutrition_daily "
            "WHERE local_date BETWEEN :s AND :e AND kcal IS NOT NULL"
        ),
        {"s": past_14_start, "e": target_date},
    ).scalar()
    avg_14_intake = float(past_14_kcals) if past_14_kcals is not None else None
    mean_14_balance = (
        round(avg_14_intake - tdee) if avg_14_intake is not None and tdee is not None else None
    )
    expected_weekly_change = (
        round(mean_14_balance * 7.0 / 7700.0, 2) if mean_14_balance is not None else None
    )

    # Actual weight trend rate
    wt_rate = conn.execute(
        text(
            "SELECT weekly_rate_kg FROM v_weight_trend WHERE local_date <= :d "
            "ORDER BY local_date DESC LIMIT 1"
        ),
        {"d": target_date},
    ).scalar()
    actual_weekly_change = float(wt_rate) if wt_rate is not None else None

    # Last 7 days kcal with protein hit
    week_start = target_date - dt.timedelta(days=6)
    week_rows = (
        conn.execute(
            text(
                "SELECT local_date, kcal, protein_g, target_kcal, target_protein_g "
                "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": week_start, "e": target_date},
        )
        .mappings()
        .all()
    )
    week_map = {r["local_date"]: r for r in week_rows}

    week_list: list[dict[str, Any]] = []
    w_d = week_start
    protein_hits = 0
    while w_d <= target_date:
        r = week_map.get(w_d)
        d_kcal = float(r["kcal"]) if r and r["kcal"] is not None else None
        d_prot = float(r["protein_g"]) if r and r["protein_g"] is not None else None
        d_target_prot = (
            float(r["target_protein_g"])
            if r and r["target_protein_g"] is not None
            else target_protein
        )
        hit = bool(d_prot is not None and d_target_prot is not None and d_prot >= d_target_prot)
        if hit:
            protein_hits += 1
        week_list.append(
            {
                "date": w_d.isoformat(),
                "weekday": CZECH_WEEKDAYS[w_d.weekday()],
                "kcal": d_kcal,
                "protein_hit": hit,
            }
        )
        w_d += dt.timedelta(days=1)

    return {
        "date": target_date.isoformat(),
        "kcal": round(kcal),
        "target_kcal": round(target_kcal) if target_kcal else None,
        "remaining_kcal": round(target_kcal - kcal) if target_kcal else None,
        "phase": targets.get("phase") if targets else None,
        "weekly_rate_target_kg": (targets.get("weekly_rate_min_kg") if targets else None),
        "macros": [
            {
                "name": "Bílkoviny",
                "val": protein_g,
                "target": target_protein,
                "unit": "g",
                "color": "#FF8A65",
            },
            {
                "name": "Sacharidy",
                "val": carbs_g,
                "target": target_carbs,
                "unit": "g",
                "color": "#F5C542",
            },
            {"name": "Tuky", "val": fat_g, "target": target_fat, "unit": "g", "color": "#4D9BE8"},
            {
                "name": "Vláknina",
                "val": fiber_g,
                "target": target_fiber,
                "unit": "g",
                "color": "#5FE39E",
            },
        ],
        "meals": meals_list,
        "meals_count": len(meals_list),
        "last_logged_time": last_logged_time,
        "energy_balance": {
            "intake": round(kcal),
            "tdee": round(tdee) if tdee else None,
            "balance": balance,
            "mean_14_balance": mean_14_balance,
            "expected_weekly_change": expected_weekly_change,
            "actual_weekly_change": actual_weekly_change,
        },
        "week": week_list,
        "protein_hits_days": protein_hits,
        "micros": micros_list,
        "micros_coverage": micros_coverage,
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 6. /api/trends
# -----------------------------------------------------------------------------
