"""Micronutrient definitions, unit conversions, reference values, and mapper mappings.

One shared module defining:
- Standard snake_case nutrient keys
- Czech names
- Display units (g, mg, µg)
- Groups (minerály / vitamíny / ostatní)
- Reference values and limits (Regulation (EU) 1169/2011 Annex XIII, WHO, EFSA)
- Google Health nutrient enum -> key mapping
- Open Food Facts nutriments key -> key mapping
"""

from dataclasses import dataclass
from typing import Any, Literal

NutrientGroup = Literal["minerály", "vitamíny", "ostatní"]
NutrientKind = Literal["target", "limit"]
NutrientUnit = Literal["g", "mg", "µg"]


@dataclass(frozen=True)
class NutrientDef:
    key: str
    name: str  # Czech display name
    group: NutrientGroup
    unit: NutrientUnit
    reference: float | None  # Daily reference value in display unit
    kind: NutrientKind | None  # "target", "limit", or None


# All known micronutrients in their fixed display order, grouped by minerály, vitamíny, ostatní.
NUTRIENTS: tuple[NutrientDef, ...] = (
    # --- Minerály -------------------------------------------------------------
    # Regulation (EU) No 1169/2011 Annex XIII Part A: Daily nutrient reference values (NRVs)
    NutrientDef("potassium", "Draslík", "minerály", "mg", 2000.0, "target"),
    NutrientDef("chloride", "Chlorid", "minerály", "mg", 800.0, "target"),
    NutrientDef("calcium", "Vápník", "minerály", "mg", 800.0, "target"),
    NutrientDef("phosphorus", "Fosfor", "minerály", "mg", 700.0, "target"),
    NutrientDef("magnesium", "Hořčík", "minerály", "mg", 375.0, "target"),
    NutrientDef("iron", "Železo", "minerály", "mg", 14.0, "target"),
    NutrientDef("zinc", "Zinek", "minerály", "mg", 10.0, "target"),
    NutrientDef("copper", "Měď", "minerály", "mg", 1.0, "target"),
    NutrientDef("manganese", "Mangan", "minerály", "mg", 2.0, "target"),
    NutrientDef("selenium", "Selen", "minerály", "µg", 55.0, "target"),
    NutrientDef("chromium", "Chrom", "minerály", "µg", 40.0, "target"),
    NutrientDef("molybdenum", "Molybden", "minerály", "µg", 50.0, "target"),
    NutrientDef("iodine", "Jód", "minerály", "µg", 150.0, "target"),
    # WHO (2012) Guideline: Sodium intake for adults and children (< 2000 mg/day)
    NutrientDef("sodium", "Sodík", "minerály", "mg", 2000.0, "limit"),
    # --- Vitamíny -------------------------------------------------------------
    # Regulation (EU) No 1169/2011 Annex XIII Part A: Daily nutrient reference values (NRVs)
    NutrientDef("vitamin_a", "Vitamín A", "vitamíny", "µg", 800.0, "target"),
    NutrientDef("vitamin_d", "Vitamín D", "vitamíny", "µg", 5.0, "target"),
    NutrientDef("vitamin_e", "Vitamín E", "vitamíny", "mg", 12.0, "target"),
    NutrientDef("vitamin_k", "Vitamín K", "vitamíny", "µg", 75.0, "target"),
    NutrientDef("vitamin_c", "Vitamín C", "vitamíny", "mg", 80.0, "target"),
    NutrientDef("thiamin", "Thiamin (B1)", "vitamíny", "mg", 1.1, "target"),
    NutrientDef("riboflavin", "Riboflavin (B2)", "vitamíny", "mg", 1.4, "target"),
    NutrientDef("niacin", "Niacin (B3)", "vitamíny", "mg", 16.0, "target"),
    NutrientDef("pantothenic_acid", "Kyselina pantothenová (B5)", "vitamíny", "mg", 6.0, "target"),
    NutrientDef("vitamin_b6", "Vitamín B6", "vitamíny", "mg", 1.4, "target"),
    NutrientDef("biotin", "Biotin (B7)", "vitamíny", "µg", 50.0, "target"),
    NutrientDef("folate", "Kyselina listová (B9)", "vitamíny", "µg", 200.0, "target"),
    NutrientDef("vitamin_b12", "Vitamín B12", "vitamíny", "µg", 2.5, "target"),
    # --- Ostatní --------------------------------------------------------------
    # WHO (2015) Sugars intake for adults and children:
    # < 10 % of 2000 kcal = 50 g (total sugars here)
    NutrientDef("sugar", "Cukry", "ostatní", "g", 50.0, "limit"),
    # Nordic / DGE / EFSA recommendations: saturated fat < 10 % of 2000 kcal = 22 g
    NutrientDef("saturated_fat", "Nasycené tuky", "ostatní", "g", 22.0, "limit"),
    # EFSA (2015) Scientific Opinion on the safety of caffeine: daily intake <= 400 mg
    NutrientDef("caffeine", "Kofein", "ostatní", "mg", 400.0, "limit"),
    # Cholesterol and mono/poly/trans/unsaturated fats: shown without reference
    NutrientDef("cholesterol", "Cholesterol", "ostatní", "mg", None, None),
    NutrientDef("monounsaturated_fat", "Mononenasycené tuky", "ostatní", "g", None, None),
    NutrientDef("polyunsaturated_fat", "Polynenasycené tuky", "ostatní", "g", None, None),
    NutrientDef("trans_fat", "Transmastné tuky", "ostatní", "g", None, None),
    NutrientDef("unsaturated_fat", "Nenasycené tuky", "ostatní", "g", None, None),
)

