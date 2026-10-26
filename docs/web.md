# Healthstats Web App

Healthstats is a read-only WHOOP-style Progressive Web Application (PWA) built for
`health-coach`. It visualizes daily recovery, sleep performance, cardiovascular and
muscular strain, nutrition, long-term trends, calendar overviews, and habit journal insights
directly from your health database.

The frontend is implemented in Preact and TypeScript with custom hand-written SVG charts,
achieving a tiny bundle footprint (< 30 kB gzipped) with zero external chart or UI dependencies.
The backend is served by Starlette and uvicorn directly from `health-coach web`, connecting
to PostgreSQL using the read-only `Role.ro` credentials (with a narrow exception for journal
writes using `Role.web_journal` when configured).

## Screens and features

The app is localized in Czech (`lang="cs"`) and provides tabular number formatting,
durations (`7 h 12 min`), and standard WHOOP-style color coding:

- **Dnes (`/`)**: Daily overview with 3 ring dials (Spánek, Recovery, Strain), recommended
  strain target bar, cardio strain and muscular score breakdown under the strain ring ("kardio 9,8 · svaly 64 %"),
  component breakdown ("Co ovlivnilo recovery"), activity summary (steps, active minutes, calories, workout list,
  linking to `/aktivita`), and overnight vitals (SpO2, breathing rate, skin temperature deviation, HRV, linking
  to `/noc`). Both the Aktivita and V noci cards are tappable as a whole with `aria-label` links.
- **Recovery (`/recovery`)**: 200 px ring dial with status text, 30-day scrubbable `TimeChart`s
  with normal baseline bands for HRV and resting heart rate, 3 additional 30-day `TimeChart`s
  below them for sleep performance (%), breathing rate (/min with baseline band), and skin
  temperature deviation (°C with baseline band), detailed signal breakdown with standard
  deviation ($\sigma$) weights, and illness/fever warning cards.
- **Aktivita (`/aktivita`)**: 30-day activity detail reachable from the Dnes activity card.
  Displays 30-day `TimeChart`s for daily steps (bars, dashed target line from `targets.steps`
  when configured), active minutes (bars), and calories burned (line), along with their
  30-day daily averages.
- **Noc (`/noc`)**: Overnight vitals detail reachable from the Dnes "V noci" card. Displays
  30-day `TimeChart`s for HRV, resting heart rate, SpO₂, breathing rate, and skin temperature
  deviation, each showing the latest day's value, 30-day mean, and personal baseline band.
- **Spánek (`/spanek`)**: Sleep performance ring dial, time in bed and sleep duration,
  "Plán na dnešní noc" card (suggested bedtime, alarm, assumed efficiency), hypnogram
  chart showing awake / REM / light / deep stages, sleep need breakdown (base need, debt,
  strain bonus, nap credit), and a 30-night scrubbable `TimeChart` comparing actual sleep
  duration bars to nightly sleep need dots.
- **Strain (`/strain`)**: Two ring dials side by side for Kardio strain (0–21) and Svaly (0–100 %,
  with band label), total strain summary with recommended target range, cardio and muscular load (TRIMP),
  scrubbable intraday 5-minute heart rate chart with workout overlay windows, zone 3 threshold line,
  and time readout ("HH:MM · 142 bpm"), time spent across 5 HR zones, logged workouts and activities
  (with per-session muscular score for strength sessions), and two 30-day scrubbable history `TimeChart`s
  for cardio strain (line) and muscular load (bars).
- **Jídlo (`/jidlo`)**: Calorie intake ring dial vs daily target, macronutrient bars
  (protein, carbohydrates, fat, fiber), energy balance card (intake vs TDEE, 14-day mean,
  expected vs actual weight change), meals list grouped by meal time, and 7-day calorie chart
  highlighting protein target achievement.
