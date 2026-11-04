"""Trends screen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.recovery import calculate_acute_chronic
from health_coach.analytics.scores import calculate_strain_from_load
from health_coach.mcp_server import quality
from health_coach.mcp_server.tools.discovery import current_targets
from health_coach.web.queries._common import _parse_date


def query_trends(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    start_date = target_date - dt.timedelta(days=days - 1)

    # 1. Daily scores
    sc_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, strain, cardio_load, muscular_score, "
                "       sleep_actual_min, sleep_performance "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    sc_map = {r["local_date"]: r for r in sc_rows}

    # 2. Vitals
    vt_rows = (
        conn.execute(
            text(
                "SELECT local_date, resting_hr, hrv_rmssd_ms "
                "FROM daily_vitals WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    vt_map = {r["local_date"]: r for r in vt_rows}

    # 3. Weight trend
    wt_rows = (
        conn.execute(
            text(
                "SELECT local_date, weight_kg, avg_7d_kg, trend_kg, weekly_rate_kg "
                "FROM v_weight_trend WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    wt_map = {r["local_date"]: r for r in wt_rows}

    # 4. Nutrition
    nt_rows = (
        conn.execute(
            text(
                "SELECT local_date, kcal, protein_g, target_kcal "
                "FROM v_nutrition_daily WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    nt_map = {r["local_date"]: r for r in nt_rows}

    # 5. Acute:chronic workload calculation
    # Query 28 days of daily load or strain
    acwr_28_start = target_date - dt.timedelta(days=27)
    past_28_strains = (
        conn.execute(
            text(
                "SELECT strain FROM daily_scores "
                "WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": acwr_28_start, "e": target_date},
        )
        .scalars()
        .all()
    )
    strain_loads = [float(s) for s in past_28_strains if s is not None]
    acwr = calculate_acute_chronic(strain_loads)

    # Compile daily points
    rec_points: list[dict[str, Any]] = []
    hrv_points: list[dict[str, Any]] = []
    rhr_points: list[dict[str, Any]] = []
    sleep_points: list[dict[str, Any]] = []
    strain_points: list[dict[str, Any]] = []
    cardio_points: list[dict[str, Any]] = []
    muscular_points: list[dict[str, Any]] = []
    weight_points: list[dict[str, Any]] = []
    kcal_points: list[dict[str, Any]] = []

    curr_d = start_date
    targets = current_targets(conn, target_date)
    target_kcal_val = targets.get("kcal") if targets else 2400

    while curr_d <= target_date:
        sc = sc_map.get(curr_d)
        vt = vt_map.get(curr_d)
        wt = wt_map.get(curr_d)
        nt = nt_map.get(curr_d)

        r_val = sc["recovery"] if sc and sc["recovery"] is not None else None
        rec_points.append({"date": curr_d.isoformat(), "val": r_val})

        hrv_val = float(vt["hrv_rmssd_ms"]) if vt and vt["hrv_rmssd_ms"] is not None else None
        hrv_points.append({"date": curr_d.isoformat(), "val": hrv_val})

        rhr_val = float(vt["resting_hr"]) if vt and vt["resting_hr"] is not None else None
        rhr_points.append({"date": curr_d.isoformat(), "val": rhr_val})

        sl_val = sc["sleep_actual_min"] if sc and sc["sleep_actual_min"] is not None else None
        sl_perf = sc["sleep_performance"] if sc and sc["sleep_performance"] is not None else None
        sleep_points.append({"date": curr_d.isoformat(), "val": sl_val, "perf": sl_perf})

        st_val = float(sc["strain"]) if sc and sc["strain"] is not None else None
        strain_points.append({"date": curr_d.isoformat(), "val": st_val})

        cl_val = float(sc["cardio_load"]) if sc and sc.get("cardio_load") is not None else None
        cs_val = calculate_strain_from_load(cl_val) if cl_val is not None else None
        ms_val = int(sc["muscular_score"]) if sc and sc.get("muscular_score") is not None else None
        cardio_points.append({"date": curr_d.isoformat(), "val": cs_val})
        muscular_points.append({"date": curr_d.isoformat(), "val": ms_val})

        w_raw = float(wt["weight_kg"]) if wt and wt["weight_kg"] is not None else None
        w_avg = float(wt["avg_7d_kg"]) if wt and wt["avg_7d_kg"] is not None else None
        weight_points.append({"date": curr_d.isoformat(), "raw": w_raw, "avg": w_avg})

        k_val = float(nt["kcal"]) if nt and nt["kcal"] is not None else None
        p_val = float(nt["protein_g"]) if nt and nt["protein_g"] is not None else None
        kcal_points.append({"date": curr_d.isoformat(), "val": k_val, "protein": p_val})

        curr_d += dt.timedelta(days=1)

    # Averages
    valid_recs = [p["val"] for p in rec_points if p["val"] is not None]
    avg_rec = round(sum(valid_recs) / len(valid_recs)) if valid_recs else None
    green_recs = sum(1 for v in valid_recs if v >= 67)

    valid_hrvs = [p["val"] for p in hrv_points if p["val"] is not None]
    avg_hrv = round(sum(valid_hrvs) / len(valid_hrvs), 1) if valid_hrvs else None

    valid_rhrs = [p["val"] for p in rhr_points if p["val"] is not None]
    avg_rhr = round(sum(valid_rhrs) / len(valid_rhrs), 1) if valid_rhrs else None

    valid_sleeps = [p["val"] for p in sleep_points if p["val"] is not None]
    avg_sleep_m = round(sum(valid_sleeps) / len(valid_sleeps)) if valid_sleeps else None
    valid_perfs = [p["perf"] for p in sleep_points if p["perf"] is not None]
    avg_perf = round(sum(valid_perfs) / len(valid_perfs)) if valid_perfs else None

    valid_strains = [p["val"] for p in strain_points if p["val"] is not None]
    avg_strain = round(sum(valid_strains) / len(valid_strains), 1) if valid_strains else None

    valid_cardio = [p["val"] for p in cardio_points if p["val"] is not None]
    avg_cardio = round(sum(valid_cardio) / len(valid_cardio), 1) if valid_cardio else None

    valid_muscular = [p["val"] for p in muscular_points if p["val"] is not None]
    avg_muscular = round(sum(valid_muscular) / len(valid_muscular), 1) if valid_muscular else None

    valid_weights = [p["avg"] for p in weight_points if p["avg"] is not None]
    last_weight = valid_weights[-1] if valid_weights else None
    weight_rate = None
    if len(valid_weights) >= 7:
        weight_rate = round(valid_weights[-1] - valid_weights[-7], 2)
    elif len(valid_weights) >= 2:
        weight_rate = round(valid_weights[-1] - valid_weights[0], 2)

    valid_kcals = [p["val"] for p in kcal_points if p["val"] is not None]
    avg_kcal = round(sum(valid_kcals) / len(valid_kcals)) if valid_kcals else None
    valid_proteins = [p["protein"] for p in kcal_points if p["protein"] is not None]
    avg_protein = round(sum(valid_proteins) / len(valid_proteins)) if valid_proteins else None

    return {
        "days": days,
        "date": target_date.isoformat(),
        "recovery": {
            "avg": avg_rec,
            "green_count": green_recs,
            "series": rec_points,
        },
        "hrv": {
            "avg": avg_hrv,
            "series": hrv_points,
        },
        "rhr": {
            "avg": avg_rhr,
            "series": rhr_points,
        },
        "sleep": {
            "avg_min": avg_sleep_m,
            "avg_perf": avg_perf,
            "series": sleep_points,
        },
        "strain": {
            "avg": avg_strain,
            "cardio_avg": avg_cardio,
            "muscular_avg": avg_muscular,
            "acwr": acwr,
            "series": strain_points,
            "cardio_series": cardio_points,
            "muscular_series": muscular_points,
        },
        "weight": {
            "last": last_weight,
            "rate": weight_rate,
            "series": weight_points,
        },
        "kcal": {
            "avg": avg_kcal,
            "avg_protein": avg_protein,
            "target": target_kcal_val,
            "series": kcal_points,
        },
        "as_of": quality.as_of(conn),
    }


# -----------------------------------------------------------------------------
# 7. /api/calendar
# -----------------------------------------------------------------------------