NUTRIENTS_BY_KEY: dict[str, NutrientDef] = {n.key: n for n in NUTRIENTS}

# Google Health API nutrient enum string -> standard snake_case key.
# Note: PROTEIN, DIETARY_FIBER, and CARBOHYDRATES are mapped to top-level columns and excluded here.
GH_EXCLUDED_NUTRIENTS: frozenset[str] = frozenset({"PROTEIN", "DIETARY_FIBER", "CARBOHYDRATES"})

GH_NUTRIENT_MAP: dict[str, str] = {
    "BIOTIN": "biotin",
    "CAFFEINE": "caffeine",
    "CALCIUM": "calcium",
    "CHLORIDE": "chloride",
    "CHOLESTEROL": "cholesterol",
    "CHROMIUM": "chromium",
    "COPPER": "copper",
    "FOLIC_ACID": "folate",
    "FOLATE": "folate",
    "IODINE": "iodine",
    "IRON": "iron",
    "MAGNESIUM": "magnesium",
    "MANGANESE": "manganese",
    "MOLYBDENUM": "molybdenum",
    "MONOUNSATURATED_FAT": "monounsaturated_fat",
    "NIACIN": "niacin",
    "PANTOTHENIC_ACID": "pantothenic_acid",
    "PHOSPHORUS": "phosphorus",
    "POLYUNSATURATED_FAT": "polyunsaturated_fat",
    "POTASSIUM": "potassium",
    "RIBOFLAVIN": "riboflavin",
    "SATURATED_FAT": "saturated_fat",
    "SELENIUM": "selenium",
    "SODIUM": "sodium",
    "SUGAR": "sugar",
    "THIAMIN": "thiamin",
    "TRANS_FAT": "trans_fat",
    "UNSATURATED_FAT": "unsaturated_fat",
    "VITAMIN_A": "vitamin_a",
    "VITAMIN_B12": "vitamin_b12",
    "VITAMIN_B6": "vitamin_b6",
    "VITAMIN_C": "vitamin_c",
    "VITAMIN_D": "vitamin_d",
    "VITAMIN_E": "vitamin_e",
    "VITAMIN_K": "vitamin_k",
    "ZINC": "zinc",
}

