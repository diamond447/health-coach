-- Views of revision 0001. The main read surface for MCP tools, query_sql and Grafana.
-- A later change to a view gets a new revision with its own SQL file; never edit this one.

-- Daily body values: the earliest reading of the day wins (morning weigh-in), whatever
-- the source. Soft-deleted rows are ignored.
CREATE VIEW v_body_daily AS
SELECT d.local_date,
       (SELECT b.weight_kg FROM body_metrics b
         WHERE b.local_date = d.local_date AND b.deleted_at IS NULL AND b.weight_kg IS NOT NULL
         ORDER BY b.ts LIMIT 1) AS weight_kg,
       (SELECT b.body_fat_pct FROM body_metrics b
         WHERE b.local_date = d.local_date AND b.deleted_at IS NULL AND b.body_fat_pct IS NOT NULL
         ORDER BY b.ts LIMIT 1) AS body_fat_pct,
       (SELECT b.waist_cm FROM body_metrics b
         WHERE b.local_date = d.local_date AND b.deleted_at IS NULL AND b.waist_cm IS NOT NULL
         ORDER BY b.ts LIMIT 1) AS waist_cm
FROM (SELECT DISTINCT local_date FROM body_metrics WHERE deleted_at IS NULL) d;

COMMENT ON VIEW v_body_daily IS
  'One row per day with any body metric: earliest weight, body fat and waist of the day.';

-- Weight trend: 7-day moving average of daily weights and an exponentially smoothed
-- trend (alpha 0.1 per day, compounded over gaps between weigh-ins). weekly_rate_kg is
-- the trend change against the latest weigh-in 7 to 14 days earlier, scaled to 7 days.
CREATE VIEW v_weight_trend AS
WITH RECURSIVE w AS (
    SELECT local_date, weight_kg, row_number() OVER (ORDER BY local_date) AS n
    FROM v_body_daily
    WHERE weight_kg IS NOT NULL
), t AS (
    SELECT n, local_date, weight_kg, weight_kg::numeric AS trend
    FROM w WHERE n = 1
    UNION ALL
    SELECT w.n, w.local_date, w.weight_kg,
           t.trend + (1 - power(0.9::numeric, (w.local_date - t.local_date)::numeric))
                     * (w.weight_kg - t.trend)
    FROM t JOIN w ON w.n = t.n + 1
)
SELECT t.local_date,
       t.weight_kg,
       round(avg(t.weight_kg) OVER (ORDER BY t.local_date
             RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW), 2) AS avg_7d_kg,
       round(t.trend, 2) AS trend_kg,
       round((t.trend - p.trend) * 7.0 / (t.local_date - p.local_date), 2) AS weekly_rate_kg
FROM t
LEFT JOIN LATERAL (
    SELECT t2.local_date, t2.trend FROM t t2
    WHERE t2.local_date BETWEEN t.local_date - 14 AND t.local_date - 7
    ORDER BY t2.local_date DESC LIMIT 1
) p ON true;

COMMENT ON VIEW v_weight_trend IS
  'Daily weigh-ins with 7-day average, smoothed trend and weekly rate of trend change (kg/week).';

-- Daily nutrition totals against the targets in force that day.
CREATE VIEW v_nutrition_daily AS
SELECT n.local_date,
       n.kcal, n.protein_g, n.carbs_g, n.fat_g, n.fiber_g,
       n.entries, n.meals_logged,
       t.phase,
       t.kcal AS target_kcal,
       t.protein_g AS target_protein_g,
       t.protein_max_g AS target_protein_max_g,
       t.carbs_g AS target_carbs_g,
       t.fat_g AS target_fat_g,
       n.kcal - t.kcal AS kcal_vs_target,
       n.protein_g - t.protein_g AS protein_vs_target_g,
       round(n.protein_g / nullif(bw.weight_kg, 0), 2) AS protein_g_per_kg
FROM (
    SELECT local_date,
           round(sum(kcal)) AS kcal,
           round(sum(protein_g), 1) AS protein_g,
           round(sum(carbs_g), 1) AS carbs_g,
           round(sum(fat_g), 1) AS fat_g,
           round(sum(fiber_g), 1) AS fiber_g,
           count(*) AS entries,
           count(DISTINCT meal) AS meals_logged
    FROM nutrition_entries
    WHERE deleted_at IS NULL
    GROUP BY local_date
) n
LEFT JOIN LATERAL (
    SELECT * FROM targets tg
    WHERE tg.effective_from <= n.local_date
    ORDER BY tg.effective_from DESC, tg.id DESC LIMIT 1
) t ON true
LEFT JOIN LATERAL (
    SELECT avg(b.weight_kg) AS weight_kg FROM v_body_daily b
    WHERE b.local_date BETWEEN n.local_date - 6 AND n.local_date
) bw ON true;

