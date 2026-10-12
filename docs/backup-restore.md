# Backup and Restore Procedure

Back up the `health` database nightly with a custom-format dump (`pg_dump -Fc`), keep the
dumps for about 30 days, and test a restore every quarter into a scratch container. How
you schedule it (cron, a systemd timer, a backup container, VM snapshots) is up to your
host; the commands below are the parts that matter.

## What to back up

- The `health` database (`pg_dump -Fc`). Roles and their passwords are cluster-wide and
  not in the dump: on a new server, create the roles before restoring and set their
  passwords with `health-coach db sync-roles` (see the restore test below).
- `.env` (passwords and the Fernet keys; without `HC_TOKEN_KEY` the stored Google and
  openGym tokens cannot be decrypted, and you have to authorize again). Keep it
  encrypted and separate from the dumps.
- The fit server's `fit-data` volume (`/data/fit.db`, only account links; see
  [fit.md](fit.md)).
- openGym's own data, as its documentation describes.

### Nightly dump

```sh
BACKUPS=/srv/backups/health-coach
docker compose exec -T db pg_dump -Fc -U health -d health \
  > "$BACKUPS/health_$(date +%Y%m%d_%H%M%S).dump"
find "$BACKUPS" -name 'health_*.dump' -mtime +30 -delete
```

---

## Quarterly Restore Test

A backup is only as good as its restore. Run this test once per quarter in an ephemeral scratch container to confirm data integrity and verify role permissions.

### 1. Start an Ephemeral PostgreSQL Container

Start a clean Postgres container on an unused local port (e.g. `55434`):

```sh
docker run -d --name pg-restore-test \
  -e POSTGRES_PASSWORD=restoretest \
  -p 55434:5432 \
  postgres:16-alpine
```

Wait until the scratch database is accepting connections:

```sh
docker exec pg-restore-test pg_isready -U postgres
```

### 2. Create the Database and Roles

Roles are cluster-level objects, so a database dump does not contain them. Create the
service roles first, so the restore can apply its grants to them:

```sh
docker exec pg-restore-test createdb -U postgres health
docker exec pg-restore-test psql -U postgres -c \
  "CREATE ROLE coach_ro NOLOGIN; CREATE ROLE coach_rw NOLOGIN;
   CREATE ROLE ingest NOLOGIN; CREATE ROLE grafana_ro NOLOGIN;"
```

### 3. Restore the Dump

Use `--no-owner` so all objects belong to the connecting user; keep the privileges, they
are what makes the service roles work:

```sh
docker exec -i pg-restore-test pg_restore -U postgres -d health --no-owner \
  < /srv/backups/health-coach/health_YYYYMMDD_HHMMSS.dump
```

### 4. Set Role Logins

`health-coach db sync-roles` gives each role `LOGIN` with the password from its service
URL and sets the database time zone. Run it from the image against the scratch server:

```sh
docker run --rm --network host \
  -e HC_DATABASE_URL="postgresql+psycopg://postgres:restoretest@127.0.0.1:55434/health" \
  -e HC_RO_DATABASE_URL="postgresql+psycopg://coach_ro:test-ro@127.0.0.1:55434/health" \
  -e HC_RW_DATABASE_URL="postgresql+psycopg://coach_rw:test-rw@127.0.0.1:55434/health" \
  -e HC_INGEST_DATABASE_URL="postgresql+psycopg://ingest:test-ingest@127.0.0.1:55434/health" \
  -e HC_TIMEZONE="Europe/Berlin" \
  ghcr.io/diamond447/health-coach:main db sync-roles
```

### 5. Verify Data and Views

Execute a query on `v_daily` using the `coach_ro` role to ensure views compile and historical records exist:

```sh
docker exec pg-restore-test psql -U coach_ro -d health -c "
SELECT
  local_date,
  steps,
  resting_hr,
  kcal_in,
  weight_kg,
  hard_sets
FROM v_daily
ORDER BY local_date DESC
LIMIT 7;
"
```

Verify that:
1. `v_daily` returns recent daily records without SQL errors.
2. The `coach_ro` user cannot read `raw_payloads` or `oauth_tokens`:
   ```sh
   docker exec pg-restore-test psql -U coach_ro -d health -c "SELECT count(*) FROM oauth_tokens;"
   # Expected output: ERROR: permission denied for table oauth_tokens
   ```

### 6. Clean Up

Stop and remove the scratch container:

```sh
docker rm -f pg-restore-test
```
