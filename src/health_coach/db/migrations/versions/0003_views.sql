-- Views updated for openGym: joined on exercises.id = strength_sets.exercise_id (Text)
-- Recreates v_strength_volume_weekly and v_exercise_e1rm with identical output columns.

CREATE VIEW v_strength_volume_weekly AS
WITH hard AS (
    SELECT s.local_date, x.primary_muscles, x.secondary_muscles
    FROM strength_sets ss
    JOIN strength_sessions s ON s.id = ss.session_id
    JOIN exercises x ON x.id = ss.exercise_id
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
JOIN exercises x ON x.id = ss.exercise_id
WHERE NOT ss.is_warmup
  AND ss.weight_kg > 0
  AND ss.reps BETWEEN 1 AND 12
  AND (ss.rir IS NULL OR ss.rir <= 3)
ORDER BY s.id, ss.exercise_id, e1rm_kg DESC;

COMMENT ON VIEW v_exercise_e1rm IS
  'Best Epley e1RM per exercise per session, from working sets of 1-12 reps with RIR <= 3.';

GRANT SELECT ON v_strength_volume_weekly, v_exercise_e1rm TO coach_ro, coach_rw, ingest, grafana_ro;