COMMENT ON VIEW v_nutrition_daily IS
  'Daily intake totals vs targets in force, protein per kg of 7-day average weight, entry count.';

-- Hard sets per muscle and ISO week. A hard set is a working set (not warm-up, reps > 0)
-- with RIR <= 4 or no RIR logged. Primary muscles count 1, secondary 0.5.
CREATE VIEW v_strength_volume_weekly AS
WITH hard AS (
    SELECT s.local_date, x.primary_muscles, x.secondary_muscles
    FROM strength_sets ss
    JOIN strength_sessions s ON s.id = ss.session_id
    JOIN exercises x ON x.wger_id = ss.exercise_id
    WHERE NOT ss.is_warmup
      AND coalesce(ss.reps, 0) > 0
      AND (ss.rir IS NULL OR ss.rir <= 4)
), m AS (
    SELECT local_date, unnest(primary_muscles) AS muscle, 1.0 AS weight FROM hard
    UNION ALL
    SELECT local_date, unnest(secondary_muscles), 0.5 FROM hard
)
SELECT to_char(local_date, 'IYYY-"W"IW') AS iso_week,
       date_trunc('week', local_date)::date AS week_start,
       muscle,
       sum(weight) AS hard_sets,
       count(*) FILTER (WHERE weight = 1.0) AS direct_sets
FROM m
GROUP BY 1, 2, 3;

COMMENT ON VIEW v_strength_volume_weekly IS
  'Hard sets per muscle group per ISO week (primary muscle = 1, secondary = 0.5).';

-- Best estimated 1RM per exercise per session (Epley). Only sets that say something
-- about strength: 1-12 reps, weight > 0, RIR <= 3 or not logged.
CREATE VIEW v_exercise_e1rm AS
SELECT DISTINCT ON (s.id, ss.exercise_id)
       s.id AS session_id,
       s.local_date,
       ss.exercise_id,
       x.name AS exercise,
       ss.weight_kg,
       ss.reps,
       ss.rir,
       round(CASE WHEN ss.reps = 1 THEN ss.weight_kg
                  ELSE ss.weight_kg * (1 + ss.reps / 30.0) END, 1) AS e1rm_kg
FROM strength_sets ss
JOIN strength_sessions s ON s.id = ss.session_id
JOIN exercises x ON x.wger_id = ss.exercise_id
WHERE NOT ss.is_warmup
  AND ss.weight_kg > 0
  AND ss.reps BETWEEN 1 AND 12
  AND (ss.rir IS NULL OR ss.rir <= 3)
ORDER BY s.id, ss.exercise_id, e1rm_kg DESC;

COMMENT ON VIEW v_exercise_e1rm IS
  'Best Epley e1RM per exercise per session, from working sets of 1-12 reps with RIR <= 3.';

