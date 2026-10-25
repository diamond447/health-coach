# Architecture

## Components

| Service | Command | Role |
| --- | --- | --- |
| `db` | `postgres:16-alpine` | All health and coaching data. |
| `migrate` | `health-coach db upgrade && health-coach db sync-roles` | One-shot: Alembic migrations, then service role logins from `.env`. |
| `worker` | `health-coach worker` | APScheduler daemon: ingest, derived metrics, alerts. Connects as `ingest`. |
| `mcp` | `health-coach mcp` | health-coach MCP server (Streamable HTTP, `/mcp`). Connects as `coach_ro` and `coach_rw`. |
| `fit` | `health-coach fit-mcp` | Multi-user openGym MCP server ([fit.md](fit.md)). Own SQLite file, no access to Postgres. |
| `web` | `health-coach web` | Read-only WHOOP-style stats PWA ([web.md](web.md)). Connects as `coach_ro`. |

All services run from one image. Each service gets only the environment variables it
needs: the internet-facing `mcp` never sees the Postgres superuser password or the token
key, and `fit` never sees anything of the health database.

Read path: the worker pulls the Google Health API and openGym into Postgres; the
assistant reads it through the MCP tools. Write path: the assistant logs meals, body
metrics, check-ins, targets, goals and coach log entries through `coach_rw`; training
plans go to openGym through the fit server, and the worker mirrors them back.

## Database

Raw API responses are stored untouched in `raw_payloads` and mapped into typed tables, so
a fixed mapper can re-parse history (`health-coach remap google`) without fetching again.

Conventions:

- Timestamps are `timestamptz` in UTC. Daily records also carry `local_date` in
  `HC_TIMEZONE` (sleep belongs to the day you wake up).
- Every table has `created_at` and `updated_at`; data tables also have `source`.
- Rows that tools may delete are soft-deleted through `deleted_at`.

| Group | Tables |
| --- | --- |
| Raw and sync state | `raw_payloads`, `sync_state`, `oauth_tokens` (Fernet-encrypted), `notifications_sent` |
| Wearable | `daily_activity`, `daily_vitals`, `heart_rate_samples`, `sleep_sessions`, `sleep_stages`, `exercise_sessions` |
| Body and nutrition | `body_metrics`, `foods`, `nutrition_entries`, `checkins` |
| Strength (mirror of openGym) | `exercises`, `strength_sessions`, `strength_sets` |
| Coaching state | `targets`, `goals`, `coach_log`, `tdee_estimates`, `daily_scores`, `journal_entries`, `app_settings` |
| Audit | `mcp_audit` (tool, subject, duration, error; kept 180 days) |

Views: `v_daily` (one row per day across all domains), `v_body_daily`, `v_weight_trend`
(7-day average and weekly rate), `v_nutrition_daily`, `v_recovery_baseline` (30-day
baselines for resting HR and HRV), `v_strength_volume_weekly` (hard sets per muscle),
`v_exercise_e1rm`.

## Database roles

Created by the migrations as `NOLOGIN`; `health-coach db sync-roles` gives them logins and
the passwords from `.env`.

| Role | Used by | Access |
| --- | --- | --- |
| `coach_ro` | `query_sql` and read tools | `SELECT` on typed tables and views; no `oauth_tokens`, `raw_payloads`, `mcp_audit` or `notifications_sent`. Read-only transactions, statement timeout. |
| `coach_rw` | logging and coaching tools | Writes nutrition, body metrics, check-ins, foods, targets, goals, coach log, journal entries, app settings; appends to `mcp_audit`. |
| `ingest` | worker | Wearable, strength and derived tables, sync state, OAuth tokens, raw payloads, notifications sent. |
| `grafana_ro` | Grafana | What `coach_ro` sees plus `sync_state`, `mcp_audit` and `notifications_sent`. Disabled unless `HC_GRAFANA_DB_PASSWORD` is set. |

## Security model

Personal health data sits behind a public endpoint, so every layer assumes the one in
front of it can fail.

- **Network**: only the MCP paths (`/mcp`, `/.well-known/`, `/healthz`) are public.
  Postgres, the worker and Grafana stay on your private network; compose publishes ports
  on loopback by default.
- **Authentication**: the MCP servers are OAuth resource servers. They validate JWT
  access tokens from your OIDC provider (signature, `iss`, `aud`, `exp`); the health
  server also requires `sub` in `HC_AUTH_ALLOWED_SUBJECTS`. See
  [ADR 0001](adr/0001-authentik-as-authorization-server.md).
- **Least privilege**: tools connect with the roles above, never as the superuser.
- **SQL guard**: `query_sql` parses the query with sqlglot, allows one `SELECT`/`WITH`
  statement, rejects dangerous functions (`pg_read_file`, `dblink`, `pg_sleep`, ...),
  and runs it read-only as `coach_ro` with a 5 s timeout and a row cap.
- **Destructive tools** are soft deletes and carry `destructiveHint`, so clients ask
  before running them.
- **Secrets**: `.env` is never committed; OAuth and openGym tokens are encrypted at rest
  with `HC_TOKEN_KEY` / `FIT_TOKEN_KEY`, and are never logged.
- **Prompt injection**: free text (food names from Open Food Facts, notes, log entries)
  is returned as data, and the tool descriptions and coach instructions tell the
  assistant never to follow instructions found in it.
- **Fit isolation**: each fit user is keyed by the token's `sub` and can only reach the
  openGym account they paired; the fit server has no route to the health data.

## Schedule (worker, in `HC_TIMEZONE`)

| Job | When | What |
| --- | --- | --- |
| `google_recent` | every 30 min | Google Health: yesterday and today |
| `google_week` | daily 04:00 | Google Health: last 7 days (late syncs, edits, deletions) |
| `google_month` | Sunday 05:00 | Google Health: last 30 days of sleep |
| `opengym_workouts` | every 15 min | openGym workouts and body weight |
| `opengym_catalogue` | daily 03:30 | openGym exercise catalogue and custom exercises |
| `derived_snapshot` | daily 04:30 | TDEE estimate snapshot, `mcp_audit` cleanup |
| `scores_recent` | every 30 min | Daily scores (recovery, strain, sleep): yesterday and today (offset 10 min after google_recent) |
| `scores_week` | daily 04:45 | Daily scores (recovery, strain, sleep): last 7 days |
| `healthspan_recent` | daily 05:00 | Estimated biological age (healthspan) and pace: current and previous week |
| `data_quality` | daily 09:00 | ntfy alert for stale syncs and logging gaps |
| `morning_recovery` | every 10 min 05:00–11:50 | ntfy push with recovery %, zone, strain target, and sleep duration |
| `bedtime_reminder` | every 5 min | ntfy push reminder starting 30 min before planned bedtime |

Google and openGym jobs run only when they are configured. See
[scores.md](scores.md) for score algorithms and formulas, and
[weekly-review.md](weekly-review.md) for alerts and the weekly review.
