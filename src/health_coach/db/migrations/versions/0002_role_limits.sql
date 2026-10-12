-- Revision 0002: resource limits for the query roles and no temp tables for anyone
-- (security review 2026-10-11).

ALTER ROLE coach_ro SET work_mem = '32MB';
ALTER ROLE coach_ro SET temp_file_limit = '256MB';
ALTER ROLE grafana_ro SET work_mem = '32MB';
ALTER ROLE grafana_ro SET temp_file_limit = '512MB';

DO $$
BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END
$$;

-- coach_rw only needs the sequences of the tables it inserts into.
REVOKE USAGE ON ALL SEQUENCES IN SCHEMA public FROM coach_rw;
GRANT USAGE ON SEQUENCE
    foods_id_seq, nutrition_entries_id_seq, body_metrics_id_seq, exercise_sessions_id_seq,
    targets_id_seq, goals_id_seq, coach_log_id_seq, mcp_audit_id_seq
TO coach_rw;
