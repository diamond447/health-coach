# Daily Scores (Recovery, Strain, Sleep)

`health-coach` computes daily WHOOP-style scores to track physiological readiness, training
exertion, and sleep need. These are computed by the worker daemon, stored in the `daily_scores`
table, and exposed to the assistant through MCP tools (`get_scores`, `get_context_snapshot`).

```
                    ┌───────────────────────────┐
                    │ Trailing 30 nights vitals │
                    └─────────────┬─────────────┘
                                  ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────────┐
│ Last night sleep │───>│  Recovery Score  │───>│ Daily Strain Target      │
│  & daily vitals  │    │  (1-99, G/Y/R)   │    │ [3 + 12r, 6 + 12r]       │
└──────────────────┘    └──────────────────┘    └──────────────────────────┘

┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────────┐
│ Intraday 1-min HR│───>│    Day Strain    │───>│  Sleep Need Bonus        │
│ & gym sessions   │    │      (0-21)      │    │  max(0, strain - 7) * 3  │
└──────────────────┘    └──────────────────┘    └─────────────┬────────────┘
                                                              ▼
                        ┌──────────────────┐    ┌──────────────────────────┐
                        │    Sleep Plan    │<───│ Sleep Need & Performance │
                        │ bedtime and wake │    │ debt decay over 14 days  │
                        └──────────────────┘    └──────────────────────────┘
```

---

## 1. Robust Baselines

Vitals vary between individuals. Instead of fixed population thresholds, signals are evaluated
against personal baselines computed over the **30 nights before the scored day** (the scored day
is excluded).

Baselines use the robust median and Median Absolute Deviation (MAD):

$$\text{center} = \text{median}(V), \quad \text{scale} = \max(1.4826 \cdot \text{MAD}(V), \text{floor})$$

At least 7 valid nights are required; fewer returns `None` (baseline not ready).
Scale floors prevent division by zero or oversensitivity during periods of low variability:

| Metric | Scale Floor | Notes |
| --- | --- | --- |
| $\ln(\text{HRV RMSSD})$ | 0.08 | Evaluated on natural logarithm of RMSSD (Plews et al. 2013) |
| Resting HR | 1.5 bpm | |
| Breathing Rate | 0.5 breaths/min | |
| Skin Temperature Delta | 0.15 °C | |

---

## 2. Recovery Score (1–99)

Recovery reflects autonomic nervous system balance and physiological readiness for the day,
computed from the night that ended on local calendar day $D$.

### Components and z-scores

Signals are converted to z-scores oriented so **higher is better**, each clamped to $[-3, 3]$:

- **HRV (RMSSD)** (weight 0.50): $(\ln(\text{rmssd}) - \text{center}) / \text{scale}$
- **Resting HR** (weight 0.20): $(\text{center} - \text{rhr}) / \text{scale}$
- **Sleep performance** (weight 0.15): $(\text{perf} / 100 - 0.85) / 0.12$
- **Breathing rate** (weight 0.05): $(\text{center} - \text{rate}) / \text{scale}$
- **Skin temperature** (weight 0.05): $-\lvert\text{delta} - \text{center}\rvert / \max(\text{scale}, 0.3)$
- **$\text{SpO}_2$** (weight 0.05, no baseline): $\min(0, (\text{spo2} - 95) / 2.5)$

Missing signals or signals without a valid baseline are omitted, and weights are renormalised
over the present ones. If **both HRV and resting HR are missing**, recovery is `None`.

### Score formula

The blended z-score $z = \sum (w_i z_i) / \sum w_i$ is mapped through a logistic sigmoid:

$$\text{score} = \text{clamp}\left(\text{round}\left(\frac{100}{1 + \exp(-(1.6 z + 0.3))}\right), 1, 99\right)$$

- Baseline ($z = 0$) evaluates to **57**.
- **Green zone**: $\ge 67$ (well recovered, primed for high strain)
- **Yellow zone**: $34–66$ (normal, maintain baseline strain)
- **Red zone**: $\le 33$ (impaired recovery, focus on rest or active recovery)

