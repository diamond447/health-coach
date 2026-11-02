# Configuration

All settings are environment variables, set in `.env` and passed per service by
`docker-compose.yml` (each service gets only what it needs). Health coach settings use
the `HC_` prefix, fit server settings the `FIT_` prefix; [.env.example](../.env.example)
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
| `HC_WEB_JOURNAL_DATABASE_URL` | empty | Optional connection URL for `Role.web_journal`; enables journal logging from the web app. |
| `FIT_*` | | Same meaning for the fit server; see [fit.md](fit.md). |
