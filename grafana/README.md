# Grafana Dashboards

Provisioned dashboards for `health-coach`.

## Dashboards

| File | UID | Name | Description |
| --- | --- | --- | --- |
| `body.json` | `hc-body` | Body | Daily weight points, 7-day average and trend (`v_weight_trend`), weekly rate with target band (`targets`), intake vs targets (`v_nutrition_daily`), TDEE history coloured by confidence (`tdee_estimates`), and 7-day stat panels. |
| `recovery.json` | `hc-recovery` | Recovery | Sleep duration and stages stacked (deep, REM, light, awake for main sessions), resting HR and HRV with 30-day baseline bands (mean ± 1 SD), sleep start time consistency, and 1–5 check-in scores. |
| `training.json` | `hc-training` | Training | Weekly hard sets per muscle group (`v_strength_volume_weekly`) with target reference band (10–20), e1RM progression over time with an exercise selector variable, weekly tonnage, and other sports minutes by activity type. |
| `system.json` | `hc-system` | System | Sync state freshness and error counts (`sync_state`) with age thresholds, MCP tool calls per tool per day, p95 execution duration per tool, and recent MCP errors. |

All dashboards use stable UIDs, default to the last 90 days in the browser's time zone, and include the tag `health-coach`.

## Datasource Configuration

All panels query PostgreSQL through a dashboard template variable `${ds}` of type `grafana-postgresql-datasource`.

Configure the datasource in Grafana:

| Setting | Value |
| --- | --- |
| Type | PostgreSQL (`grafana-postgresql-datasource`) |
| Host | the Docker host and `HC_DB_PUBLISH` port, e.g. `192.0.2.10:5432` (or `db:5432` if Grafana joins the compose network) |
| Database | `health` |
| User | `grafana_ro` |
| Password | Value of `HC_GRAFANA_DB_PASSWORD` from `.env` |
| TLS / SSL Mode | `disable` on a trusted network; Postgres in the compose file has no TLS |
| Version | `16` |

The `grafana_ro` role is read-only (`default_transaction_read_only = on`, 15 s statement timeout) with `SELECT` access to all views and typed tables, plus `sync_state` and `mcp_audit`. It cannot access credentials in `oauth_tokens` or raw dumps in `raw_payloads`.

## Provisioning

Copy the JSON files into Grafana's provisioned dashboards folder:
```sh
cp grafana/*.json /var/lib/grafana/dashboards/
```
Or mount them in `docker-compose.yml`:
```yaml
volumes:
  - ./grafana:/var/lib/grafana/dashboards:ro
```
With dashboard provider configuration in `/etc/grafana/provisioning/dashboards/health-coach.yaml`:
```yaml
apiVersion: 1
providers:
  - name: 'Health Coach'
    orgId: 1
    folder: 'Health'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

Publishing Postgres beyond loopback (`HC_DB_PUBLISH=0.0.0.0:5432`) exposes it to your
network: allow only the Grafana host in your firewall, and never publish it to the
internet.
