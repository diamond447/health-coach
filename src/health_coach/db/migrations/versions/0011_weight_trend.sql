-- Revision 0011: v_weight_trend in one linear pass.
--
-- The recursive CTE of revision 0001 rescanned the whole series on every step and the
-- weekly-rate lateral rescanned it once more per row, so the view grew quadratically
-- with the number of weigh-ins. The same numbers now come from a window aggregate.

-- State: {day number, trend}. The trend moves towards each weigh-in by
-- 1 - 0.9^(days since the previous weigh-in), exactly as the recursive version did.
CREATE FUNCTION weight_ema_step(state numeric[], day date, weight numeric)
RETURNS numeric[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN weight IS NULL THEN state
        WHEN state IS NULL THEN ARRAY[(day - DATE '2000-01-01')::numeric, weight]
        ELSE ARRAY[(day - DATE '2000-01-01')::numeric,
                   state[2] + (1 - power(0.9::numeric, (day - DATE '2000-01-01') - state[1]))
                              * (weight - state[2])]
    END
$$;

CREATE FUNCTION weight_ema_final(state numeric[])
RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT state[2] $$;

CREATE AGGREGATE weight_ema(date, numeric) (
    SFUNC = weight_ema_step,
    STYPE = numeric[],
    FINALFUNC = weight_ema_final
);

COMMENT ON AGGREGATE weight_ema(date, numeric) IS
  'Exponentially smoothed weight (alpha 0.1 per day, compounded over gaps); use as a window '
  'aggregate ordered by date.';

-- Same columns, types and values as revision 0001.
CREATE OR REPLACE VIEW v_weight_trend AS
WITH t AS (
    SELECT local_date, weight_kg,
           weight_ema(local_date, weight_kg) OVER (ORDER BY local_date) AS trend
    FROM v_body_daily
    WHERE weight_kg IS NOT NULL
), p AS (
    SELECT t.*,
           avg(weight_kg) OVER (ORDER BY local_date
               RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW) AS avg_7d,
           -- latest weigh-in 7 to 14 days earlier
           last_value(trend) OVER w AS prev_trend,
           last_value(local_date) OVER w AS prev_date
    FROM t
    WINDOW w AS (ORDER BY local_date
                 RANGE BETWEEN INTERVAL '14 days' PRECEDING AND INTERVAL '7 days' PRECEDING)
)
SELECT local_date,
       weight_kg,
       round(avg_7d, 2) AS avg_7d_kg,
       round(trend, 2) AS trend_kg,
       round((trend - prev_trend) * 7.0 / (local_date - prev_date), 2) AS weekly_rate_kg
FROM p;