-- One row per calendar day from the first recorded day to today.
CREATE VIEW v_daily AS
WITH bounds AS (
    SELECT min(d) AS first_day FROM (
        SELECT min(local_date) AS d FROM daily_activity
        UNION ALL SELECT min(local_date) FROM daily_vitals
        UNION ALL SELECT min(local_date) FROM sleep_sessions
        UNION ALL SELECT min(local_date) FROM nutrition_entries WHERE deleted_at IS NULL
        UNION ALL SELECT min(local_date) FROM body_metrics WHERE deleted_at IS NULL
        UNION ALL SELECT min(local_date) FROM checkins
        UNION ALL SELECT min(local_date) FROM strength_sessions
        UNION ALL SELECT min(local_date) FROM exercise_sessions WHERE deleted_at IS NULL
    ) x
), days AS (
    SELECT generate_series(first_day, (now() AT TIME ZONE 'Europe/Prague')::date,
                           INTERVAL '1 day')::date AS local_date
    FROM bounds
), sleep AS (
    SELECT DISTINCT ON (local_date) *
    FROM sleep_sessions
    WHERE is_main
    ORDER BY local_date, duration_min DESC
), strength AS (
    SELECT s.local_date,
           count(DISTINCT s.id) AS strength_sessions,
           count(ss.id) FILTER (WHERE NOT ss.is_warmup AND coalesce(ss.reps, 0) > 0
                                  AND (ss.rir IS NULL OR ss.rir <= 4)) AS hard_sets,
           round(sum(ss.reps * ss.weight_kg) FILTER (WHERE NOT ss.is_warmup)) AS tonnage_kg
    FROM strength_sessions s
    LEFT JOIN strength_sets ss ON ss.session_id = s.id
    GROUP BY s.local_date
), other AS (
    SELECT local_date,
           sum(duration_min) AS exercise_min,
           array_agg(DISTINCT activity_type ORDER BY activity_type) AS exercise_types
    FROM exercise_sessions
    WHERE deleted_at IS NULL
    GROUP BY local_date
)
SELECT d.local_date,
       a.steps, a.distance_km, a.active_minutes, a.active_zone_minutes, a.calories_out, a.floors,
       v.resting_hr, v.hrv_rmssd_ms, v.spo2_avg, v.breathing_rate, v.skin_temp_delta,
       sl.duration_min AS sleep_min, sl.efficiency AS sleep_efficiency,
       sl.sleep_score, sl.minutes_deep AS sleep_deep_min, sl.minutes_rem AS sleep_rem_min,
       sl.start_ts AS sleep_start_ts, sl.end_ts AS sleep_end_ts,
       n.kcal AS kcal_in, n.protein_g, n.carbs_g, n.fat_g, n.entries AS nutrition_entries,
       n.target_kcal, n.target_protein_g,
       b.weight_kg, b.body_fat_pct,
       c.energy, c.soreness, c.stress, c.motivation,
       coalesce(st.strength_sessions, 0) AS strength_sessions,
       coalesce(st.hard_sets, 0) AS hard_sets,
       st.tonnage_kg,
       coalesce(o.exercise_min, 0) AS exercise_min,
       o.exercise_types
FROM days d
LEFT JOIN daily_activity a ON a.local_date = d.local_date
LEFT JOIN daily_vitals v ON v.local_date = d.local_date
LEFT JOIN sleep sl ON sl.local_date = d.local_date
LEFT JOIN v_nutrition_daily n ON n.local_date = d.local_date
LEFT JOIN v_body_daily b ON b.local_date = d.local_date
LEFT JOIN checkins c ON c.local_date = d.local_date
LEFT JOIN strength st ON st.local_date = d.local_date
LEFT JOIN other o ON o.local_date = d.local_date;

COMMENT ON VIEW v_daily IS
  'One row per day: activity, vitals, main sleep, nutrition vs target, weight, check-in, training.';

-- Rolling 30-day baseline (previous 30 days, today excluded) and today's z-scores.
CREATE VIEW v_recovery_baseline AS
SELECT b.*,
       round((b.resting_hr - b.rhr_mean_30d) / nullif(b.rhr_sd_30d, 0), 2) AS rhr_z,
       round((b.hrv_rmssd_ms - b.hrv_mean_30d) / nullif(b.hrv_sd_30d, 0), 2) AS hrv_z,
       round((b.sleep_min - b.sleep_mean_30d) / nullif(b.sleep_sd_30d, 0), 2) AS sleep_z
FROM (
    SELECT local_date, resting_hr, hrv_rmssd_ms, sleep_min,
           round(avg(resting_hr) OVER w, 1) AS rhr_mean_30d,
           round(stddev_samp(resting_hr) OVER w, 2) AS rhr_sd_30d,
           count(resting_hr) OVER w AS rhr_n_30d,
           round(avg(hrv_rmssd_ms) OVER w, 1) AS hrv_mean_30d,
           round(stddev_samp(hrv_rmssd_ms) OVER w, 2) AS hrv_sd_30d,
           count(hrv_rmssd_ms) OVER w AS hrv_n_30d,
           round(avg(sleep_min) OVER w, 0) AS sleep_mean_30d,
           round(stddev_samp(sleep_min) OVER w, 1) AS sleep_sd_30d,
           count(sleep_min) OVER w AS sleep_n_30d
    FROM v_daily
    WINDOW w AS (ORDER BY local_date
                 RANGE BETWEEN INTERVAL '30 days' PRECEDING AND INTERVAL '1 day' PRECEDING)
) b;

COMMENT ON VIEW v_recovery_baseline IS
  'Resting HR, HRV and sleep vs the previous 30 days: means, SDs, sample counts and z-scores.';
