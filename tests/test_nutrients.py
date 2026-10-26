"""Tests for nutrients definitions, conversions, mappings, and summaries."""

from health_coach.nutrients import (
    GH_EXCLUDED_NUTRIENTS,
    GH_NUTRIENT_MAP,
    NUTRIENTS,
    NUTRIENTS_BY_KEY,
    format_micros_summary,
    parse_off_micros,
    to_display_amount,
)


def test_nutrients_reference_values_and_kinds() -> None:
    # Targets from Regulation (EU) 1169/2011 Annex XIII
    assert NUTRIENTS_BY_KEY["vitamin_a"].reference == 800.0
    assert NUTRIENTS_BY_KEY["vitamin_a"].unit == "µg"
    assert NUTRIENTS_BY_KEY["vitamin_a"].kind == "target"

    assert NUTRIENTS_BY_KEY["vitamin_d"].reference == 5.0
    assert NUTRIENTS_BY_KEY["vitamin_d"].unit == "µg"
    assert NUTRIENTS_BY_KEY["vitamin_d"].kind == "target"

    assert NUTRIENTS_BY_KEY["vitamin_c"].reference == 80.0
    assert NUTRIENTS_BY_KEY["vitamin_c"].unit == "mg"
    assert NUTRIENTS_BY_KEY["vitamin_c"].kind == "target"

    assert NUTRIENTS_BY_KEY["thiamin"].reference == 1.1
    assert NUTRIENTS_BY_KEY["riboflavin"].reference == 1.4
    assert NUTRIENTS_BY_KEY["niacin"].reference == 16.0
    assert NUTRIENTS_BY_KEY["vitamin_b6"].reference == 1.4
    assert NUTRIENTS_BY_KEY["folate"].reference == 200.0
    assert NUTRIENTS_BY_KEY["vitamin_b12"].reference == 2.5
    assert NUTRIENTS_BY_KEY["biotin"].reference == 50.0
    assert NUTRIENTS_BY_KEY["pantothenic_acid"].reference == 6.0

    assert NUTRIENTS_BY_KEY["potassium"].reference == 2000.0
    assert NUTRIENTS_BY_KEY["chloride"].reference == 800.0
    assert NUTRIENTS_BY_KEY["calcium"].reference == 800.0
    assert NUTRIENTS_BY_KEY["phosphorus"].reference == 700.0
    assert NUTRIENTS_BY_KEY["magnesium"].reference == 375.0
    assert NUTRIENTS_BY_KEY["iron"].reference == 14.0
    assert NUTRIENTS_BY_KEY["zinc"].reference == 10.0
    assert NUTRIENTS_BY_KEY["copper"].reference == 1.0
    assert NUTRIENTS_BY_KEY["manganese"].reference == 2.0
    assert NUTRIENTS_BY_KEY["selenium"].reference == 55.0
    assert NUTRIENTS_BY_KEY["chromium"].reference == 40.0
    assert NUTRIENTS_BY_KEY["molybdenum"].reference == 50.0
    assert NUTRIENTS_BY_KEY["iodine"].reference == 150.0

    # Limits
    assert NUTRIENTS_BY_KEY["sodium"].reference == 2000.0
    assert NUTRIENTS_BY_KEY["sodium"].unit == "mg"
    assert NUTRIENTS_BY_KEY["sodium"].kind == "limit"

    assert NUTRIENTS_BY_KEY["sugar"].reference == 50.0
    assert NUTRIENTS_BY_KEY["sugar"].unit == "g"
    assert NUTRIENTS_BY_KEY["sugar"].kind == "limit"

    assert NUTRIENTS_BY_KEY["saturated_fat"].reference == 22.0
    assert NUTRIENTS_BY_KEY["saturated_fat"].unit == "g"
    assert NUTRIENTS_BY_KEY["saturated_fat"].kind == "limit"

    assert NUTRIENTS_BY_KEY["caffeine"].reference == 400.0
    assert NUTRIENTS_BY_KEY["caffeine"].unit == "mg"
    assert NUTRIENTS_BY_KEY["caffeine"].kind == "limit"

    # Nutrients without reference
    fats = (
        "cholesterol",
        "monounsaturated_fat",
        "polyunsaturated_fat",
        "trans_fat",
        "unsaturated_fat",
    )
    for fat in fats:
        assert NUTRIENTS_BY_KEY[fat].reference is None
        assert NUTRIENTS_BY_KEY[fat].kind is None


