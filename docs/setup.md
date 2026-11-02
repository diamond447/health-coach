# Setup

The full path from an empty host to an assistant that coaches you from your own data.

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

## Install

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
   in [fit.md](fit.md#authentik-configuration).
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

## Connect your data

1. **Google Health API**: create an OAuth client, authorize once, backfill history.
   See [google-health.md](google-health.md).
   ```sh
   docker compose run --rm worker auth google
   docker compose run --rm worker backfill google --from 2025-01-01
   ```
2. **openGym**: run openGym yourself (see its README), set `HC_OPENGYM_URL` and
   `FIT_OPENGYM_URL` to its address as seen from the containers, and pair the worker
   with your account (openGym: Settings -> "Pair the mobile app").
   See [opengym.md](opengym.md).
   ```sh
   docker compose run --rm worker auth opengym
   docker compose run --rm worker sync opengym --catalogue
   ```
3. **Notifications** (optional): set `HC_NTFY_TOPIC` to a long random topic name
   (and `HC_NTFY_URL` if you run your own ntfy server, plus `HC_NTFY_TOKEN` when it
   requires auth).

## Connect the assistant

1. Point your reverse proxy at `127.0.0.1:8080` (health coach) and `127.0.0.1:8081`
   (fit) for the public paths `/mcp`, `/.well-known/` and `/healthz`.
2. In Claude: Settings -> Connectors -> Add custom connector, URL
   `https://coach.example.com/mcp`, and under *Advanced settings* the client ID and
   secret. ChatGPT and Gemini: see [fit.md](fit.md).
3. Create a Claude project (for example "Coach") and paste
   [`coach_instructions.md`](../src/health_coach/prompts/coach_instructions.md) into its
   instructions **after filling in the placeholders** (your height, starting weight,
   sports, current phase, calorie and protein targets, language).
4. Optional: a weekly scheduled task that runs the `weekly_review` prompt.
   See [weekly-review.md](weekly-review.md).

## Stats app

The `web` service serves the stats PWA on `127.0.0.1:8090`. Put it behind a
forward-auth proxy and set `HC_WEB_ALLOWED_USERS`; see [web.md](web.md).

All settings: [configuration.md](configuration.md).
