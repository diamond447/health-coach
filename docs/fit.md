# Fit MCP Server

A multi-user remote Model Context Protocol (MCP) server that connects AI assistants—including Claude (claude.ai), ChatGPT, and Gemini—to self-hosted [openGym](https://github.com/DuarteSantos8/openGym) accounts.

---

## 1. Overview & Architecture

While the primary `health-coach` MCP server manages comprehensive health, biometric, nutrition, and coaching logs in Postgres for a single owner, the **fit** MCP server is a dedicated, multi-user service focused exclusively on workout tracking and session planning:

- **Multi-user isolation**: Any user your OIDC provider (e.g. Authentik) lets authorize the fit client can connect their own AI assistant. Each user links to their own openGym account via mobile pairing codes and accesses only their own training data.
- **Strict data boundary**: The fit server never touches PostgreSQL or health databases; it does not import `health_coach.db` or health coaching tools. It stores user-account links in an independent SQLite database (`/data/fit.db`).
- **Data privacy**: Workout content and tokens are never logged. Auditing records only tool name, Authentik subject, and duration. Workout and routine data leaves the server solely to the specific assistant connected by that user.
- **Preserved progression**: Planned workout sessions are stamped with `excludeFromProgression: true` and explicit per-set `pyramidWeight` targets, ensuring openGym displays the coach's exact prescribed weights without automatic progression recalculations overriding them.

---

## 2. Connecting AI Assistants

The fit server exposes an RFC 9728 OAuth 2.1 protected resource endpoint at `https://fit.example.com/mcp`. An external OIDC provider (Authentik in the examples below) is the OAuth authorization server.

### Authentik Configuration

In Authentik, create an OAuth2/OIDC provider and application with:
- **Client type**: Confidential
- **Signing Key**: RS256
- **Allowed Redirect URIs**:
  - Claude (web/desktop/mobile): `https://claude.ai/api/mcp/auth_callback`
  - Claude Code (CLI): Regex `^http://(localhost|127\.0\.0\.1):[0-9]+/callback$`
  - ChatGPT: Regex `^https://chatgpt\.com/connector/oauth/.+$` and `https://chatgpt.com/connector_platform_oauth_redirect`
  - Gemini: Regex `^https://oauth-redirect\.googleusercontent\.com/r/.+$`

### Claude (claude.ai)
1. Navigate to **Settings** -> **Connectors** (or **Integrations**).
2. Add a custom connector with URL: `https://fit.example.com/mcp`.
3. Under **Advanced settings**, enter your Authentik OAuth **Client ID** and **Client Secret**.
4. Authorize via Authentik when prompted.

### ChatGPT
1. Go to **Settings** -> **Developer mode** -> **Connectors** (or Custom Connectors).
2. Enter the connector URL: `https://fit.example.com/mcp`.
3. Set authentication to OAuth 2.0 with Client ID and Secret.
4. Select `client_secret_basic` or `client_secret_post` as client authentication scheme.
5. Complete authorization in Authentik.

### Gemini
1. Navigate to [gemini.google.com](https://gemini.google.com) -> **Settings** -> **Connected apps** -> **Custom apps**.
2. Select **Advanced** and provide the Client ID and Secret (*Note: available for personal accounts in supported regions*).
3. Complete Authentik consent.

---

## 3. Account Pairing Flow

Each user links their assistant to openGym using openGym's mobile pairing mechanism:

1. Open the openGym web app.
2. Go to **Settings** -> **"Pair the mobile app"**.
3. Click **Generate code** to produce an 8-character code (valid for 5 minutes).
4. In your assistant chat, type:
   > "Pair my openGym account with code `ABCDEFGH`"
5. The assistant calls `link_opengym("ABCDEFGH")`. The fit server redeems the one-shot code with openGym, encrypts the session token using Fernet at rest, and confirms connection with the openGym username.
6. To disconnect, ask the assistant to call `unlink_opengym()`.
7. **Session renewal**: Session tokens are automatically refreshed via openGym's `GET /api/me` and stored encrypted. If openGym returns HTTP 401 (e.g. session invalidated), existing links are preserved and the assistant prompts you to generate a new pairing code.

---

## 4. MCP Tools Reference

All tools produce compact outputs, round kilogram loads according to app conventions (0.5 kg for weights, 0.1 kg for body weight / e1RM), and include assistant-tailored docstrings.

| Tool | Annotation | Description |
| --- | --- | --- |
| `link_opengym(code)` | WRITE | Redeems an 8-character pairing code from openGym Settings and links the user's account. |
| `unlink_opengym()` | DESTRUCTIVE | Disconnects the user's openGym account and deletes the encrypted token link. |
| `get_account()` | READ | Returns profile information, connection timestamps, and verifies session validity / token renewal. |
| `search_exercises(query?, muscle?, equipment?, limit=20)` | READ | Searches both the official exercise catalogue and the user's custom exercises. |
| `get_training_history(days=28, exercise?)` | READ | Returns logged workouts with exercises and sets (weights, reps, RIR/RPE, warm-up flags). If `exercise` is given, includes top set and e1RM progression trend. |
| `get_routines()` | READ | Lists all routine templates configured in the user's openGym account. |
| `get_routine(routine_id)` | READ | Fetches full configuration of a specific routine (exercises, sets, rep ranges, target weights, pyramid targets, rest periods). |
| `get_planned(days=14)` | READ | Displays upcoming scheduled routines and rest days resolved from `dayPlan` and recurring `week` rules. |
| `plan_session(date, name, exercises, replace=false)` | WRITE | Creates or updates a dated workout in openGym with explicit sets, reps, and weights. Preserves weights against auto-progression. |
| `update_routine(routine_id, changes)` | WRITE | Modifies routine metadata, notes, or exercise specifications. |
| `schedule_week(schedule)` | WRITE | Updates recurring weekly routine assignments (`{mon: routine_id, wed: null}`). |
| `delete_planned(date)` | DESTRUCTIVE | Removes a dated session from `dayPlan` or marks recurring days as rest. |
| `log_session(date, exercises, notes?)` | WRITE | Logs a completed workout session directly into openGym history. |

---

## 5. Deployment & Configuration

The fit server runs via `health-coach fit-mcp` or Docker Compose service `fit`:

```yaml
  fit:
    image: ${HC_IMAGE:-health-coach:dev}
    build: .
    restart: unless-stopped
    command: ["fit-mcp"]
    environment:
      FIT_OPENGYM_URL: ${FIT_OPENGYM_URL:-}
      FIT_OPENGYM_VERSION: ${FIT_OPENGYM_VERSION:-1.4.1}
      FIT_DB_PATH: /data/fit.db
      FIT_TOKEN_KEY: ${FIT_TOKEN_KEY:-}
      FIT_PUBLIC_URL: ${FIT_PUBLIC_URL:-}
      FIT_AUTH_ISSUER: ${FIT_AUTH_ISSUER:-}
      FIT_AUTH_AUDIENCE: ${FIT_AUTH_AUDIENCE:-[]}
      FIT_AUTH_JWKS_URL: ${FIT_AUTH_JWKS_URL:-}
      FIT_MCP_HOST: 0.0.0.0
      FIT_MCP_PORT: "8081"
      FIT_TIMEZONE: ${FIT_TIMEZONE:-UTC}
    volumes:
      - fit-data:/data
    ports:
      - 127.0.0.1:8081:8081
```

`/data/fit.db` holds only the encrypted account links. To back it up while the server runs, use SQLite's online backup (`sqlite3.Connection.backup` or `sqlite3 /data/fit.db ".backup /data/fit.db.backup"`) and copy the result; losing it only means users pair again.
