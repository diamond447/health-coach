# Habit Journal & Sleep Settings

The journal allows tracking evening habits, supplements, and lifestyle behaviours to evaluate
their relationship with next-day WHOOP-style recovery scores. It also provides runtime configuration
for baseline sleep needs and alarm times.

---

## 1. Tracked Behaviours

Behaviours are identified by a snake_case key (`^[a-z][a-z0-9_]{1,39}$`). The assistant uses
the following standardized keys to maintain consistency, though any valid custom key is supported:

| Key | Description | Amount / Units |
| --- | --- | --- |
| `alcohol` | Alcoholic drinks consumed | Standard drinks |
| `caffeine_late` | Caffeine consumed after 14:00 | Cups / servings |
| `late_meal` | Meal consumed less than 2 hours before bed | Optional kcal or flag |
| `screen_in_bed` | Screen use while in bed | Flag or minutes |
| `sauna` | Sauna session | Minutes or flag |
| `cold_exposure` | Cold shower, cold plunge, or ice bath | Minutes or flag |
| `stretching` | Stretching or mobility work before bed | Minutes or flag |
| `meditation` | Meditation or breathwork session | Minutes or flag |
| `reading` | Reading before sleep | Minutes or flag |
| `nap` | Daytime nap | Minutes or flag |
| `high_stress` | Unusually high stress day | 1-5 scale or flag |
| `illness` | Acute illness, cold, fever, or infection | Flag |
| `travel` | Travel, flight, or major time zone shift | Flag |
| `sex` | Sexual activity | Flag |
| `magnesium` | Magnesium supplement before bed | mg or flag |

---

## 2. Tools

- `log_journal(date=None, entries=[{behavior, amount?, note?}])`:
  Logs behaviours for a calendar date. Date defaults to **yesterday** because people typically
  log the evening before during their morning review. Upserts per `(local_date, behavior)`.
- `get_journal(start=None, end=None)`:
  Retrieves logged entries within an inclusive date range (defaults to the last 14 days).
- `delete_journal_entry(entry_id)`:
  Soft-deletes a journal entry (`deleted_at`).
- `get_journal_insights(days=60)`:
  Calculates recovery differences for tracked behaviours over the lookback window.
- `set_sleep_settings(base_need_min=None, alarm_time=None, clear_alarm=False)`:
  Configures personal sleep scoring settings in `app_settings`.
- `get_sleep_settings()`:
  Retrieves the current sleep scoring settings.
- `set_profile(hr_max=None, birth_year=None, sex=None, clear=None)`:
  Stores the scoring profile in `app_settings` (`hr_max` 120-230 bpm, `birth_year`,
  `sex` `male`/`female`); `clear` removes keys. Stored values take precedence over
  `HC_HR_MAX`, `HC_BIRTH_YEAR` and `HC_SEX`. New values apply to recent days at the next
  scores refresh (within 30 minutes, the last 7 days nightly); run
  `health-coach scores backfill` to recompute older days.
- `get_profile()`:
  Returns the profile, the age, and the max heart rate the scores use with its source
  (measured, estimated from age, or default).

---

## 3. Insights Methodology & Statistical Limits

The `get_journal_insights` tool evaluates how specific habits correlate with autonomic recovery:

1. **Next-Day Association**:
   A behaviour logged on calendar day $D$ is matched with the recovery score on day $D+1$
   (the morning after the evening the behaviour occurred).
2. **Explicit "Without" Requirement**:
   A day counts as "without" a given behaviour **only if at least one other behaviour was
   logged on that day**. Unlogged days are treated as missing data, not as "no alcohol" or "no sauna".
   Days lacking a next-day recovery score in `daily_scores` are excluded.
3. **Sample Size Threshold**:
   A behaviour is only reported under `insights` if it has **at least 5 days with** and
   **at least 5 days without** the behaviour. Behaviours with fewer observations are listed
   under `insufficient` along with their counts.
4. **Percentage Point Difference**:
   Reported as $\Delta = \text{mean}(\text{recovery}_{\text{with}}) - \text{mean}(\text{recovery}_{\text{without}})$.

### Critical Limits

> [!WARNING]
> **Correlation is not causation**: A positive or negative correlation does not prove that a habit
> directly caused higher or lower recovery.
>
> - **Confounders & Clustering**: Habits rarely occur in isolation. For instance, alcohol consumption
>   often coincides with late restaurant meals, delayed bedtimes, and weekend social events.
> - **Sample Size**: 5 days with and 5 days without is a minimal threshold to screen out pure noise.
>   Coaches should look for consistent signals over 20+ tracked instances before recommending changes.
> - **No Blind Claims**: The assistant is instructed never to claim an effect that the data does
>   not demonstrate.

---

## 4. Sleep Settings

Settings stored in the `app_settings` table override default environment configuration:

- `sleep_need_base_min`: Baseline sleep need (validated between 360 and 600 minutes, i.e. 6 to 10 hours).
  Overrides `HC_SLEEP_NEED_BASE_MIN`.
- `alarm_time`: Fixed wake-up time formatted as `"HH:MM"` (e.g. `"06:30"`). When set, the worker's
  bedtime planner calculates tonight's planned bedtime using this fixed wake target instead of the
  median of recent wake times.

---

## 5. Logging from the Healthstats Web App (PWA)

Instead of typing yesterday's evening habits to the coach in Claude, you can tap them directly
in the Healthstats PWA on the **Deník (`/denik`)** screen:

- **Quick Toggles**: Tapping a habit chip toggles it on or off for yesterday's date.
- **Inline Stepper**: For countable habits (`alcohol` in drinks, `caffeine_late` in cups),
  activating the chip displays an inline stepper (`−` / value / `+`, step 1, min 1). Changes
  are debounced and saved automatically after ~600 ms.
- **Audit & Source**: Entries created via the PWA are tagged with `source = 'web'`.
- **Configuration**: Enabled by providing `HC_WEB_JOURNAL_DATABASE_URL` in `.env` (connects
  with `Role.web_journal`). When omitted, the Deník screen operates in read-only mode.
