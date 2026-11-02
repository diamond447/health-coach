# Security policy

health-coach stores personal health data, so security reports are welcome and taken
seriously.

## Reporting a vulnerability

Please report privately through
[GitHub private vulnerability reporting](https://github.com/diamond447/health-coach/security/advisories/new).
Do not open a public issue for a vulnerability, and do not include real health data
in a report.

You can expect an answer within a week. Fixes land on `main` and in the
`ghcr.io/diamond447/health-coach:main` image.

## Supported versions

Only the latest `main` (and the image built from it) receives fixes.

## Deployment notes

The security model (database roles, OAuth for the MCP servers, forward auth for the
stats app) is described in [docs/architecture.md](docs/architecture.md) and
[docs/web.md](docs/web.md). In short: keep Postgres, the worker and Grafana off the
internet, publish only the MCP and app paths through a TLS reverse proxy, and never
expose the stats app port directly, because it trusts the user header set by the proxy.
