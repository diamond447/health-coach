import pytest

from health_coach.mcp_server.sql_guard import SqlRejected, check_sql

ALLOWED = [
    "SELECT * FROM v_daily WHERE local_date >= current_date - 7",
    "with w as (select * from v_weight_trend) select avg(trend_kg) from w",
    "SELECT a.local_date FROM daily_activity a UNION SELECT local_date FROM checkins",
    "SELECT date_trunc('week', local_date), sum(kcal) FROM nutrition_entries GROUP BY 1",
    "SELECT pg_typeof(1)",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY steps) FROM daily_activity",
]

REJECTED = [
    ("SELECT 1; SELECT 2", "exactly one"),
    ("DELETE FROM coach_log", "only SELECT"),
    ("UPDATE targets SET kcal = 1", "only SELECT"),
    ("WITH d AS (DELETE FROM coach_log RETURNING *) SELECT * FROM d", "DELETE"),
    ("WITH i AS (INSERT INTO goals (name) VALUES ('x') RETURNING *) SELECT 1", "INSERT"),
    ("SELECT * INTO new_table FROM v_daily", "INTO"),
    ("SELECT * FROM targets FOR UPDATE", "LOCK"),
    ("SELECT pg_sleep(10)", "pg_sleep"),
    ("SELECT \"PG_READ_FILE\"('/etc/passwd')", "pg_read_file"),
    ("SELECT set_config('role', 'health', true)", "set_config"),
    ("SELECT current_setting('is_superuser')", "current_setting"),
    ("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", "dblink"),
    ("SELECT lo_import('/etc/passwd')", "lo_import"),
    ("SELECT query_to_xml('select * from oauth_tokens', true, true, '')", "query_to_xml"),
    ("SELECT * FROM oauth_tokens", "oauth_tokens"),
    ("SELECT * FROM public.mcp_audit", "mcp_audit"),
    ("SELECT * FROM pg_catalog.pg_authid", "pg_catalog"),
    ("SELECT * FROM pg_settings", "pg_settings"),
    ("SELECT * FROM information_schema.tables", "information_schema"),
    ("COPY coach_log TO STDOUT", "only SELECT"),
    ("SET ROLE health", "only SELECT"),
    ("SELECT FROM WHERE", "parse"),
    ("SELECT * FROM ts_stat('select to_tsvector(relname) from pg_class')", "ts_stat"),
    ("SELECT query_to_xmlschema('select 1', true, true, '')", "query_to_xmlschema"),
    ("SELECT table_to_xml_and_xmlschema('coach_log', true, true, '')", "xml"),
    ("SELECT repeat('x', 900000000)", "repeat"),
    ("SELECT lpad('x', 900000000)", "pad"),
    ("SELECT currval('coach_log_id_seq')", "currval"),
    ("SELECT " + "1," * 6000 + "1", "longer"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql: str) -> None:
    assert check_sql(sql)


@pytest.mark.parametrize(("sql", "reason"), REJECTED)
def test_rejected(sql: str, reason: str) -> None:
    with pytest.raises(SqlRejected, match=reason):
        check_sql(sql)
