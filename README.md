<div align="center">

# health-coach

**Your wearable data, your database, your AI coach.**

[![CI](https://github.com/diamond447/health-coach/actions/workflows/ci.yml/badge.svg)](https://github.com/diamond447/health-coach/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![TypeScript](https://img.shields.io/badge/TypeScript-Preact-3178C6?logo=typescript&logoColor=white)](web)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](docs/architecture.md)
[![MCP](https://img.shields.io/badge/MCP-remote_server-black)](docs/mcp-tools.md)
[![Image](https://img.shields.io/badge/ghcr.io-health--coach-2496ED?logo=docker&logoColor=white)](https://github.com/diamond447/health-coach/pkgs/container/health-coach)

<img src="docs/assets/hero.webp" alt="Healthstats app: sleep, recovery, today, strain and trends screens" width="100%">

</div>

Sleep, heart rate, workouts and meals from a wearable and [openGym](https://github.com/DuarteSantos8/openGym)
land in one Postgres database. A WHOOP-style app turns them into daily recovery, strain
and sleep scores, and remote MCP servers let Claude, ChatGPT or Gemini read the data
and coach you from it.

## Features

- **Daily scores**: recovery from HRV, resting HR, sleep and vitals against your own
  baseline; cardio strain (TRIMP) and muscular load from lifting; sleep need and debt.
  [How they work](docs/scores.md)
- **Stats app**: installable PWA with scrubbable charts, a calendar, weekly and monthly
  reports, a habit journal and its effect on recovery. Hand-written SVG charts, no chart library.
- **AI coach over MCP**: 40+ tools for analytics, read-only SQL, meal logging, goals and
  a coach log, plus a weekly review prompt. [Tool list](docs/mcp-tools.md)
- **Training planner**: a multi-user MCP server that plans sessions and weekly
  schedules straight into openGym. [Fit server](docs/fit.md)
- **Healthspan**: estimated biological age and pace of aging from sleep, activity and
  resting HR. [Method](docs/healthspan.md)
- **Self-hosted**: Docker Compose, OAuth 2.1 through your own OIDC provider,
  least-privilege database roles. Your history lives in your own Postgres.

## Screenshots

<table>
  <tr>
    <td><img src="docs/assets/screens/today.webp" alt="Today"></td>
    <td><img src="docs/assets/screens/recovery.webp" alt="Recovery"></td>
    <td><img src="docs/assets/screens/sleep.webp" alt="Sleep"></td>
    <td><img src="docs/assets/screens/strain.webp" alt="Strain"></td>
  </tr>
  <tr>
    <td align="center">Today</td><td align="center">Recovery</td>
    <td align="center">Sleep</td><td align="center">Strain</td>
  </tr>
  <tr>
    <td><img src="docs/assets/screens/nutrition.webp" alt="Nutrition"></td>
    <td><img src="docs/assets/screens/calendar.webp" alt="Calendar"></td>
    <td><img src="docs/assets/screens/journal.webp" alt="Journal insights"></td>
    <td><img src="docs/assets/screens/healthspan.webp" alt="Healthspan"></td>
  </tr>
  <tr>
    <td align="center">Nutrition</td><td align="center">Calendar</td>
    <td align="center">Journal insights</td><td align="center">Healthspan</td>
  </tr>
</table>

<sub>Synthetic demo data. The app UI is in Czech.</sub>

## How it works

```mermaid
flowchart LR
  wearable["Wearable"] --> gh["Google Health API"]
  gh --> worker["worker<br/>ingest + scores"]
  opengym["openGym"] --> worker
  worker --> pg[("Postgres")]
  pg --> web["Stats PWA"]
  pg <--> mcp["health-coach MCP"]
  fit["fit MCP"] <--> opengym
  ai["Claude / ChatGPT / Gemini"] <-- OAuth 2.1 --> mcp
  ai <--> fit
  worker --> ntfy["ntfy push"]
```

| Service | What it does |
| --- | --- |
| `worker` | Syncs Google Health and openGym, computes scores and healthspan, sends pushes. |
| `mcp` | Single-user MCP server over the health database. |
| `fit` | Multi-user MCP server for openGym; never touches health data. |
| `web` | The stats PWA, read-only apart from journal entries. |

More in [docs/architecture.md](docs/architecture.md).

## Quick start

```sh
git clone https://github.com/diamond447/health-coach.git && cd health-coach
cp .env.example .env    # passwords, keys, OIDC settings, time zone
echo 'HC_IMAGE=ghcr.io/diamond447/health-coach:main' >> .env
docker compose up -d
```

Then connect your data sources and add the MCP server as a custom connector in your
assistant. The full walkthrough is in [docs/setup.md](docs/setup.md), every setting in
[docs/configuration.md](docs/configuration.md).

## Documentation

| | |
| --- | --- |
| [Setup](docs/setup.md) | From an empty host to a working coach |
| [Architecture](docs/architecture.md) | Components, database, roles, security model |
| [Daily scores](docs/scores.md) | Recovery, strain and sleep math |
| [Stats app](docs/web.md) | Screens, API, forward auth, iPhone install |
| [Journal](docs/journal.md) | Tracked habits and their effect on recovery |
| [Healthspan](docs/healthspan.md) | Biological age and pace of aging |
| [Data sources](docs/google-health.md) | Google Health API, [openGym](docs/opengym.md), [nutrition](docs/nutrition.md) |
| [Fit server](docs/fit.md) | Multi-user training connector |
| [Operations](docs/backup-restore.md) | Backups, [weekly review](docs/weekly-review.md), [Grafana](grafana/README.md) |

## Development

```sh
uv sync
docker run -d --name hc-pg -e POSTGRES_PASSWORD=health -e POSTGRES_USER=health \
  -p 127.0.0.1:55433:5432 postgres:16-alpine
uv run ruff check . && uv run mypy src tests
HC_TEST_DATABASE_URL=postgresql+psycopg://health:health@127.0.0.1:55433/postgres uv run pytest
cd web && npm ci && npm test
```

Database tests are skipped without `HC_TEST_DATABASE_URL`. CI runs all checks on every
pull request and publishes `ghcr.io/diamond447/health-coach` from `main` and `v*` tags.

## Security

This is personal health data. Keep Postgres, the worker and Grafana off the internet,
expose only the MCP and app paths, and report vulnerabilities privately through
[GitHub security advisories](https://github.com/diamond447/health-coach/security/advisories/new).

> [!NOTE]
> A personal project shared as is. Not medical advice and not a medical device.

## License

[AGPL-3.0-or-later](LICENSE). openGym, which the fit server talks to, is AGPL-3.0 too.
