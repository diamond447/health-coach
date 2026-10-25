# Healthstats Web App

Healthstats is a read-only WHOOP-style Progressive Web Application (PWA) built for
`health-coach`. It visualizes daily recovery, sleep performance, cardiovascular and
muscular strain, nutrition, long-term trends, calendar overviews, and habit journal insights
directly from your health database.

The frontend is implemented in Preact and TypeScript with custom hand-written SVG charts,
achieving a tiny bundle footprint (< 30 kB gzipped) with zero external chart or UI dependencies.
The backend is served by Starlette and uvicorn directly from `health-coach web`, connecting
to PostgreSQL using the read-only `Role.ro` credentials.

## Screens and features

The app is localized in Czech (`lang="cs"`) and provides tabular number formatting,
durations (`7 h 12 min`), and standard WHOOP-style color coding:

- **Dnes (`/`)**: Daily overview with 3 ring dials (Spánek, Recovery, Strain), recommended
  strain target bar, component breakdown ("Co ovlivnilo recovery"), activity summary (steps,
  active minutes, calories, workout list), and overnight vitals (SpO2, breathing rate, skin
  temperature deviation, HRV).
- **Recovery (`/recovery`)**: 200 px ring dial with status text, 30-day HRV line chart with
  normal baseline band, 30-day resting heart rate chart with baseline band, detailed signal
  breakdown with standard deviation ($\sigma$) weights, and illness/fever warning cards.
- **Spánek (`/spanek`)**: Sleep performance ring dial, time in bed and sleep duration,
  "Plán na dnešní noc" card (suggested bedtime, alarm, assumed efficiency), hypnogram
  chart showing awake / REM / light / deep stages, sleep need breakdown (base need, debt,
  strain bonus, nap credit), and 7-night comparison bars.
- **Strain (`/strain`)**: Strain dial (0–21 scale), cardio and muscular load (TRIMP),
  intraday 5-minute heart rate chart with workout overlay windows and zone 3 threshold line,
  time spent across 5 HR zones, logged workouts and activities, and 7-day strain history.
- **Jídlo (`/jidlo`)**: Calorie intake ring dial vs daily target, macronutrient bars
  (protein, carbohydrates, fat, fiber), energy balance card (intake vs TDEE, 14-day mean,
  expected vs actual weight change), meals list grouped by meal time, and 7-day calorie chart
  highlighting protein target achievement.
- **Trendy (`/trendy`)**: Sub-navigation tiles (Kalendář, Deník, Přehled), 7/30/90-day time
  range selector, daily recovery bars, HRV & RHR trend chart, sleep duration bars, strain
  bars with acute-to-chronic workload ratio (ACWR), raw and 7-day smoothed weight trend,
  and calorie intake vs target.
- **Kalendář (`/kalendar`)**: Interactive month calendar with metric toggle (Recovery,
  Spánek, Strain), color-coded daily tiles, month statistics (average recovery, green/yellow/red
  counts, average sleep, ending sleep debt, total workouts).
- **Deník (`/denik`)**: Habit impact analysis over the last 60 days. Shows yesterday's
  habits (logged via Claude) and two-sided recovery impact bars showing the difference in
  next-day recovery with and without each habit.
- **Týdenní přehled (`/prehled`)**: Weekly or monthly review card comparing metrics to the
  previous period, daily recovery bars, best and worst days, volume of hard sets per muscle
  group, and the weekly coaching review text from the coach log.

## Security and Forward-Auth

Healthstats is designed to run behind a forward-auth reverse proxy such as
[Authentik](https://goauthentik.io), Traefik Forward Auth, or Authelia.

As a defense-in-depth measure, every `/api/*` request must carry an authenticated user header
matching a name in `HC_WEB_ALLOWED_USERS` (configured in `.env` as a JSON list, e.g.
`["your-username"]`). If `HC_WEB_ALLOWED_USERS` is non-empty and the header is missing or
disallowed, the server immediately returns a `403 Forbidden` JSON response.

All API responses set `Cache-Control: no-store` to prevent caching of personal health data on
intermediate proxies.

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
