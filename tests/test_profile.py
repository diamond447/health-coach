"""Tests for the scoring profile (app_settings over HC_* settings)."""

from typing import Any

import pytest

from health_coach.config import Settings
from health_coach.profile import Profile, profile_from


def test_stored_values_override_settings() -> None:
    settings = Settings(hr_max=185, birth_year=1980, sex="female")
    profile = profile_from({"hr_max": 201, "birth_year": 1990, "sex": "male"}, settings)
    assert profile == Profile(hr_max=201, birth_year=1990, sex="male")


def test_settings_are_the_fallback() -> None:
    settings = Settings(hr_max=185, birth_year=1980, sex="female")
    assert profile_from({}, settings) == Profile(hr_max=185, birth_year=1980, sex="female")


@pytest.mark.parametrize(
    "stored",
    [
        {"hr_max": 90},
        {"hr_max": "200"},
        {"hr_max": True},
        {"hr_max": 180.5},
        {"birth_year": 1800},
        {"birth_year": 3000},
        {"sex": "Male"},
    ],
)
def test_invalid_stored_values_fall_back(stored: dict[str, Any]) -> None:
    settings = Settings(hr_max=185, birth_year=1980, sex="female")
    assert profile_from(stored, settings) == Profile(hr_max=185, birth_year=1980, sex="female")


def test_effective_hr_max() -> None:
    assert Profile(hr_max=201, birth_year=1990).effective_hr_max(2026) == 201
    assert Profile(birth_year=1986).effective_hr_max(2026) == 180  # 208 - 0.7 * 40
    assert Profile().effective_hr_max(2026) == 190
    assert Profile(birth_year=1986).age(2026) == 40
    assert Profile().age(2026) is None