### Point contributions

Each present component reports `points`: the difference between the full recovery score and the
score computed without that component's term in the blend ($z - \tilde{w}_i z_i$). The points
sum approximately to $\text{score} - 57$, allowing the UI to show contributions like "HRV +9".

### Flags

- `"illness"`: Resting HR $> \text{center} + 5\text{ bpm}$ and $\text{RMSSD} < 0.85 \cdot \exp(\text{center}_{\ln\text{HRV}})$ on **both** $D$ and $D-1$.
- `"temperature"`: $\lvert\text{skin delta} - \text{center}\rvert \ge 0.6\text{ °C}$.
- `"low_spo2"`: Average $\text{SpO}_2 < 94\%$.

### Strain target

From recovery fraction $r = \text{score} / 100$:

$$\text{target} = \left[\text{round}(3 + 12r, 1), \; \text{round}(6 + 12r, 1)\right]$$

---

## 3. Day Strain (0–21)

Strain measures cardiovascular and muscular exertion over the local calendar day
(00:00 to 24:00 in `HC_TIMEZONE`).

### Cardio load (Banister TRIMP)

1. Intraday heart rate samples are resampled to 1-minute means. Minutes without samples inside gaps
   longer than 5 minutes get nothing.
2. **Resting HR anchor**: Median resting HR over the 7 days ending $D$ (fallback 60 bpm).
3. **Heart rate max ($HR_{\max}$)**: From `HC_HR_MAX`, or estimated via Tanaka ($208 - 0.7 \cdot \text{age}$), fallback 190.
4. **Heart Rate Reserve fraction**: $x = \text{clamp}\left(\frac{hr - \text{rest}}{HR_{\max} - \text{rest}}, 0, 1\right)$.
5. **Gating filter**:
   - $x < 0.30 \implies 0$ (sedentary noise filtered out)
   - $0.30 \le x < 0.40$ outside workout windows $\implies \text{scale} = \frac{x - 0.30}{0.10}$
   - $x \ge 0.40$ or inside any activity window $\implies 1.0$
6. **Banister weighting factor $y(x)$**:
   - Male: $y(x) = 0.64 \cdot \exp(1.92x)$
   - Female: $y(x) = 0.86 \cdot \exp(1.67x)$
   - Unset: arithmetic mean of male and female curves
7. **Cardio load**: $\sum_{\text{minutes}} x \cdot y(x) \cdot \text{scale}$.

### Muscular load (strength training)

For each openGym session on day $D$:
- **Working volume**: $\sum \text{reps} \cdot \text{weight\_kg}$ over working sets (`is_warmup = false`).
- **Session RPE**: Mean set RPE; fallback $10 - \text{RIR}$; fallback 7.0.
- **sRPE**: $\text{Session RPE} \cdot \text{duration\_min}$.
- **30-day caps**: 90th percentile of per-session volume and sRPE over trailing 30 days, with
  floors $\text{cap}_{\text{vol}} \ge 5000\text{ kg}$ and $\text{cap}_{\text{srpe}} \ge 480$.
- **Session score**: $\text{clamp}\left(50 \cdot \frac{\text{volume}}{\text{cap}_{\text{vol}}} + 50 \cdot \frac{\text{sRPE}}{\text{cap}_{\text{srpe}}}, 0, 100\right)$.
- **Muscular load**: $45 \cdot (\text{score} / 100)^{1.6}$.

### Total strain

$$\text{strain} = \text{round}\left(21 \cdot \left(1 - \exp\left(-\frac{\text{cardio} + \text{muscular}}{100}\right)\right), 1\right)$$

Calibration benchmarks: load 5 $\to$ ~1.0, 25 $\to$ ~4.6, 60 $\to$ ~9.5, 85 $\to$ ~12.0, 135 $\to$ ~15.6.

### Heart rate zones (%HRR)

