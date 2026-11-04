-- Revision 0012: tighter limits for the roles that run ad-hoc or dashboard queries.
--
-- Postgres cannot cap the memory of one backend, so the container's memory limit is the
-- last line of defence. These settings keep one heavy query from using several times
-- work_mem (parallel workers each get their own), from holding many connections, or from
-- sitting idle inside a transaction.

-- query_sql and the read tools: one user, short queries.
ALTER ROLE coach_ro SET max_parallel_workers_per_gather = 0;
ALTER ROLE coach_ro SET lock_timeout = '2s';
ALTER ROLE coach_ro CONNECTION LIMIT 20;

-- Dashboards: longer queries are fine, idle transactions and parallel plans are not.
ALTER ROLE grafana_ro SET max_parallel_workers_per_gather = 0;
ALTER ROLE grafana_ro SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE grafana_ro CONNECTION LIMIT 10;

-- Logging tools write a row or two per call.
ALTER ROLE coach_rw SET idle_in_transaction_session_timeout = '30s';
