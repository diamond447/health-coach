# health-coach

Self-hosted health, nutrition and training data in one Postgres database, exposed to an
AI assistant (Claude, ChatGPT, Gemini) through remote Model Context Protocol (MCP)
servers, so the assistant can act as a data-driven personal coach: it reads your sleep,
heart rate, activity, nutrition, body weight and workouts, logs meals from chat, keeps a
coaching log, and plans your next training session in [openGym](https://github.com/DuarteSantos8/openGym).

It has two MCP servers:

- **health-coach** (`/mcp` on port 8080): single-user. All health data, analytics,
  read-only SQL, meal and body logging, targets, goals and a coach log.
- **fit** (`/mcp` on port 8081): multi-user. Each user links their own openGym account
  and lets their assistant read their training history and write planned sessions,
  routines and the weekly schedule. It never touches the health database.

> [!NOTE]
> A personal project shared as is. It is built for one owner (plus friends or family on
> the fit server) behind your own OIDC provider. It is not medical advice and not a
> medical device.

## How it works

```mermaid
flowchart LR
  wearable["Wearable / phone app"] --> gh["Google Health API"]
  gh -- every 30 min --> worker["worker<br/>ingest + scheduled jobs"]
  opengym["openGym<br/>self-hosted"] -- every 15 min --> worker
  worker --> pg[("Postgres<br/>typed tables + views")]
  pg --> grafana["Grafana<br/>(optional)"]
  mcp["mcp<br/>health-coach MCP"] <-- SQL --> pg
  fit["fit<br/>openGym MCP"] <-- per-user token --> opengym
  mcp --> ntfy["ntfy<br/>push to phone"]
  ai["Claude / ChatGPT / Gemini"] <-- HTTPS --> proxy["your reverse proxy"]
  proxy <--> mcp
  proxy <--> fit
  ai -. OAuth .-> idp["OIDC provider<br/>e.g. Authentik"]
```

- **Postgres** is the single source of truth. Raw API responses land in `raw_payloads`
  and are mapped into typed tables; views compute daily overviews, weight trend, recovery
  baselines, weekly training volume and estimated 1RM. See
  [docs/architecture.md](docs/architecture.md).
- **worker** syncs the Google Health API and openGym, refreshes the exercise catalogue,
  and sends data-quality and failure alerts through [ntfy](https://ntfy.sh).
- **mcp** and **fit** are OAuth 2.1 resource servers. They do not issue tokens; your
  OIDC provider does, and they verify the JWT access tokens (signature, `iss`, `aud`,
  `exp`, and for the health server an allowlist of subjects). See
  [ADR 0001](docs/adr/0001-authentik-as-authorization-server.md).

## Requirements

- Docker with the compose plugin, on a host with about 1.5 GB of free RAM.
- A public HTTPS hostname per MCP server (for example `coach.example.com` and
  `fit.example.com`) behind a reverse proxy or tunnel. Only `/mcp`, `/.well-known/` and
  `/healthz` need to be public.
- An OIDC provider that issues RS256-signed JWT access tokens and lets you register a
  confidential client with fixed redirect URIs. Tested with
  [Authentik](https://goauthentik.io); others (Keycloak, Zitadel, ...) should work when
  you set `HC_AUTH_JWKS_URL` / `FIT_AUTH_JWKS_URL` to their JWKS endpoint.
- Optional: a Google Cloud project for the Google Health API, a self-hosted openGym
  instance, ntfy, Grafana.

## Quick start

```sh
git clone https://github.com/diamond447/health-coach.git
cd health-coach
cp .env.example .env
```

Fill in `.env`:

```sh
openssl rand -hex 24   # once each for POSTGRES_PASSWORD, HC_COACH_RO_PASSWORD,
                       # HC_COACH_RW_PASSWORD, HC_INGEST_PASSWORD (and HC_GRAFANA_DB_PASSWORD)
docker run --rm python:3.12-slim sh -c \
  "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                       # once each for HC_TOKEN_KEY and FIT_TOKEN_KEY
```

Set `HC_TIMEZONE` (and `FIT_TIMEZONE`) to your IANA time zone, for example
`Europe/Berlin`; it decides which calendar day a record belongs to. Set it before the
first sync: changing it later does not re-date rows already stored.

The MCP servers refuse to start without their OAuth settings, so set them up now:

1. In your OIDC provider, create one confidential OAuth client per server (health coach:
   only you; fit: everyone who may use it). Redirect URIs for each assistant are listed
   in [docs/fit.md](docs/fit.md#authentik-configuration).
2. Set `HC_PUBLIC_URL`, `HC_AUTH_ISSUER`, `HC_AUTH_AUDIENCE` (the client ID) and
   `HC_AUTH_ALLOWED_SUBJECTS` (your own `sub`), and `FIT_PUBLIC_URL`,
   `FIT_AUTH_ISSUER` and `FIT_AUTH_AUDIENCE` (who may use fit is decided in the
   provider). Add the public host names to `HC_MCP_ALLOWED_HOSTS` and
   `FIT_MCP_ALLOWED_HOSTS`.

Then start the stack, using the published image instead of building locally (pin a
digest in production):

```sh
echo 'HC_IMAGE=ghcr.io/diamond447/health-coach:main' >> .env
docker compose up -d
curl http://127.0.0.1:8080/healthz   # {"status":"ok",...}
```

`migrate` applies the database migrations and role passwords, then `worker`, `mcp` and
`fit` start. Ports are published on loopback only; point your reverse proxy at them.

### Connect your data

1. **Google Health API**: create an OAuth client, authorize once, backfill history.
   See [docs/google-health.md](docs/google-health.md).
   ```sh
   docker compose run --rm worker auth google
   docker compose run --rm worker backfill google --from 2025-01-01
   ```
2. **openGym**: run openGym yourself (see its README), set `HC_OPENGYM_URL` and
   `FIT_OPENGYM_URL` to its address as seen from the containers, and pair the worker
   with your account (openGym: Settings -> "Pair the mobile app").
   See [docs/opengym.md](docs/opengym.md).
   ```sh
   docker compose run --rm worker auth opengym
   docker compose run --rm worker sync opengym --catalogue
   ```
3. **Notifications** (optional): set `HC_NTFY_TOPIC` to a long random topic name
   (and `HC_NTFY_URL` if you run your own ntfy server, plus `HC_NTFY_TOKEN` when it
   requires auth).

### Connect the assistant

1. Point your reverse proxy at `127.0.0.1:8080` (health coach) and `127.0.0.1:8081`
   (fit) for the public paths `/mcp`, `/.well-known/` and `/healthz`.
2. In Claude: Settings -> Connectors -> Add custom connector, URL
   `https://coach.example.com/mcp`, and under *Advanced settings* the client ID and
   secret. ChatGPT and Gemini: see [docs/fit.md](docs/fit.md).
3. Create a Claude project (for example "Coach") and paste
   [`coach_instructions.md`](src/health_coach/prompts/coach_instructions.md) into its
   instructions **after filling in the placeholders** (your height, starting weight,
   sports, current phase, calorie and protein targets, language).
4. Optional: a weekly scheduled task that runs the `weekly_review` prompt.
   See [docs/weekly-review.md](docs/weekly-review.md).

## Documentation

- [Architecture](docs/architecture.md): components, database, roles, security model, schedule.
- [Daily scores](docs/scores.md): WHOOP-style recovery, strain and sleep scoring.
- [Healthspan](docs/healthspan.md): estimated biological age, pace of aging, factor curves.
- [Healthstats web app](docs/web.md): read-only WHOOP-style stats PWA.
- [Habit journal & sleep settings](docs/journal.md): tracked behaviours, recovery insights, sleep settings.
- [Google Health API](docs/google-health.md): OAuth setup, backfill, mapping notes.
- [openGym](docs/opengym.md): data model, pairing, how planned sessions are written.
- [Fit MCP server](docs/fit.md): multi-user connector for Claude, ChatGPT and Gemini.
- [Weekly review and alerts](docs/weekly-review.md).
- [Backup and restore](docs/backup-restore.md).
- [Grafana dashboards](grafana/README.md).
- [ADR 0001](docs/adr/0001-authentik-as-authorization-server.md): an external OIDC
  provider as the authorization server.

## Configuration

All settings are environment variables, set in `.env` and passed per service by
`docker-compose.yml` (each service gets only what it needs). Health coach settings use
the `HC_` prefix, fit server settings the `FIT_` prefix; [.env.example](.env.example)
lists them with comments.

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | *(required)* | Postgres superuser `health`, used by migrations only. |
| `HC_COACH_RO_PASSWORD`, `HC_COACH_RW_PASSWORD`, `HC_INGEST_PASSWORD` | *(required)* | Logins of the service roles. |
| `HC_GRAFANA_DB_PASSWORD` | empty | Enables the read-only `grafana_ro` login. |
| `HC_IMAGE` | `health-coach:dev` | Image to run, e.g. `ghcr.io/diamond447/health-coach@sha256:...`. |
| `HC_TIMEZONE` | `UTC` | Time zone for `local_date` day boundaries and the database session. |
| `HC_LOG_LEVEL` | `INFO` | Log level. |
| `HC_TOKEN_KEY` | *(required for ingest)* | Fernet key encrypting the Google and openGym tokens at rest. |
| `HC_GOOGLE_CLIENT_ID`, `HC_GOOGLE_CLIENT_SECRET` | empty | Google OAuth client. |
| `HC_GOOGLE_REDIRECT_URI` | `http://localhost:8765/callback` | Must match the OAuth client. |
| `HC_OPENGYM_URL` | empty | openGym base URL as seen from the worker. |
| `HC_OPENGYM_VERSION` | `1.4.1` | openGym release whose exercise catalogue is loaded. |
| `HC_PUBLIC_URL` | empty | Public URL of the MCP endpoint, e.g. `https://coach.example.com/mcp`. |
| `HC_AUTH_ISSUER`, `HC_AUTH_AUDIENCE` | empty | Expected `iss` and `aud` of access tokens. |
| `HC_AUTH_JWKS_URL` | `<issuer>/jwks/` | JWKS URL. The default is Authentik's layout; set it for other providers or to fetch keys internally. |
| `HC_AUTH_ALLOWED_SUBJECTS` | `[]` | JSON list of token subjects allowed to use the health server. |
| `HC_AUTH_DISABLED` | `false` | Disables auth. Loopback development only. |
| `HC_MCP_ALLOWED_HOSTS` | loopback | Accepted `Host` headers (DNS rebinding protection). |
| `HC_MCP_PUBLISH`, `HC_DB_PUBLISH` | `127.0.0.1:8080`, `127.0.0.1:5432` | Published host ports. |
| `HC_NTFY_URL`, `HC_NTFY_TOPIC` | `https://ntfy.sh`, empty | Push notifications. |
| `HC_NTFY_TOKEN` | empty | ntfy access token, sent as `Authorization: Bearer`. |
| `HC_NOTIFY_LANG` | `en` | Language for push notifications (`en` or `cs`). |
| `HC_OFF_BASE_URL` | `https://world.openfoodfacts.org` | Open Food Facts for food search. |
| `HC_HR_MAX` | empty | Maximum heart rate. Fallback: Tanaka 208 - 0.7*age; if age unknown, 190. Overridden by `set_profile`. |
| `HC_BIRTH_YEAR` | empty | Birth year to estimate age (current year - birth_year). Overridden by `set_profile`. |
| `HC_SEX` | empty | Biological sex (`male` or `female`) for Banister coefficients. Overridden by `set_profile`. |
| `HC_SLEEP_NEED_BASE_MIN` | `480` | Baseline sleep need in minutes (default 8 hours). |
| `HC_WEB_HOST`, `HC_WEB_PORT` | `127.0.0.1`, `8090` | Web server bind host and port. |
| `HC_WEB_PUBLISH` | `127.0.0.1:8090` | Published host port for the web PWA service. |
| `HC_WEB_ALLOWED_USERS` | `[]` | JSON list of usernames allowed through forward-auth proxy (empty = no check, dev only). |
| `HC_WEB_USER_HEADER` | `X-authentik-username` | Header containing the authenticated username from the proxy. |
| `FIT_*` | | Same meaning for the fit server; see [docs/fit.md](docs/fit.md). |

## MCP tools

**health-coach**

| Area | Tools |
| --- | --- |
| Orientation | `get_context_snapshot`, `get_schema`, `get_data_coverage` |
| Overviews | `get_daily_overview`, `get_weekly_summary`, `get_weight_trend`, `get_scores` |
| Analytics | `estimate_tdee`, `get_nutrition_summary`, `get_recovery_status`, `get_sleep_analysis`, `get_training_load`, `get_exercise_progress`, `get_personal_records`, `compare_periods` |
| SQL | `query_sql`: one read-only `SELECT`, checked by sqlglot, run as `coach_ro` with a timeout and row cap |
| Logging | `search_food`, `save_food`, `log_meal`, `update_nutrition_entry`, `delete_nutrition_entry`, `log_body_metric`, `log_checkin`, `log_exercise_session` |
| Journal & settings | `log_journal`, `get_journal`, `delete_journal_entry`, `get_journal_insights`, `set_sleep_settings`, `get_sleep_settings`, `set_profile`, `get_profile` |
| Training (read) | `search_exercises`, `get_workout_log` |
| Coaching state | `get_targets`, `set_targets`, `read_coach_log`, `write_coach_log`, `manage_goal` |
| Notifications | `send_notification` |

Prompts: `coach_instructions`, `weekly_review`.

**fit**: `link_opengym`, `unlink_opengym`, `get_account`, `search_exercises`,
`get_training_history`, `get_routines`, `get_routine`, `get_planned`, `plan_session`,
`update_routine`, `schedule_week`, `delete_planned`, `log_session`.

## Development

Requires Docker and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
docker run -d --name hc-pg -e POSTGRES_PASSWORD=health -e POSTGRES_USER=health \
  -p 127.0.0.1:55433:5432 postgres:16-alpine
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests
HC_TEST_DATABASE_URL=postgresql+psycopg://health:health@127.0.0.1:55433/postgres uv run pytest
```

Database tests are skipped without `HC_TEST_DATABASE_URL`. To try the tools without an
identity provider, run `uv run health-coach mcp` outside Docker with
`HC_AUTH_DISABLED=true` and `HC_RO_DATABASE_URL` / `HC_RW_DATABASE_URL` pointing at a
migrated database; it binds to 127.0.0.1 only. The opt-in openGym live test
is described in `tests/test_opengym_live.py`.

CI runs the checks on every pull request and publishes `ghcr.io/diamond447/health-coach`
for pushes to `main` (tags `main`, `sha-<commit>`) and version tags `v*`.

## Security

This is personal health data on a public endpoint. Keep Postgres, the worker and Grafana
off the internet, expose only the MCP paths, keep `HC_AUTH_ALLOWED_SUBJECTS` to yourself,
and never commit `.env`. Please report vulnerabilities privately through GitHub security
advisories rather than public issues.

## License

[AGPL-3.0-or-later](LICENSE). openGym, which the fit server talks to, is AGPL-3.0 too.