- **Trendy (`/trendy`)**: Sub-navigation tiles in a 2x2 grid (Kalendář, Deník, Přehled,
  Healthspan), period navigation with "‹" and "›" window shift buttons (disabled when ending today)
  and date range readout ("1. 10. – 30. 10."), 7/30/90-day time range selector, daily recovery bars,
  HRV & RHR trend chart (with x-axis), sleep duration bars, two scrubbable charts for Kardio strain and
  Svalová zátěž with acute-to-chronic workload ratio (ACWR), raw and 7-day smoothed weight trend (with x-axis),
  and calorie intake vs target. All charts are powered by scrubbable `TimeChart` components with y-axes.
- **Healthspan (`/healthspan`)**: Estimated biological age and pace of aging (see
  [healthspan.md](healthspan.md)). Displays biological age delta (e.g. `−2,6 roku`), pace of
  aging (`0,8×`), signal coverage count ("8 z 9 signálů s daty"), and a 6-month breakdown of
  what rejuvenates or ages you across 9 physiological and lifestyle factors.
- **Kalendář (`/kalendar`)**: Interactive month calendar with metric toggle (Recovery,
  Spánek, Strain), color-coded daily tiles, month statistics (average recovery, green/yellow/red
  counts, average sleep, ending sleep debt, total workouts).
- **Deník (`/denik`)**: Habit impact analysis over the last 60 days. Shows yesterday's
  habits (tappable to log or remove when write access is enabled) and two-sided recovery
  impact bars showing the difference in next-day recovery with and without each habit.
- **Týdenní přehled (`/prehled`)**: Weekly or monthly review card comparing metrics to the
  previous period (including total strain, cardio and muscular averages), daily recovery bars, best
  and worst days, volume of hard sets per muscle group, and the weekly coaching review text from the
  coach log. Includes "‹" and "›" period navigation buttons moving by one week or one month (disabled
  for current period) with date range displayed in the header.

## Chart Interactions and TimeChart

All daily time-series and intraday charts use a shared SVG component (`TimeChart.tsx`):

- **Scrub interaction**: Dragging or touching over the chart snaps to the nearest day/point,
  draws a vertical cursor dashed line and dots on each series, and updates a readout above
  the chart in Czech format: `"po 20. 10. · HRV 31 ms · klidový tep 68 bpm"` (or `"HH:MM · 142 bpm"`
  for intraday heart rate).
- **Default state**: Without an active touch, the readout shows the latest day. Releasing the
  finger preserves the selection.
- **Mobile scrolling**: SVGs configure `touch-action: pan-y` so vertical page scrolling works
  smoothly while horizontal swipes scrub the timeline.
- **Gaps & baselines**: Null gaps break the line segments cleanly without manufacturing fake values.
  Personal baseline bands are rendered as shaded polygons behind the series lines.
- **Axes**: Y axis renders 3–4 nicely rounded tick marks via `niceTicks(min, max, count)` with
  faint horizontal grid lines. X axis renders 3–5 date labels ("d. M.") under the chart where enabled.

## Period Navigation

- **Trendy (`/trendy`)**: "‹" and "›" buttons shift the viewing window by its selected length
  (7, 30, or 90 days) via the `?date=` query parameter. "›" is automatically disabled when the
  window ends on the current day. The date range ("d. M. – d. M.") is shown alongside the buttons.
- **Přehled (`/prehled`)**: "‹" and "›" buttons move the report window by 1 week or 1 month
  (matching the active Týden/Měsíc toggle) using `/api/report?period=&end=`. "›" is disabled for
  the current period, and the range is displayed in the header.
- URL parameters (`?date=` and `?end=`) keep the browser history, reload, and back/forward navigation
  in sync. All touch targets meet the ≥ 44 px accessibility standard.

## API Endpoints

- `GET /api/day?date=YYYY-MM-DD`: daily overview (rings, activity, vitals, scores).
- `GET /api/recovery?date=YYYY-MM-DD&days=30`: recovery score, component weights, 30-day HRV, RHR,
  sleep performance, breathing rate, and skin temperature series with baseline bands.
- `GET /api/activity?date=YYYY-MM-DD&days=30`: 30-day daily activity time series (steps, active minutes,
  calories out), 30-day averages, and step target from `targets.steps` (days 7–90).
