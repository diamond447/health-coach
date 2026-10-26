"""Habit and behaviour journaling constants and definitions."""

from __future__ import annotations

import re
from typing import Any

BEHAVIOR_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

KNOWN_BEHAVIORS: tuple[tuple[str, str], ...] = (
    ("alcohol", "Standard drinks consumed (amount = standard drinks)"),
    ("caffeine_late", "Caffeine consumed after 14:00"),
    ("late_meal", "Meal consumed less than 2 hours before bed"),
    ("screen_in_bed", "Screen use while in bed"),
    ("sauna", "Sauna session"),
    ("cold_exposure", "Cold shower, plunge or ice bath"),
    ("stretching", "Stretching or mobility work"),
    ("meditation", "Meditation or breathwork"),
    ("reading", "Reading before sleep"),
    ("nap", "Daytime nap"),
    ("high_stress", "Unusually high stress day"),
    ("illness", "Acute illness, cold, or infection"),
    ("travel", "Travel or significant time zone shift"),
    ("sex", "Sexual activity"),
    ("magnesium", "Magnesium supplement before bed"),
)

BEHAVIOR_LABELS: dict[str, str] = {
    "alcohol": "Alkohol",
    "sauna": "Sauna",
    "caffeine_late": "Kofein po 14:00",
    "late_meal": "Jídlo < 2 h před spaním",
    "screen_in_bed": "Mobil v posteli",
    "stretching": "Strečink večer",
    "meditation": "Meditace",
    "cold_exposure": "Chladová terapie",
    "reading": "Čtení místo mobilu",
    "nap": "Zdřímnutí",
    "high_stress": "Vysoký stres",
    "illness": "Nemoc",
    "travel": "Cestování",
    "sex": "Sex",
    "magnesium": "Hořčík večer",
}

# Ordered list of tappable habits for the PWA journal screen
JOURNAL_OPTIONS: list[dict[str, Any]] = [
    {"behavior": "alcohol", "name": BEHAVIOR_LABELS["alcohol"], "unit": "nápoje"},
    {"behavior": "caffeine_late", "name": BEHAVIOR_LABELS["caffeine_late"], "unit": "šálky"},
    {"behavior": "late_meal", "name": BEHAVIOR_LABELS["late_meal"], "unit": None},
    {"behavior": "screen_in_bed", "name": BEHAVIOR_LABELS["screen_in_bed"], "unit": None},
    {"behavior": "high_stress", "name": BEHAVIOR_LABELS["high_stress"], "unit": None},
    {"behavior": "sauna", "name": BEHAVIOR_LABELS["sauna"], "unit": None},
    {"behavior": "stretching", "name": BEHAVIOR_LABELS["stretching"], "unit": None},
    {"behavior": "reading", "name": BEHAVIOR_LABELS["reading"], "unit": None},
    {"behavior": "meditation", "name": BEHAVIOR_LABELS["meditation"], "unit": None},
    {"behavior": "magnesium", "name": BEHAVIOR_LABELS["magnesium"], "unit": None},
    {"behavior": "cold_exposure", "name": BEHAVIOR_LABELS["cold_exposure"], "unit": None},
    {"behavior": "nap", "name": BEHAVIOR_LABELS["nap"], "unit": None},
    {"behavior": "travel", "name": BEHAVIOR_LABELS["travel"], "unit": None},
    {"behavior": "illness", "name": BEHAVIOR_LABELS["illness"], "unit": None},
    {"behavior": "sex", "name": BEHAVIOR_LABELS["sex"], "unit": None},
]
