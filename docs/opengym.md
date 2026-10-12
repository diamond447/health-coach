# openGym Integration

Integration guide and technical reference for [openGym](https://github.com/DuarteSantos8/openGym) (v1.4.1, AGPL), the workout tracker health-coach integrates with.

---

## 1. API Architecture & Facts Used

openGym is a self-hosted progressive web app (PWA) with a single-document per-user REST API.

### Endpoints
- **`POST /api/pair/redeem`**: Body `{"code": "<8-char-code>"}`. Exchanges a one-shot pairing code minted in the web UI (Settings -> "Pair the mobile app", 5 min TTL) for `{ "token": "<session-token>", "user": { ... } }`.
- **`GET /api/me`**: Returns user profile and session info. When past half of its 90-day lifetime (`SESSION_DAYS`), the response includes a refreshed `token`. The sync client automatically detects and persists refreshed tokens.
- **`GET /api/data`**: Returns `{ "state": { ... }, "rev": <int> }`. Everything for a user (workouts, routines, schedule, body weight, custom exercises) lives inside `state`.
- **`PUT /api/data`**: Body `{ "state": { ... }, "baseRev": <int>, "baseWid"?: "<str>" }`. Updates the entire user state atomically.

### Optimistic Concurrency Control (OCC / CAS)
- When `PUT /api/data` receives a stale `baseRev`, the server rejects the request with HTTP **409 Conflict** and returns `{ "state": <current_state>, "rev": <current_rev> }`.
- `health_coach.opengym.client.OpenGymClient.mutate(fn)` implements a CAS loop: it fetches the latest state, creates a deep copy, applies the pure mutator `fn`, attempts PUT, and retries up to 3 times on 409 by applying `fn` to the refreshed document.

### Stamping & Field Preservation
- openGym stamps deletions and edits using `_f` (deletion tombstones) and `edited` metadata if `stamped: true` is not provided.
- Writers must preserve all unknown fields across the document and return `edited` / `_f` fields as read to maintain consistency with client sync engines.

---

## 2. State Shapes & Fields

The top-level `state` object contains:

```json
{
  "workouts": [...],
  "routines": [...],
  "week": { "mon": "<routine-id>", "wed": "<routine-id>", ... },
  "dayPlan": { "2026-10-12": "<routine-id>", "2026-10-13": "rest", ... },
  "bodyweight": [ { "d": "2026-01-15", "w": 80, "t": 1768460400000 } ],
  "customEx": [...],
  "unit": "kg"
}
```

### Workouts (`workouts[]`)
Each logged workout session:
- `id` (str): Unique workout ID (e.g. `m1ab2c3d4ef`).
- `d` (str): ISO date `YYYY-MM-DD`.
- `start` / `end` (int | str): Unix timestamps or ISO strings for workout duration.
- `routineId` (str | null): Associated routine ID if started from a template.
- `name` (str): Session name (e.g. "Upper Power", "Push").
- `entries` (array): List of exercise performances:
  - `id` (str): Exercise ID referencing the catalogue or `customEx`.
  - `sets` (array): List of completed sets:
    - `w` (num): Weight lifted (in user's `unit`).
    - `r` (num): Reps completed.
    - `done` (bool): Whether the set was checked off as finished.
    - `rir` (num | null): Reps in reserve (0-10).
    - `rpe` (num | null): Rating of perceived exertion (6-10).
    - `warm` (bool): `true` if marked as a warm-up set.
    - `drop` (bool): `true` if marked as a drop set.
    - `restPause` (bool): `true` for rest-pause sets.
    - `side` (str | null): `"L"` or `"R"` for unilateral exercises.
    - `c` (str | null): Set notes/comments.
- `_ts` (int): Last modified timestamp.

### Routines (`routines[]`)
Templates used to start or plan workouts:
- `id` (str): Unique routine ID.
- `name` (str): Name (e.g. "Upper A").
- `ex` (array): Exercise configurations:
  - `id` (str): Exercise ID.
  - `sets` (int): Number of target sets.
  - `reps` (int | null): Target reps (for fixed rep targets).
  - `repsMin` / `repsMax` (int | null): Rep range (e.g. 8-12 reps).
  - `weight` (num | null): Default target weight.
  - `pyramid` (bool): Whether per-set weights/reps differ across sets.
  - `pyramidWeight` (num[] | null): Explicit target weights per set `[w1, w2, ...]`.
  - `pyramidReps` (num[] | null): Explicit target reps per set `[r1, r2, ...]`.
  - `rest` (int | null): Rest time in seconds.
  - `superset` (str | null): Superset grouping identifier.
  - `prog` (str | null): Progression mode (`"double"`, `"linear"`, `"off"`).
  - `excludeFromProgression` (bool): Disable automatic progression.
  - `mode` (str | null): `"reps"`, `"time"`, or `"cardio"`.
  - `warmUpSets` (int | null): Number of warm-up sets to prompt.

---

## 3. ID Generation

openGym generates unique IDs on the client using Base-36 timestamp and random fragments:
```js
// frontend/src/lib/workout-model.js
Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
```
Python equivalent implemented in `health_coach.opengym.model.make_uid()`:
```python
import math, random, time


def make_uid() -> str:
    ts = math.floor(time.time() * 1000)
    ts_str = _to_base36(ts)
    rand_part = _to_base36(random.randint(0, 36**5 - 1)).rjust(5, "0")
    return ts_str + rand_part
```

---

## 4. Planned Weights & Preventing Progression Overrides

### Problem
openGym includes an automatic progression engine (`frontend/src/lib/progression.js`, `frontend/src/lib/session-start.js`). When a user starts a workout from a routine, the app queries historical workout logs for that exercise and increases targets if the previous session met rep criteria. If a coach sets a specific deload weight or prescribed load, the progression engine could overwrite the coach's prescribed targets with its own calculated progression.

### Solution & Mechanism
To ensure planned weights show up in the openGym web app exactly as specified:
1. **Set `excludeFromProgression: true`** on the routine definition.
2. **Set `prog: "off"`** and `excludeFromProgression: true` on each exercise spec within the routine.
3. **Use `pyramid: True` and `pyramidWeight: [...]`**: In `session-start.js`, when `pyramid` is active and `pyramidWeight` is populated, the starting session extracts per-set target weights directly from `pyramidWeight[i]`, bypassing linear/double progression calculation.

---

## 5. Pairing and Synchronization

### Pairing CLI
1. Open the openGym web app, go to **Settings** -> **Pair the mobile app**.
2. Click **Generate code** (produces an 8-character uppercase string, valid for 5 minutes).
3. In terminal, run:
   ```sh
   health-coach auth opengym
   ```
4. Enter the pairing code. The CLI redeems the code, receives a session token, and stores it Fernet-encrypted in Postgres table `oauth_tokens` with `provider = 'opengym'`.

### Data Synchronization
The worker runs `opengym_workouts` every 15 minutes:
- Pulls `GET /api/data`.
- Renews tokens when `GET /api/me` indicates renewal is due.
- Normalizes weights to kilograms regardless of the user's `unit` setting.
- Upserts sessions into `strength_sessions` and sets into `strength_sets`.
- Mirrored removals: if a workout is deleted from openGym's state document, the sync worker removes the corresponding rows from Postgres.
- Extracts `bodyweight` entries into `body_metrics` with `source = 'opengym'`.
- Synchronizes the exercise catalogue daily at 03:30 from the official openGym GitHub release (`v{HC_OPENGYM_VERSION}`).
