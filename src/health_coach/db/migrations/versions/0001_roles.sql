-- Database roles of revision 0001. Roles are created NOLOGIN; `health-coach db sync-roles`
-- gives them LOGIN and the passwords from the service URLs.
--
--   coach_ro    query_sql and read tools. No secrets, raw payloads or audit log.
--   coach_rw    logging and coaching-state tools; writes the audit log.
--   ingest      worker: wearable, wger and derived tables, sync state, OAuth tokens.
--   grafana_ro  dashboards: everything coach_ro sees plus audit log and sync state.

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['coach_ro', 'coach_rw', 'ingest', 'grafana_ro'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END
$$;

GRANT USAGE ON SCHEMA public TO coach_ro, coach_rw, ingest, grafana_ro;

-- Readable data: everything except oauth_tokens, raw_payloads and mcp_audit.
GRANT SELECT ON
    sync_state,
    daily_activity, daily_vitals, heart_rate_samples, sleep_sessions, sleep_stages,
    exercise_sessions, body_metrics, foods, nutrition_entries, checkins,
    exercises, strength_sessions, strength_sets,
    targets, goals, coach_log, tdee_estimates,
    v_body_daily, v_weight_trend, v_nutrition_daily, v_strength_volume_weekly,
    v_exercise_e1rm, v_daily, v_recovery_baseline
TO coach_ro, coach_rw, ingest, grafana_ro;

GRANT SELECT ON mcp_audit TO grafana_ro;

-- Tool writes.
GRANT INSERT, UPDATE, DELETE ON
    foods, nutrition_entries, body_metrics, checkins, exercise_sessions,
    targets, goals, coach_log
TO coach_rw;
GRANT INSERT ON mcp_audit TO coach_rw;

-- Worker writes. DELETE on mcp_audit is for the 180-day retention job.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    raw_payloads, sync_state, oauth_tokens,
    daily_activity, daily_vitals, heart_rate_samples, sleep_sessions, sleep_stages,
    exercise_sessions, body_metrics, foods, nutrition_entries,
    exercises, strength_sessions, strength_sets, tdee_estimates
TO ingest;
GRANT SELECT, DELETE ON mcp_audit TO ingest;

-- Identity columns need their sequences.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO coach_rw, ingest;

-- Guard rails that hold even if the SQL guard in the MCP server is bypassed.
ALTER ROLE coach_ro SET default_transaction_read_only = on;
ALTER ROLE coach_ro SET statement_timeout = '5s';
ALTER ROLE coach_ro SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE grafana_ro SET default_transaction_read_only = on;
ALTER ROLE grafana_ro SET statement_timeout = '15s';
ALTER ROLE coach_rw SET statement_timeout = '10s';
