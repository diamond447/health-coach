-- Synthetic history of one person, for performance tests and demo screenshots.
--
--   psql "$DATABASE_URL" -v days=1095 -v hr_days=30 -f tests/fixtures/seed_history.sql
--
-- Run it on an empty database at alembic head; tests load it through tests/seed.py.
-- Defaults: three years of daily data and a week of intraday heart rate.
\if :{?days} \else \set days 1095 \endif
\if :{?hr_days} \else \set hr_days 7 \endif
SET TimeZone = 'Europe/Prague';
SELECT setseed(0.42);

INSERT INTO exercises (id, name, category, primary_muscles, secondary_muscles)
SELECT 'ex' || i, 'Exercise ' || i, 'strength',
       ARRAY[(ARRAY['chest','back','quads','hamstrings','shoulders','biceps','triceps','glutes'])[1 + i % 8]],
       ARRAY[(ARRAY['core','forearms','calves'])[1 + i % 3]]
FROM generate_series(1, 300) i;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO daily_activity (local_date, steps, distance_km, active_minutes, active_zone_minutes, calories_out, floors)
SELECT day, 4000 + (random()*12000)::int, round((random()*10)::numeric, 3), (random()*120)::int,
       (random()*90)::int, 2000 + (random()*1500)::int, (random()*20)::int FROM d;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO daily_vitals (local_date, resting_hr, hrv_rmssd_ms, spo2_avg, breathing_rate, skin_temp_delta, cardio_fitness)
SELECT day, 48 + (random()*12)::int, round((35 + random()*40)::numeric, 1), round((94 + random()*4)::numeric, 1),
       round((13 + random()*3)::numeric, 1), round((random()-0.5)::numeric, 2), round((45 + random()*5)::numeric, 1) FROM d;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO sleep_sessions (external_id, start_ts, end_ts, local_date, duration_min, time_in_bed_min, efficiency,
                            minutes_deep, minutes_light, minutes_rem, minutes_awake, sleep_score, is_main)
SELECT 'sl' || day, (day - 1) + time '22:30' + random() * interval '90 min', day + time '06:30' + random() * interval '60 min',
       day, 380 + (random()*120)::int, 480, 85 + (random()*10)::int, 60 + (random()*40)::int, 200, 90 + (random()*30)::int,
       30, 60 + (random()*35)::int, true FROM d
UNION ALL
SELECT 'nap' || day, day + time '14:00', day + time '14:30', day, 25, 30, 90, 0, 25, 0, 5, NULL, false
FROM d WHERE random() < 0.15;

INSERT INTO sleep_stages (session_id, start_ts, end_ts, stage)
SELECT s.id, s.start_ts + g * interval '15 min', s.start_ts + (g + 1) * interval '15 min',
       (ARRAY['light','deep','rem','awake'])[1 + g % 4]
FROM sleep_sessions s, generate_series(0, 31) g WHERE s.is_main;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO exercise_sessions (external_id, start_ts, end_ts, local_date, activity_type, duration_min, avg_hr, max_hr,
                               calories, hr_zone_minutes)
SELECT 'ex' || day, day + time '17:00', day + time '17:45', day,
       (ARRAY['run','bike','walk','swim'])[1 + (random()*3)::int], 30 + (random()*60)::int, 140, 175, 400,
       jsonb_build_object('fat_burn', 10, 'cardio', 15, 'peak', 5)
FROM d WHERE random() < 0.5;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO body_metrics (external_id, ts, local_date, weight_kg, body_fat_pct, source)
SELECT 'bm' || day, day + time '07:00', day, round((80 + random()*2 - (CURRENT_DATE - day) / 500.0)::numeric, 2),
       round((18 + random())::numeric, 1), 'google_health'
FROM d WHERE random() < 0.8;

INSERT INTO targets (effective_from, phase, kcal, protein_g, protein_max_g, carbs_g, fat_g, steps, weekly_rate_min_kg, weekly_rate_max_kg, reason)
SELECT CURRENT_DATE - :days + i * 90, 'cut', 2300, 160, 200, 230, 70, 9000, -0.5, -0.2, 'seed' FROM generate_series(0, :days / 90) i;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO nutrition_entries (external_id, ts, local_date, meal, description, grams, kcal, protein_g, carbs_g, fat_g, fiber_g, confidence, source)
SELECT 'ne' || day || '-' || g, day + time '07:00' + g * interval '100 min', day,
       (ARRAY['breakfast','lunch','dinner','snack'])[1 + g % 4]::meal, 'Food ' || (random()*200)::int, 150,
       250 + random()*150, 20, 30, 10, 3, 'estimated', 'chat'
FROM d, generate_series(0, 7) g WHERE random() < 0.9;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO checkins (local_date, energy, soreness, stress, motivation)
SELECT day, 1 + (random()*4)::int, 1 + (random()*4)::int, 1 + (random()*4)::int, 1 + (random()*4)::int FROM d WHERE random() < 0.6;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO strength_sessions (external_id, local_date, start_ts, end_ts, routine_name)
SELECT 'ss' || day, day, day + time '18:00', day + time '19:15', 'Routine' FROM d WHERE extract(isodow FROM day) IN (1, 3, 5);

INSERT INTO strength_sets (session_id, external_id, exercise_id, set_no, reps, weight_kg, rir, is_warmup)
SELECT s.id, 'set' || s.id || '-' || g, 'ex' || (1 + ((s.id * 7 + g / 4) % 40)), g % 4 + 1,
       5 + (random()*7)::int, round((40 + random()*80 + (s.id % 500) / 10.0)::numeric, 2),
       (random()*4)::int, g % 4 = 0
FROM strength_sessions s, generate_series(0, 23) g;

WITH d AS (SELECT generate_series(CURRENT_DATE - :days, CURRENT_DATE, '1 day')::date AS day)
INSERT INTO journal_entries (local_date, behavior, amount)
SELECT day, b, NULL FROM d, unnest(ARRAY['alcohol','caffeine_late','magnesium','screen_late','stretching']) b WHERE random() < 0.3;

-- Intraday heart rate: one sample a minute for the last :hr_days days.
INSERT INTO heart_rate_samples (ts, bpm)
SELECT ts, 55 + (random()*60)::int
FROM generate_series(now() - :hr_days * interval '1 day', now(), interval '1 min') ts;

ANALYZE;
