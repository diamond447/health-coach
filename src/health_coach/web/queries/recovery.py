"""Recovery and night screens: vitals against their 30-day baselines."""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

from sqlalchemy import Connection, text

from health_coach.analytics.scores import recovery_zone
from health_coach.mcp_server import quality
from health_coach.web.queries._common import _parse_date


def _build_vitals_history(conn: Connection, target_date: dt.date, days: int) -> dict[str, Any]:
    start_date = target_date - dt.timedelta(days=days - 1)

    vitals_rows = (
        conn.execute(
            text(
                "SELECT local_date, resting_hr, hrv_rmssd_ms, breathing_rate, "
                "       skin_temp_delta, spo2_avg "
                "FROM daily_vitals WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    vitals_map = {r["local_date"]: r for r in vitals_rows}

    scores_rows = (
        conn.execute(
            text(
                "SELECT local_date, recovery, recovery_z, recovery_components, flags, "
                "inputs, sleep_performance "
                "FROM daily_scores WHERE local_date BETWEEN :s AND :e ORDER BY local_date"
            ),
            {"s": start_date, "e": target_date},
        )
        .mappings()
        .all()
    )
    scores_map = {r["local_date"]: r for r in scores_rows}

    hrv_series: list[dict[str, Any]] = []
    rhr_series: list[dict[str, Any]] = []
    sleep_series: list[dict[str, Any]] = []
    breathing_series: list[dict[str, Any]] = []
    skin_temp_series: list[dict[str, Any]] = []
    spo2_series: list[dict[str, Any]] = []

    curr_d = start_date
    latest_hrv_band: list[float] | None = None
    latest_rhr_band: list[float] | None = None
    latest_breathing_band: list[float] | None = None
    latest_skin_temp_band: list[float] | None = None

    while curr_d <= target_date:
        v = vitals_map.get(curr_d)
        sc = scores_map.get(curr_d)

        inputs_data = sc["inputs"] if sc and sc.get("inputs") else None
        if isinstance(inputs_data, str):
            inputs_data = json.loads(inputs_data)

        baselines = inputs_data.get("baselines", {}) if isinstance(inputs_data, dict) else {}

        # HRV band = exp(center +- scale)
        hrv_band_lo: float | None = None
        hrv_band_hi: float | None = None
        if baselines.get("hrv"):
            c, s = baselines["hrv"]
            hrv_band_lo = round(math.exp(c - s), 1)
            hrv_band_hi = round(math.exp(c + s), 1)
            latest_hrv_band = [hrv_band_lo, hrv_band_hi]

        # RHR band = center +- scale
        rhr_band_lo: float | None = None
        rhr_band_hi: float | None = None
        if baselines.get("rhr"):
            c, s = baselines["rhr"]
            rhr_band_lo = round(c - s, 1)
            rhr_band_hi = round(c + s, 1)
            latest_rhr_band = [rhr_band_lo, rhr_band_hi]

        # Breathing rate band = center +- scale
        br_band_lo: float | None = None
        br_band_hi: float | None = None
        if baselines.get("breathing_rate"):
            c, s = baselines["breathing_rate"]
            br_band_lo = round(c - s, 2)
            br_band_hi = round(c + s, 2)
            latest_breathing_band = [br_band_lo, br_band_hi]

        # Skin temp band = center +- scale
        temp_band_lo: float | None = None
        temp_band_hi: float | None = None
        if baselines.get("skin_temp"):
            c, s = baselines["skin_temp"]
            temp_band_lo = round(c - s, 2)
            temp_band_hi = round(c + s, 2)
            latest_skin_temp_band = [temp_band_lo, temp_band_hi]

        hrv_val = float(v["hrv_rmssd_ms"]) if v and v["hrv_rmssd_ms"] is not None else None
        rhr_val = float(v["resting_hr"]) if v and v["resting_hr"] is not None else None
        sleep_perf = (
            float(sc["sleep_performance"])
            if sc and sc.get("sleep_performance") is not None
            else None
        )
        br_val = float(v["breathing_rate"]) if v and v["breathing_rate"] is not None else None
        temp_val = float(v["skin_temp_delta"]) if v and v["skin_temp_delta"] is not None else None
        spo2_val = float(v["spo2_avg"]) if v and v["spo2_avg"] is not None else None

        d_str = curr_d.isoformat()
        hrv_series.append(
            {
                "date": d_str,
                "val": hrv_val,
                "band_lo": hrv_band_lo,
                "band_hi": hrv_band_hi,
            }
        )
        rhr_series.append(
            {
                "date": d_str,
                "val": rhr_val,
                "band_lo": rhr_band_lo,
                "band_hi": rhr_band_hi,
            }
        )
        sleep_series.append(
            {
                "date": d_str,
                "val": sleep_perf,
                "band_lo": None,
                "band_hi": None,
            }
        )
        breathing_series.append(
            {
                "date": d_str,
                "val": br_val,
                "band_lo": br_band_lo,
                "band_hi": br_band_hi,
            }
        )
        skin_temp_series.append(
            {
                "date": d_str,
                "val": temp_val,
                "band_lo": temp_band_lo,
                "band_hi": temp_band_hi,
            }
        )
        spo2_series.append(
            {
                "date": d_str,
                "val": spo2_val,
                "band_lo": None,
                "band_hi": None,
            }
        )
        curr_d += dt.timedelta(days=1)

    return {
        "start_date": start_date,
        "hrv_series": hrv_series,
        "rhr_series": rhr_series,
        "sleep_series": sleep_series,
        "breathing_series": breathing_series,
        "skin_temp_series": skin_temp_series,
        "spo2_series": spo2_series,
        "latest_hrv_band": latest_hrv_band,
        "latest_rhr_band": latest_rhr_band,
        "latest_breathing_band": latest_breathing_band,
        "latest_skin_temp_band": latest_skin_temp_band,
        "today_vitals": vitals_map.get(target_date),
        "today_scores": scores_map.get(target_date),
    }


def query_recovery(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    hist = _build_vitals_history(conn, target_date, days)

    today_sc = hist["today_scores"]
    today_v = hist["today_vitals"]

    recovery = today_sc["recovery"] if today_sc else None
    zone = recovery_zone(recovery) if recovery is not None else None
    recovery_z = (
        float(today_sc["recovery_z"])
        if today_sc and today_sc.get("recovery_z") is not None
        else None
    )

    components = today_sc["recovery_components"] if today_sc else None
    if isinstance(components, str):
        components = json.loads(components)
    flags = today_sc["flags"] if today_sc else []

    # Czech summary text matching zone
    summary: str
    if zone == "green":
        summary = "Tělo je připravené na zátěž. HRV je nad tvým normálem a klidový tep pod ním."
    elif zone == "yellow":
        summary = "Běžný stav organismu. Můžeš udržovat obvyklou tréninkovou zátěž."
    elif zone == "red":
        summary = (
            "Organismus vykazuje známky přetížení nebo únavy. "
            "Doporučujeme klidový režim nebo lehkou regeneraci."
        )
    else:
        summary = "Recovery se počítá po synchronizaci noci a alespoň 7 dnech měření."

    return {
        "date": target_date.isoformat(),
        "recovery": recovery,
        "zone": zone,
        "recovery_z": recovery_z,
        "summary": summary,
        "components": components or [],
        "flags": flags,
        "current_hrv": float(today_v["hrv_rmssd_ms"])
        if today_v and today_v["hrv_rmssd_ms"] is not None
        else None,
        "current_rhr": float(today_v["resting_hr"])
        if today_v and today_v["resting_hr"] is not None
        else None,
        "hrv_band": hist["latest_hrv_band"],
        "rhr_band": hist["latest_rhr_band"],
        "hrv_series": hist["hrv_series"],
        "rhr_series": hist["rhr_series"],
        "sleep_series": hist["sleep_series"],
        "breathing_series": hist["breathing_series"],
        "skin_temp_series": hist["skin_temp_series"],
        "as_of": quality.as_of(conn),
    }


def query_night(conn: Connection, date_str: str | None = None, days: int = 30) -> dict[str, Any]:
    target_date = _parse_date(date_str)
    hist = _build_vitals_history(conn, target_date, days)
    today_v = hist["today_vitals"]

    def _calc_avg(series: list[dict[str, Any]], decimals: int = 1) -> float | None:
        valid = [s["val"] for s in series if s["val"] is not None and not math.isnan(s["val"])]
        return round(sum(valid) / len(valid), decimals) if valid else None

    return {
        "date": target_date.isoformat(),
        "days": days,
        "hrv": {
            "current": float(today_v["hrv_rmssd_ms"])
            if today_v and today_v["hrv_rmssd_ms"] is not None
            else None,
            "avg": _calc_avg(hist["hrv_series"], 1),
            "band": hist["latest_hrv_band"],
            "series": hist["hrv_series"],
        },
        "rhr": {
            "current": float(today_v["resting_hr"])
            if today_v and today_v["resting_hr"] is not None
            else None,
            "avg": _calc_avg(hist["rhr_series"], 1),
            "band": hist["latest_rhr_band"],
            "series": hist["rhr_series"],
        },
        "spo2": {
            "current": float(today_v["spo2_avg"])
            if today_v and today_v["spo2_avg"] is not None
            else None,
            "avg": _calc_avg(hist["spo2_series"], 1),
            "band": None,
            "series": hist["spo2_series"],
        },
        "breathing": {
            "current": float(today_v["breathing_rate"])
            if today_v and today_v["breathing_rate"] is not None
            else None,
            "avg": _calc_avg(hist["breathing_series"], 1),
            "band": hist["latest_breathing_band"],
            "series": hist["breathing_series"],
        },
        "skin_temp": {
            "current": float(today_v["skin_temp_delta"])
            if today_v and today_v["skin_temp_delta"] is not None
            else None,
            "avg": _calc_avg(hist["skin_temp_series"], 2),
            "band": hist["latest_skin_temp_band"],
            "series": hist["skin_temp_series"],
        },
        "as_of": quality.as_of(conn),
    }