- `GET /api/night?date=YYYY-MM-DD&days=30`: 30-day overnight vitals (HRV, RHR, SpO₂, breathing rate,
  skin temperature deviation), 30-day means, and personal baseline bands (days 7–90).
- `GET /api/sleep?date=YYYY-MM-DD&days=30`: sleep session, stages, need breakdown, tonight plan,
  and 30-day comparison series.
- `GET /api/strain?date=YYYY-MM-DD&days=30`: strain score, TRIMP load, heart rate zones, intraday samples,
  workout windows, activities, and 30-day strain history.
- `GET /api/nutrition?date=YYYY-MM-DD`: calorie & macro intake, energy balance, meal log, micronutrients (`micros`), and logging coverage (`micros_coverage`).
- `GET /api/trends?date=YYYY-MM-DD&days=30`: trends over 7, 30, or 90 days for recovery, HRV, RHR,
  sleep, strain, weight, and calories.
- `GET /api/calendar?month=YYYY-MM`: monthly calendar cells with recovery/sleep/strain data.
- `GET /api/journal?date=YYYY-MM-DD&days=60`: habit impact on next-day recovery, tappable options, and write status.
- `PUT /api/journal/entries`: upsert a journal entry for `date` (body: `{"date": "YYYY-MM-DD", "behavior": "alcohol", "amount": 2 | null, "note": "..." | null}`). Returns the refreshed `/api/journal` payload for the date shown.
- `DELETE /api/journal/entries?date=YYYY-MM-DD&behavior=alcohol`: soft-delete an entry.
- `GET /api/report?period=week|month&end=YYYY-MM-DD`: weekly/monthly comparative review and coaching note.
- `GET /api/healthspan?weeks=26`: biological age and pace of aging factor breakdown.

## Security and Forward-Auth

