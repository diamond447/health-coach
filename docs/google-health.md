# Google Health ingest

Request shapes, data type names, scopes and the mappers follow the official discovery
document (revision 20261007, `https://health.googleapis.com/$discovery/rest?version=v4`),
are tested against fixtures built from its schemas, and were checked against real
payloads from one Fitbit device. Other devices may report fields differently: raw
responses are kept in `raw_payloads`, so after fixing a mapper you can re-run
`health-coach remap google` without fetching again. The API has no sleep score; sleep
comes as durations and stages.

How the client talks to the API:

- `list` filters use civil time with the data type prefix: `{type}.date` for daily
  summaries, `{type}.sample_time.civil_time` for samples (weight, body fat, heart rate),
  `{type}.interval.civil_start_time` for sessions and nutrition, and
  `sleep.interval.civil_end_time` for sleep (a night belongs to the day you wake up).
- `pageSize` is at most 25 for `sleep` and `exercise`, 10000 otherwise.
- `dailyRollUp` takes a `CivilTimeInterval` (`{"start": {"date": ...}, "end": ...}`),
  at most 14 days for `active-minutes` and `total-calories`, 90 days otherwise.
- Rows are dated by the civil date the API reports (the user's own time zone at that
  moment), so a re-sync of a window never drops rows recorded abroad. Each window
  re-sync soft-deletes (or, for sleep, deletes) rows of that window that Google no longer
  returns; heart-rate samples are never deleted.
- Nutrition logs come from the Google Health app (if you log food there) under
  `googlehealth.nutrition.readonly`; entries logged through the MCP server are separate
  rows with their own source, and the views add both up per day.

## Setup

1. Google Cloud console: enable the Google Health API, configure the OAuth consent
   screen (External, add yourself as test user), add the read-only `googlehealth.*`
   scopes, create an OAuth client and register `http://localhost:8765/callback` as a
   redirect URI.
2. Publishing status: apps in *Testing* get refresh tokens that expire after 7 days. Move
   the consent screen to *In production* (no verification needed for personal use; you
   will see an "unverified app" warning on consent).
3. Set `HC_GOOGLE_CLIENT_ID`, `HC_GOOGLE_CLIENT_SECRET` and `HC_TOKEN_KEY`, then on the
   host: `docker compose run --rm worker auth google`, open the printed URL, approve, and
   paste the URL the browser ends up on (it does not load; that is expected).
4. `docker compose run --rm worker backfill google --from 2025-01-01` (resumable; `--type`
   limits it to some data types). Intraday heart rate goes back only 30 days and runs last:
   one request per day with tens of thousands of samples; the daily summaries (resting HR,
   HRV, exercise average/max HR and zones) cover the history.

## Schedule

| Job | When | Range |
| --- | --- | --- |
| `google_recent` | every 30 min | yesterday + today |
| `google_week` | daily 04:00 | last 7 days |
| `google_month` | Sunday 05:00 | last 30 days of sleep |

A revoked or expired grant alerts on the first failure with the re-auth command; other
errors alert after three failures in a row.