def test_nutrient_groups_ordering() -> None:
    groups = [n.group for n in NUTRIENTS]
    # Check that all "minerály" appear first, then "vitamíny", then "ostatní"
    first_vit = groups.index("vitamíny")
    first_ost = groups.index("ostatní")
    assert all(g == "minerály" for g in groups[:first_vit])
    assert all(g == "vitamíny" for g in groups[first_vit:first_ost])
    assert all(g == "ostatní" for g in groups[first_ost:])


def test_to_display_amount() -> None:
    # grams -> g
    assert to_display_amount(15.4, "g") == 15.4
    assert to_display_amount(0.35, "g") == 0.35

    # grams -> mg
    assert to_display_amount(0.5, "mg") == 500.0
    assert to_display_amount(0.0014, "mg") == 1.4

    # grams -> µg
    assert to_display_amount(0.0002, "µg") == 200.0
    assert to_display_amount(0.0000025, "µg") == 2.5


def test_parse_off_micros() -> None:
    nutriments = {
        "sodium_100g": 0.45,
        "potassium_100g": "0.32",
        "vitamin-c_100g": 0.015,
        "folates_100g": 0.00005,
        "sugars_100g": 12.0,
        "saturated-fat_100g": 2.5,
        "energy-kcal_100g": 250,  # macro / calorie, not a micro
        "proteins_100g": 10.0,
        "caffeine_100g": 0.0,  # zero should be skipped
        "copper_100g": -0.5,  # negative should be skipped
    }
    parsed = parse_off_micros(nutriments)
    assert parsed["sodium"] == 0.45
    assert parsed["potassium"] == 0.32
    assert parsed["vitamin_c"] == 0.015
    assert parsed["folate"] == 0.00005
    assert parsed["sugar"] == 12.0
    assert parsed["saturated_fat"] == 2.5
    assert "caffeine" not in parsed
    assert "copper" not in parsed
    assert "energy-kcal" not in parsed


def test_format_micros_summary() -> None:
    micros_g = {
        "sodium": 0.5,  # 500 mg, limit 2000 mg -> 25 %
        "vitamin_c": 0.08,  # 80 mg, target 80 mg -> 100 %
        "sugar": 25.0,  # 25 g, limit 50 g -> 50 %
        "cholesterol": 0.05,  # 50 mg, no ref -> pct None
        "potassium": 0.0,  # zero should be skipped
    }
    summary = format_micros_summary(micros_g)
    assert len(summary) == 4
    # Ordered by group: minerály (sodium), vitamíny (vitamin_c), ostatní (sugar, cholesterol)
    assert [s["key"] for s in summary] == ["sodium", "vitamin_c", "sugar", "cholesterol"]

    sod = summary[0]
    assert sod["amount"] == 500.0
    assert sod["unit"] == "mg"
    assert sod["reference"] == 2000.0
    assert sod["kind"] == "limit"
    assert sod["pct"] == 25

    vit_c = summary[1]
    assert vit_c["amount"] == 80.0
    assert vit_c["unit"] == "mg"
    assert vit_c["reference"] == 80.0
    assert vit_c["kind"] == "target"
    assert vit_c["pct"] == 100

    sug = summary[2]
    assert sug["amount"] == 25.0
    assert sug["unit"] == "g"
    assert sug["reference"] == 50.0
    assert sug["kind"] == "limit"
    assert sug["pct"] == 50

    chol = summary[3]
    assert chol["amount"] == 50.0
    assert chol["unit"] == "mg"
    assert chol["reference"] is None
    assert chol["kind"] is None
    assert chol["pct"] is None


def test_google_health_mappings() -> None:
    # Folic acid and Folate both map to folate
    assert GH_NUTRIENT_MAP["FOLIC_ACID"] == "folate"
    assert GH_NUTRIENT_MAP["FOLATE"] == "folate"
    # Macros excluded from GH micros
    assert "PROTEIN" in GH_EXCLUDED_NUTRIENTS
    assert "DIETARY_FIBER" in GH_EXCLUDED_NUTRIENTS
    assert "CARBOHYDRATES" in GH_EXCLUDED_NUTRIENTS