- Z1: 50%–60% HRR
- Z2: 60%–70% HRR
- Z3: 70%–80% HRR
- Z4: 80%–90% HRR
- Z5: $\ge 90\%$ HRR

### Activities

Each exercise and strength session records `{kind, name, start, end, avg_hr, max_hr, load, strain}`,
where activity strain is computed from that activity's load alone.

---

## 4. Sleep Need, Debt, and Performance

Evaluated for the primary sleep session (`is_main = true`) with wake date `local_date = D`.

### Sleep need

$$\text{need}(D) = \text{clamp}(\text{base} + \text{debt} + \text{strain\_bonus} - \text{nap\_credit}, 360, 660)$$

- $\text{base}$: `HC_SLEEP_NEED_BASE_MIN` (default 480 min = 8h).
- $\text{strain\_bonus} = \max(0, \text{strain}(D-1) - 7) \cdot 3$ minutes.
- $\text{nap\_credit}$: Sum duration of non-main sleep sessions on $D-1$.
- **Sleep debt**: Exponentially decaying deficit over trailing 14 nights ($k = 1..14$):

$$\text{debt} = \min\left(120, \; \frac{\sum_k 0.75^{k-1} \max(0, \text{need}(D-k) - \text{actual}(D-k))}{\sum_k 0.75^{k-1}}\right)$$

### Performance, efficiency, and consistency

- **Performance**: $\min(100, \text{round}(\text{actual} / \text{need} \cdot 100))$.
- **Efficiency**: From wearable, or $\text{round}(\text{duration} / \text{time\_in\_bed} \cdot 100)$.
- **Consistency**: Standard deviation of sleep midpoints (in minutes relative to 18:00 local time)
  over the last 7 main sleeps:

$$\text{consistency} = \text{clamp}\left(100 - \text{SD} \cdot \frac{100}{120}, 0, 100\right)$$

### Bedtime plan for tonight (only computed for today)

- $\text{need\_tonight} = \text{base} + \text{debt including last night} + \text{today strain bonus} - \text{today naps}$.
- $\text{in\_bed} = \text{need\_tonight} / \text{mean efficiency of last 7 nights}$ (fallback 0.90).
- $\text{wake}$: Median wake time of last 14 main sleeps (fallback 07:00 local).
- $\text{bedtime} = \text{wake} - \text{in\_bed}$.

---

## Known Limitations

1. **Calendar-day strain**: Strain is computed for the local day (00:00 to 24:00). Workouts
   stretching past midnight contribute to the day each minute falls on.
2. **No intraday HRV**: The Google Health API currently provides nighttime resting HRV (RMSSD).
   Intraday stress / HRV spikes are not tracked.
3. **Estimated HR max**: When `HC_HR_MAX` is unset, the Tanaka formula ($208 - 0.7 \cdot \text{age}$)
   or 190 bpm is used. Setting personal `HC_HR_MAX` provides the most accurate %HRR strain.

---

## Credits & Prior Art

Formulas and concepts are inspired by public literature and open-source projects (implemented
independently without copying code):

- **OpenStrap** ([github.com/OpenStrap/analytics](https://github.com/OpenStrap/analytics), AGPL-3.0): Open-source wearable analytics and recovery modelling concepts.
- **Watch2Whoop** ([github.com/SongyuQi-Francisco/Watch2Whoop](https://github.com/SongyuQi-Francisco/Watch2Whoop), AGPL-3.0): WHOOP-style strain and recovery formulas.
- **Atria** ([github.com/adidshaft/atria](https://github.com/adidshaft/atria), MIT): Cardiovascular load concepts and zone computations.
- **Banister TRIMP** (Banister, E.W., 1991): Heart rate training impulse and exponential weighting.
- **Plews et al. 2013**: $\ln(\text{RMSSD})$ transformation and rolling baseline dynamics for athlete recovery.

---

## See Also

- [Healthspan](healthspan.md): Weekly estimated biological age, pace of aging, and factor curves.
