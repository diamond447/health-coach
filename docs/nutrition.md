# Nutrition and Micronutrients

Health-coach tracks macronutrients (calories, protein, carbohydrates, fats, fiber) and
micronutrients (vitamins, minerals, and other dietary components) in Postgres. Data is
exposed through the MCP server tools (`get_nutrition_summary`, `log_meal`, `save_food`,
`search_food`) and the `/api/nutrition` web endpoint on the Jídlo screen.

## Sources

Micronutrients come from two sources:

1. **Google Health API**:
   - `nutritionLog.nutrients[]` returns `{nutrient, quantity: {grams}}`.
   - Google Health enum values are mapped to canonical snake_case keys (defined in
     `src/health_coach/nutrients.py`).
   - Every nutrient except `PROTEIN`, `DIETARY_FIBER`, and `CARBOHYDRATES` (which are mapped
     to the top-level macro columns on `nutrition_entries`) is stored in `micros`.
   - Zero and negative values are skipped. `FOLIC_ACID` and `FOLATE` are merged into `folate`.
   - When Google Health creates a linked food in `foods`, `foods.micros_100g` is populated
     and scaled to 100 g according to the serving grams.
   - Because raw payloads are stored untouched in `raw_payloads`, historical data can be
     re-parsed without fetching again (see [Post-deploy step](#post-deploy-step)).

2. **Open Food Facts API**:
   - Products fetched via `search_food` or barcode lookup contain `nutriments.<key>_100g`
     in grams per 100 g (e.g. `sodium_100g`, `potassium_100g`, `vitamin-c_100g`,
     `sugars_100g`, `saturated-fat_100g`, etc.).
   - `parse_product` maps these into `micros_100g` on the food record.
   - `save_food` stores `micros_100g` in the `foods` table.
   - `log_meal` with a `food_id` and grams computes `nutrition_entries.micros` as
     `micros_100g * grams / 100`. Updating grams on a food-linked entry via
     `update_nutrition_entry` recomputes its `micros`. Free-text entries without a linked
     food do not have micronutrients.

## Storage

Migration `0010_micronutrients.py` adds:

- `foods.micros_100g` (`jsonb`, nullable): micronutrients in grams per 100 g.
- `nutrition_entries.micros` (`jsonb`, nullable): micronutrients in grams for the logged entry.

Both store JSON dictionaries with snake_case nutrient keys (`sodium`, `potassium`,
`vitamin_c`, `folate`, `sugar`, `saturated_fat`, etc.) and float amounts in grams.

Canonical keys, Czech display names, units, groups, and reference values are centrally
defined in `src/health_coach/nutrients.py`.

## Reference Values (Adults)

Daily reference values (DRH / NRV) follow official standards:

### Targets: EU Regulation 1169/2011 Annex XIII Part A

| Nutrient | Czech name | Group | Unit | Daily reference (DRH) |
| --- | --- | --- | --- | --- |
| `potassium` | Draslík | minerály | mg | 2 000 |
| `chloride` | Chlorid | minerály | mg | 800 |
| `calcium` | Vápník | minerály | mg | 800 |
| `phosphorus` | Fosfor | minerály | mg | 700 |
| `magnesium` | Hořčík | minerály | mg | 375 |
| `iron` | Železo | minerály | mg | 14 |
| `zinc` | Zinek | minerály | mg | 10 |
| `copper` | Měď | minerály | mg | 1.0 |
| `manganese` | Mangan | minerály | mg | 2.0 |
| `selenium` | Selen | minerály | µg | 55 |
| `chromium` | Chrom | minerály | µg | 40 |
| `molybdenum` | Molybden | minerály | µg | 50 |
| `iodine` | Jód | minerály | µg | 150 |
| `vitamin_a` | Vitamín A | vitamíny | µg | 800 |
| `vitamin_d` | Vitamín D | vitamíny | µg | 5.0 |
| `vitamin_e` | Vitamín E | vitamíny | mg | 12 |
| `vitamin_k` | Vitamín K | vitamíny | µg | 75 |
| `vitamin_c` | Vitamín C | vitamíny | mg | 80 |
| `thiamin` | Thiamin (B1) | vitamíny | mg | 1.1 |
| `riboflavin` | Riboflavin (B2) | vitamíny | mg | 1.4 |
| `niacin` | Niacin (B3) | vitamíny | mg | 16 |
| `pantothenic_acid` | Kyselina pantothenová (B5) | vitamíny | mg | 6.0 |
| `vitamin_b6` | Vitamín B6 | vitamíny | mg | 1.4 |
| `biotin` | Biotin (B7) | vitamíny | µg | 50 |
| `folate` | Kyselina listová (B9) | vitamíny | µg | 200 |
| `vitamin_b12` | Vitamín B12 | vitamíny | µg | 2.5 |

### Limits

| Nutrient | Czech name | Group | Unit | Limit | Source |
| --- | --- | --- | --- | --- | --- |
| `sodium` | Sodík | minerály | mg | < 2 000 | WHO (2012) Sodium intake guideline |
| `sugar` | Cukry | ostatní | g | < 50 | WHO (2015) Free sugars guideline (10 % of 2000 kcal) |
| `saturated_fat` | Nasycené tuky | ostatní | g | < 22 | Nordic / DGE / EFSA (10 % of 2000 kcal) |
| `caffeine` | Kofein | ostatní | mg | ≤ 400 | EFSA (2015) Safety of caffeine opinion |

### Tracked Without Reference

`cholesterol` (mg), `monounsaturated_fat` (g), `polyunsaturated_fat` (g), `trans_fat` (g),
and `unsaturated_fat` (g) are tracked and displayed without reference bars or percentage targets.

## API and UI

- `GET /api/nutrition?date=YYYY-MM-DD` returns:
  - `micros`: list of `{key, name, group, unit, amount, reference, kind, pct}` for the day,
    including only nutrients with an amount > 0, ordered by group (`minerály`, `vitamíny`,
    `ostatní`) then fixed order.
  - `micros_coverage`: `{entries_with: n, entries_total: m}`.
- Jídlo screen displays a "Vitamíny a minerály" card at the bottom:
  - Categorized into Minerály, Vitamíny, Ostatní.
  - Rows show name, amount with unit, thin bar up to 100 % (grey to food colour for targets;
    orange/red when limits are exceeded), and "% DRH".
  - Subtitle: "Data z {n} z {m} záznamů · DRH = denní referenční hodnota EU".
  - Empty state when no entry has micronutrient data:
    "Zatím žádná data o vitamínech a minerálech. Doplní se z Google Health u potravin, které je mají."

## Post-Deploy Step

After applying migration `0010_micronutrients` in production, run:

```sh
health-coach remap google
```

This re-runs the mappers over stored raw responses in `raw_payloads` and populates `micros`
and `foods.micros_100g` for all existing entries without needing to re-fetch from Google.
