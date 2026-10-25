# Healthspan (Estimated Biological Age)

`health-coach` computes a weekly estimate of biological age and pace of aging based on
lifestyle, training, and cardiovascular markers. The results are stored in the
`healthspan_weekly` table and exposed to the AI coach via the `get_healthspan` MCP tool and
in the Healthstats PWA at `/healthspan`.

> [!IMPORTANT]
> **This is an estimate, not a medical measurement.**
> Biological age calculations are based on statistical associations from published
> epidemiological cohort studies. They do not constitute a medical diagnosis, clinical
> health check, or clinical prognosis. Never present them as medical advice.

---

## 1. Mathematical Method

### Gompertz Rule of Thumb

Benjamin Gompertz observed that human mortality rates increase exponentially with age,
approximately doubling every 8 years. Using this mortality doubling time:

$$\text{years} = \frac{8}{\ln(2)} \cdot \ln(\text{HR}) \approx 11.5416 \cdot \ln(\text{HR})$$

- $\text{HR} < 1.0 \implies \ln(\text{HR}) < 0 \implies \text{years} < 0$ (**younger** biological age).
- $\text{HR} > 1.0 \implies \ln(\text{HR}) > 0 \implies \text{years} > 0$ (**older** biological age).
- $\text{HR} = 1.0 \implies \text{years} = 0.0$ (matches chronological age baseline).

### Clamping Bounds

To prevent any single outlier or metric from skewing the estimate unrealistically:
- Each individual factor is clamped to **$[-3.0, +3.0]$ years** (except body composition, clamped to **$[-1.5, +1.5]$ years** due to weaker evidence).
- The total cumulative biological age delta ($\text{delta\_years}$) is clamped to **$[-10.0, +10.0]$ years**.

### Trailing Window and Minimum Data

The algorithm evaluates factors across the **trailing 26 weeks** (with VO2max and body
composition evaluated over the latest **8 weeks**).
- A factor requires a **minimum of 4 weeks of data** within the trailing window to be included.
- Factors with fewer than 4 weeks of data are marked as "no data" (`has_data = false`) and skipped.
- The UI reports how many of the 9 factors have sufficient data (e.g., "8 z 9 signálů s daty").
- The PWA screen displays an empty state if fewer than 4 weeks of overall data are available.

### Piecewise-Linear Interpolation in Log HR

For factor curves specified with discrete anchor points $[(x_0, \text{HR}_0), \dots, (x_k, \text{HR}_k)]$,
values between anchors are interpolated **linearly in $\ln(\text{HR})$**:

$$\ln(\text{HR}(x)) = \ln(\text{HR}_i) + \frac{x - x_i}{x_{i+1} - x_i} \left(\ln(\text{HR}_{i+1}) - \ln(\text{HR}_i)\right)$$

Values outside the lowest and highest anchor points are held flat at the endpoint values.

---

## 2. The 9 Factor Curves

### 1. Sleep Regularity
- **Metric**: `daily_scores.sleep_consistency` (mean consistency score 0–100 over trailing 26 weeks).
- **Literature**: Windred et al. 2024, *SLEEP* ("Sleep regularity is a stronger predictor of mortality risk than sleep duration").
- **Anchors**:
  - Consistency 40 $\to \text{HR } 1.30$
  - Consistency 70 $\to \text{HR } 1.00$
  - Consistency 90 $\to \text{HR } 0.85$
- **Goal in UI**: `≥ 85 %`

### 2. Sleep Duration
- **Metric**: Mean hours of main sleep (`daily_scores.sleep_actual_min / 60` over trailing 26 weeks).
- **Literature**: Cappuccio et al. 2010, *Sleep* ("Sleep duration and all-cause mortality: a systematic review and meta-analysis of prospective studies").
- **Anchors**:
  - 5.0 h $\to \text{HR } 1.30$
  - 6.0 h $\to \text{HR } 1.12$
  - 7.0 h $\to \text{HR } 1.00$
  - 8.0 h $\to \text{HR } 1.00$
  - 9.0 h $\to \text{HR } 1.15$
  - 10.0 h $\to \text{HR } 1.30$