Healthstats is designed to run behind a forward-auth reverse proxy such as
[Authentik](https://goauthentik.io), Traefik Forward Auth, or Authelia.

As a defense-in-depth measure, every `/api/*` request must carry an authenticated user header
matching a name in `HC_WEB_ALLOWED_USERS` (configured in `.env` as a JSON list, e.g.
`["your-username"]`). If `HC_WEB_ALLOWED_USERS` is non-empty and the header is missing or
disallowed, the server immediately returns a `403 Forbidden` JSON response.

All API responses set `Cache-Control: no-store` to prevent caching of personal health data on
intermediate proxies.

### Journal Write Exception and CSRF Security

The web app is read-only by default (`Role.ro`). One narrow exception is allowed: logging
journal entries (`PUT /api/journal/entries` and `DELETE /api/journal/entries`).

The write exception adheres to strict defense-in-depth principles:
- **Least Privilege Role (`Role.web_journal`)**: Connects using credentials configured via
  `HC_WEB_JOURNAL_DATABASE_URL`. The role possesses `SELECT, INSERT` and column-level
  `UPDATE (amount, note, updated_at, deleted_at)` on `journal_entries` and sequence usage only.
  It has no read or write access to any other tables.
- **CSRF Protection**:
  - `Content-Type: application/json` is required for `PUT` requests (rejects `text/plain` or form submissions).
  - The `Origin` header (or `Referer` if `Origin` is omitted) must match the request's own host
    (`Host` or `X-Forwarded-Host`) and scheme (from `X-Forwarded-Proto` or request URL); mismatches return `403 Forbidden`.
  - Both `PUT` and `DELETE` require the custom header `X-Healthstats: 1`.
- **User Authentication Requirement**: Write routes strictly require `HC_WEB_ALLOWED_USERS` to be
  configured and non-empty. In unauthenticated dev mode (empty allowed users), write routes return `403 Forbidden`.
- **Validation and Size Limits**:
  - Request body is streamed and stopped after 2048 bytes with `400 Bad Request` (handles chunked bodies).
  - Amount must be a finite number between 0 and 9999.99 with at most 2 decimal places (strings and non-finite values rejected).
  - Notes are limited to 200 characters of plain text with no control characters (including `\x00` and newlines).
- **Method Restrictions**: Only `/api/journal/entries` accepts non-GET methods. All other API
  routes remain strictly GET-only (returning `405 Method Not Allowed` on mutations).
- **Graceful Degradation**: If `HC_WEB_JOURNAL_DATABASE_URL` is unset, write attempts return
  `503 Service Unavailable` (`{"error": "journal_writes_disabled"}`). `GET /api/journal` reports
  `"can_write": false` whenever the write database URL is unset or `HC_WEB_ALLOWED_USERS` is empty,
  hiding interactive controls in the UI.
- **Service Worker**: The PWA service worker never caches or intercepts `PUT` or `DELETE` requests.

### Public Paths (Bypassing Auth)

iOS Safari fetches PWA web manifests and home screen icons out-of-band **without session
cookies**. Therefore, reverse proxies must allow unauthenticated access to the following public
paths:

- `/manifest.webmanifest`
- `/icons/*` (e.g. `/icons/apple-touch-icon.png`, `/icons/icon-192.png`, etc.)
- `/healthz` (liveness / readiness check)

### Authentik Proxy Configuration Example

When using Authentik with Traefik or Caddy as a forward-auth provider:

```yaml
# Traefik Forward-Auth Middleware Example
http:
  middlewares:
    authentik-forward-auth:
      forwardAuth:
        address: "http://authentik-server:9000/outpost.goauthentik.io/auth/traefik"
        trustForwardHeader: true
        authResponseHeaders:
          - "X-authentik-username"
          - "X-authentik-email"

  routers:
    # Public bypass router for PWA manifest and icons
    healthstats-public:
      rule: "Host(`stats.example.com`) && (Path(`/manifest.webmanifest`) || PathPrefix(`/icons/`) || Path(`/healthz`))"
      service: "healthstats-svc"
      entryPoints: ["websecure"]

    # Protected router for application shell and API
    healthstats-protected:
      rule: "Host(`stats.example.com`)"
      service: "healthstats-svc"
      entryPoints: ["websecure"]
      middlewares:
        - "authentik-forward-auth"

  services:
    healthstats-svc:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8090"
```

## Adding to iPhone Home Screen

Healthstats is optimized for iOS Safari PWA standalone mode:

1. Open `https://stats.example.com` in Safari on iOS.
2. Log in through your reverse proxy / Authentik screen.
3. Tap the **Share** button (box with an upward arrow) in the Safari toolbar.
4. Scroll down and tap **Add to Home Screen** (*Přidat na plochu*).
5. Name it **Healthstats** and tap **Add**.
6. Launch Healthstats from your home screen. It runs standalone without browser chrome,
   respecting safe-area insets at the top and around the bottom navigation bar.

## Development Workflow

### Prerequisites

- Node.js 20+ and npm
- Python 3.12+ and `uv`

### 1. Build Frontend

The frontend source code lives in `web/` at the repository root. Building compiles the
Preact TypeScript application into `src/health_coach/web/static/`:

```sh
cd web
npm ci
npm run typecheck   # Typecheck with tsc
npm test            # Run vitest unit tests
npm run build       # Build production bundle (< 30 kB gzipped)
cd ..
```

### 2. Run Web Server

Start the web server locally using the CLI:

```sh
# Connects with Role.ro
HC_RO_DATABASE_URL=postgresql+psycopg://coach_ro:password@127.0.0.1:5432/health \
HC_TIMEZONE=Europe/Prague \
uv run health-coach web
```

By default, the server binds to `127.0.0.1:8090`. During development when
`HC_WEB_ALLOWED_USERS` is left empty (`[]`), the username header check is disabled.

### API contract

The frontend types in `web/src/types.ts` must match what the API really returns. Two
checks keep them in step:

- `tests/test_web.py` writes one sample response per endpoint to `web/src/fixtures/api/`
  (synthetic data) and fails when the committed samples no longer have the shape the API
  returns. After changing a response, regenerate them:
  `HC_UPDATE_WEB_FIXTURES=1 uv run pytest tests/test_web.py`.
- `npm run typecheck` checks every sample against its response type
  (`web/src/fixtures.ts`), and `npm test` renders every screen with the samples
  (`web/src/screens.test.tsx`) and fails on any render error.
