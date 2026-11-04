-- Revision 0013: date-range reads of the daily views without aggregating all history.

-- One pass over body_metrics instead of three correlated subqueries per day. Same columns
-- and types; ties on ts (never seen in practice) now resolve by id instead of arbitrarily.
CREATE OR REPLACE VIEW v_body_daily AS
SELECT local_date,
       ((array_agg(weight_kg ORDER BY ts, id)
           FILTER (WHERE weight_kg IS NOT NULL))[1])::numeric(5,2) AS weight_kg,
       ((array_agg(body_fat_pct ORDER BY ts, id)
           FILTER (WHERE body_fat_pct IS NOT NULL))[1])::numeric(4,1) AS body_fat_pct,
       ((array_agg(waist_cm ORDER BY ts, id)
           FILTER (WHERE waist_cm IS NOT NULL))[1])::numeric(5,1) AS waist_cm
FROM body_metrics
WHERE deleted_at IS NULL
GROUP BY local_date;

-- v_daily for [p_start, p_end]. A WHERE on v_daily does not reach the aggregates behind
-- its LEFT JOINs, so every read summed the whole history; here each part is filtered
-- first. The body is v_daily's (revision 0004) with those filters added: keep the two in
-- step. tests/test_daily_range.py compares them on a seeded history.
CREATE FUNCTION daily_range(p_start date, p_end date)
RETURNS SETOF v_daily
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
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
    SELECT generate_series(greatest(first_day, p_start), least(CURRENT_DATE, p_end),
                           INTERVAL '1 day')::date AS local_date
    FROM bounds
    WHERE first_day IS NOT NULL
), sleep AS (
    SELECT DISTINCT ON (local_date) *
    FROM sleep_sessions
    WHERE is_main AND local_date BETWEEN p_start AND p_end
    ORDER BY local_date, duration_min DESC
), strength AS (
    SELECT s.local_date,
           count(DISTINCT s.id) AS strength_sessions,
           count(ss.id) FILTER (WHERE NOT ss.is_warmup AND coalesce(ss.reps, 0) > 0
                                  AND (ss.rir IS NULL OR ss.rir <= 4)) AS hard_sets,
           round(sum(ss.reps * ss.weight_kg) FILTER (WHERE NOT ss.is_warmup)) AS tonnage_kg
    FROM strength_sessions s
    LEFT JOIN strength_sets ss ON ss.session_id = s.id
    WHERE s.local_date BETWEEN p_start AND p_end
    GROUP BY s.local_date
), other AS (
    SELECT local_date,
           sum(duration_min) AS exercise_min,
           array_agg(DISTINCT activity_type ORDER BY activity_type) AS exercise_types
    FROM exercise_sessions
    WHERE deleted_at IS NULL AND local_date BETWEEN p_start AND p_end
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
LEFT JOIN (SELECT * FROM v_nutrition_daily WHERE local_date BETWEEN p_start AND p_end) n
       ON n.local_date = d.local_date
LEFT JOIN (SELECT * FROM v_body_daily WHERE local_date BETWEEN p_start AND p_end) b
       ON b.local_date = d.local_date
LEFT JOIN checkins c ON c.local_date = d.local_date
LEFT JOIN strength st ON st.local_date = d.local_date
LEFT JOIN other o ON o.local_date = d.local_date
$$;

COMMENT ON FUNCTION daily_range(date, date) IS
  'Rows of v_daily from p_start to p_end (inclusive), computed for that range only.';