- **Goal in UI**: `7–9 h`

### 3. Moderate Activity
- **Metric**: Minutes per week in heart rate zones 1–3 (`daily_scores.zone_minutes` Z1–Z3, weekly mean over trailing 26 weeks).
- **Literature**: Lee et al. 2022, *Circulation* ("Long-term leisure-time physical activity intensity and all-cause and cause-specific mortality").
- **Anchors**:
  - 0 min/wk $\to \text{HR } 1.25$
  - 75 min/wk $\to \text{HR } 1.00$
  - 150 min/wk $\to \text{HR } 0.85$
  - 300 min/wk $\to \text{HR } 0.78$
- **Goal in UI**: `≥ 150 min`

### 4. Vigorous Activity
- **Metric**: Minutes per week in heart rate zones 4–5 (`daily_scores.zone_minutes` Z4–Z5, weekly mean over trailing 26 weeks).
- **Literature**: Lee et al. 2022, *Circulation*.
- **Anchors**:
  - 0 min/wk $\to \text{HR } 1.05$
  - 20 min/wk $\to \text{HR } 1.00$
  - 75 min/wk $\to \text{HR } 0.85$
  - 150 min/wk $\to \text{HR } 0.80$
- **Goal in UI**: `≥ 75 min`

### 5. Strength Training
- **Metric**: Hours per week of resistance training (`strength_sessions` duration, weekly mean over trailing 26 weeks).
- **Literature**: Momma et al. 2022, *BJSM* ("Muscle-strengthening activities are associated with lower risk and mortality in major non-communicable diseases: a systematic review and meta-analysis"). Shows a J-shaped curve where 30–60 min/week has the largest reduction, tapering off beyond 2 hours.
- **Anchors**:
  - 0.0 h/wk $\to \text{HR } 1.10$
  - 0.5 h/wk $\to \text{HR } 0.90$
  - 1.0 h/wk $\to \text{HR } 0.85$
  - 2.5 h/wk $\to \text{HR } 0.90$
  - 4.0 h/wk $\to \text{HR } 0.95$
- **Goal in UI**: `1–2,5 h`

### 6. Daily Steps
- **Metric**: Steps per day (`daily_activity.steps` mean over trailing 26 weeks).
- **Literature**: Paluch et al. 2022, *Lancet Public Health* ("Daily steps and all-cause mortality: a meta-analysis of 15 international cohorts", under-60 curve).
- **Anchors**:
  - 2 500 steps $\to \text{HR } 1.40$
  - 4 000 steps $\to \text{HR } 1.20$
  - 6 000 steps $\to \text{HR } 1.00$
  - 8 000 steps $\to \text{HR } 0.85$
  - 10 000 steps $\to \text{HR } 0.78$
  - 12 000 steps $\to \text{HR } 0.76$
- **Goal in UI**: `≥ 8 000/den`

### 7. Resting Heart Rate
- **Metric**: Median resting heart rate (`daily_vitals.resting_hr` median over trailing 26 weeks).
- **Literature**: Zhang et al. 2016, *CMAJ* ("Association of resting heart rate with risk of all-cause and cardiovascular mortality: a meta-analysis").
- **Formula**:
  $$\text{HR} = 1.09^{\frac{\text{RHR} - 60}{10}}$$
  Each 10 bpm above 60 bpm corresponds to a 9% increase in relative hazard.
- **Goal in UI**: `≤ 60 bpm`