# Open Food Facts nutriments prefix -> standard snake_case key.
# OFF products have nutriments.<prefix>_100g in grams per 100 g.
OFF_NUTRIENT_MAP: dict[str, str] = {
    "sodium": "sodium",
    "potassium": "potassium",
    "calcium": "calcium",
    "iron": "iron",
    "magnesium": "magnesium",
    "zinc": "zinc",
    "copper": "copper",
    "manganese": "manganese",
    "phosphorus": "phosphorus",
    "selenium": "selenium",
    "iodine": "iodine",
    "chloride": "chloride",
    "chromium": "chromium",
    "molybdenum": "molybdenum",
    "vitamin-a": "vitamin_a",
    "vitamin-d": "vitamin_d",
    "vitamin-e": "vitamin_e",
    "vitamin-k": "vitamin_k",
    "vitamin-c": "vitamin_c",
    "thiamin": "thiamin",
    "vitamin-b1": "thiamin",
    "riboflavin": "riboflavin",
    "vitamin-b2": "riboflavin",
    "niacin": "niacin",
    "vitamin-b3": "niacin",
    "vitamin-pp": "niacin",
    "pantothenic-acid": "pantothenic_acid",
    "vitamin-b5": "pantothenic_acid",
    "vitamin-b6": "vitamin_b6",
    "biotin": "biotin",
    "vitamin-b7": "biotin",
    "vitamin-b8": "biotin",
    "folates": "folate",
    "folic-acid": "folate",
    "vitamin-b9": "folate",
    "vitamin-b12": "vitamin_b12",
    "sugars": "sugar",
    "sugar": "sugar",
    "saturated-fat": "saturated_fat",
    "monounsaturated-fat": "monounsaturated_fat",
    "polyunsaturated-fat": "polyunsaturated_fat",
    "trans-fat": "trans_fat",
    "cholesterol": "cholesterol",
    "caffeine": "caffeine",
}


def to_display_amount(grams: float, unit: NutrientUnit) -> float:
    """Convert an amount from grams to the nutrient's display unit with sensible rounding."""
    if unit == "g":
        val = grams
    elif unit == "mg":
        val = grams * 1000.0
    elif unit == "µg":
        val = grams * 1_000_000.0
    else:
        val = grams

    if val < 1:
        return round(val, 2)
    elif val < 10:
        return round(val, 1)
    else:
        return round(val, 1) if round(val, 1) != round(val) else float(round(val))


def parse_off_micros(nutriments: dict[str, Any]) -> dict[str, float]:
    """Parse Open Food Facts nutriments dict into standard snake_case micros_100g in grams."""
    result: dict[str, float] = {}
    for off_prefix, canon_key in OFF_NUTRIENT_MAP.items():
        val = nutriments.get(f"{off_prefix}_100g")
        if val is None:
            continue
        try:
            val_f = float(val)
        except (ValueError, TypeError):
            continue
        if val_f > 0:
            existing = result.get(canon_key, 0.0)
            result[canon_key] = max(existing, round(val_f, 8))
    return result


def format_micros_summary(micros_grams: dict[str, float]) -> list[dict[str, Any]]:
    """Format daily aggregated micronutrients (in grams) for API and MCP summaries.

    Returns an ordered list of nutrients with amount in their display unit, reference value,
    kind ('target' | 'limit' | None), and pct of reference (% DRH). Only nutrients with an
    amount are included, ordered by group then fixed order.
    """
    result: list[dict[str, Any]] = []
    for nutrient in NUTRIENTS:
        val_g = micros_grams.get(nutrient.key)
        if val_g is not None and val_g > 0:
            amount = to_display_amount(val_g, nutrient.unit)
            if amount <= 0:
                continue
            pct = (
                round((amount / nutrient.reference) * 100)
                if nutrient.reference is not None and nutrient.reference > 0
                else None
            )
            result.append(
                {
                    "key": nutrient.key,
                    "name": nutrient.name,
                    "group": nutrient.group,
                    "unit": nutrient.unit,
                    "amount": amount,
                    "reference": nutrient.reference,
                    "kind": nutrient.kind,
                    "pct": pct,
                }
            )
    return result