### 8. Cardiorespiratory Fitness (VO2max)
- **Metric**: Median cardio fitness score (`daily_vitals.cardio_fitness` over the latest 8 weeks).
- **Literature**: Kodama et al. 2009, *JAMA* ("Cardiorespiratory fitness as a quantitative predictor of all-cause mortality and cardiovascular events").
- **Formula**: $\text{HR} = 0.87^{\frac{\text{VO2max} - \text{ref}}{3.5}}$ (+3.5 ml/kg/min yields a 13% reduction in risk).
- **Reference Table by Age Decade and Sex**:
  | Decade | Male Reference | Female Reference |
  | --- | --- | --- |
  | 20–29 | 44.0 | 38.0 |
  | 30–39 | 42.0 | 36.0 |
  | 40–49 | 39.0 | 33.0 |
  | 50–59 | 36.0 | 30.0 |
  | 60+ | 32.0 | 26.0 |
- **Goal in UI**: `podle věku`

### 9. Body Composition
- **Metric**: Median body fat percentage (`body_metrics.body_fat_pct` over the latest 8 weeks).
- **Literature**: Heitmann et al. (weak observational evidence, subject to confounding).
- **Clamping**: Clamped to **$\pm 1.5$ years**.
- **Anchors**:
  - Male: 10% $\to \text{HR } 1.00$, 18% $\to \text{HR } 1.00$, 25% $\to \text{HR } 1.10$, 30% $\to \text{HR } 1.25$
  - Female: +8 percentage points on each anchor (18%, 26%, 33%, 38%).
- **Goal in UI**: `podle věku`

---

## 3. Demographics and Sex Resolution

- Chronological age is derived from the profile birth year (`set_profile`, fallback `HC_BIRTH_YEAR`). Without a birth year, $\text{delta\_years}$ is still computed, but `age` and `biological_age` remain `null`.
- Biological sex comes from the profile (`set_profile`, fallback `HC_SEX`; `"male"` or `"female"`).
- If no sex is set (`None`), factors that depend on sex (VO2max and Body Composition) compute the male and female results independently and take the **arithmetic mean** of the two.

---

## 4. Pace of Aging

The pace of aging reflects whether biological age is diverging from or catching up to
chronological time.
- For each of the last 26 weeks, the weekly biological age delta is calculated.
- An ordinary least squares (OLS) linear regression is fitted across calendar years:
  $$\text{pace} = 1.0 + \text{slope}(\text{delta\_years} \text{ per calendar year})$$
- A stable lifestyle with constant delta gives $\text{slope} = 0 \implies \text{pace} = 1.0\times$.
- Improving health markers (delta becoming more negative over time) gives $\text{slope} < 0 \implies \text{pace} < 1.0\times$ (e.g. $0.8\times$).
- Worsening health markers give $\text{slope} > 0 \implies \text{pace} > 1.0\times$.
- The pace is clamped to **$[0.5, 1.5]$**.
- At least **8 weekly values** are required; otherwise, pace is `null`.

---

## 5. Storage and Worker Schedule

Weekly healthspan results are stored in PostgreSQL in the `healthspan_weekly` table:

```sql
CREATE TABLE healthspan_weekly (
    week_start DATE PRIMARY KEY, -- Monday of the evaluated week
    delta_years NUMERIC(4,1),    -- e.g. -2.6
    pace NUMERIC(3,2),           -- e.g. 0.80
    factors JSONB NOT NULL,      -- array of factor results
    factors_with_data SMALLINT NOT NULL,
    age SMALLINT,
    algo_version SMALLINT NOT NULL,
    source TEXT DEFAULT 'worker' NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
```

### Worker Daemon
The worker runs `healthspan_recent` nightly at **05:00 in `HC_TIMEZONE`**, recomputing the
current week and previous week to incorporate late-syncing device data.

### CLI Backfill
To recompute past weeks:
```sh
health-coach healthspan backfill --weeks 26
```

---

## 6. Access and Exposure

- **MCP Tool**: `get_healthspan(weeks=12)` returns the latest weekly estimate, factor breakdown, and trailing history for the AI assistant.
- **Web API**: `GET /api/healthspan?weeks=26` returns `has_enough_data`, `latest`, `history`, and `as_of`.
- **Healthstats PWA**: Screen `/healthspan` displaying biological age delta, pace of aging, signal count, 6-month factor table, and notes. Accessible directly from the Trends screen via the sub-navigation grid.
