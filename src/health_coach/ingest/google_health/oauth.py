"""Google OAuth 2.0 for the Google Health API: one-time consent and token refresh.

The consent runs once from the CLI (`health-coach auth google`). The refresh token is
stored encrypted in `oauth_tokens`; access tokens are refreshed on demand.
"""

import base64
import datetime as dt
import hashlib
import secrets
import urllib.parse
from dataclasses import dataclass

import httpx
from sqlalchemy import Engine, text

from health_coach.config import Settings
from health_coach.crypto import decrypt, encrypt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
PROVIDER = "google_health"
REAUTH_COMMAND = "docker compose run --rm worker auth google"


class OAuthError(RuntimeError):
    pass


class ReauthRequired(OAuthError):
    """The grant was revoked or expired; the owner has to run the consent again."""


@dataclass
class AuthRequest:
    url: str
    state: str
    verifier: str


def _require(settings: Settings) -> tuple[str, str]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthError("HC_GOOGLE_CLIENT_ID and HC_GOOGLE_CLIENT_SECRET must be set")
    return settings.google_client_id, settings.google_client_secret.get_secret_value()


def start_consent(settings: Settings) -> AuthRequest:
    client_id, _ = _require(settings)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.google_scopes),
        "access_type": "offline",
        "prompt": "consent",  # always return a refresh token
        "state": state,
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
    }
    return AuthRequest(f"{AUTH_URL}?{urllib.parse.urlencode(params)}", state, verifier)


def code_from_redirect(redirected_url: str, expected_state: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(redirected_url.strip()).query)
    if "error" in query:
        raise OAuthError(f"consent failed: {query['error'][0]}")
    if query.get("state", [""])[0] != expected_state:
        raise OAuthError("state does not match: paste the URL from this consent run")
    if "code" not in query:
        raise OAuthError("no code in the URL")
    return query["code"][0]


def _token_request(
    data: dict[str, str], transport: httpx.BaseTransport | None
) -> dict[str, object]:
    with httpx.Client(timeout=15, transport=transport) as client:
        response = client.post(TOKEN_URL, data=data)
    try:
        body: dict[str, object] = response.json() if response.content else {}
    except ValueError:
        body = {}
    if response.status_code == 400 and body.get("error") == "invalid_grant":
        raise ReauthRequired(f"Google rejected the refresh token; run `{REAUTH_COMMAND}`")
    if response.status_code != 200:
        raise OAuthError(f"token endpoint returned {response.status_code}: {body.get('error')}")
    return body


def _store(engine: Engine, settings: Settings, body: dict[str, object], refresh: str) -> None:
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(str(body.get("expires_in", 0))))
    scopes = str(body.get("scope", "")).split()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO oauth_tokens (provider, access_token_enc, refresh_token_enc, "
                "expires_at, scopes) VALUES (:p, :a, :r, :e, :s) "
                "ON CONFLICT (provider) DO UPDATE SET "
                "access_token_enc = EXCLUDED.access_token_enc, "
                "refresh_token_enc = EXCLUDED.refresh_token_enc, "
                "expires_at = EXCLUDED.expires_at, scopes = EXCLUDED.scopes, updated_at = now()"
            ),
            {
                "p": PROVIDER,
                "a": encrypt(str(body["access_token"]), settings),
                "r": encrypt(refresh, settings),
                "e": expires,
                "s": scopes,
            },
        )


def finish_consent(
    engine: Engine,
    settings: Settings,
    request: AuthRequest,
    redirected_url: str,
    transport: httpx.BaseTransport | None = None,
) -> list[str]:
    """Exchange the code and store the tokens. Returns the granted scopes."""
    client_id, secret = _require(settings)
    code = code_from_redirect(redirected_url, request.state)
    body = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": secret,
            "redirect_uri": settings.google_redirect_uri,
            "code_verifier": request.verifier,
        },
        transport,
    )
    if "refresh_token" not in body:
        raise OAuthError("Google returned no refresh token; revoke the app's access and retry")
    _store(engine, settings, body, str(body["refresh_token"]))
    return str(body.get("scope", "")).split()


def access_token(
    engine: Engine, settings: Settings, transport: httpx.BaseTransport | None = None
) -> str:
    """A valid access token, refreshed when it expires within 2 minutes."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT access_token_enc, refresh_token_enc, expires_at FROM oauth_tokens "
                "WHERE provider = :p"
            ),
            {"p": PROVIDER},
        ).first()
    if row is None:
        raise ReauthRequired(f"no Google Health grant stored; run `{REAUTH_COMMAND}`")
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=2)
    if row.access_token_enc and row.expires_at and row.expires_at > soon:
        return decrypt(row.access_token_enc, settings)

    client_id, secret = _require(settings)
    refresh = decrypt(row.refresh_token_enc, settings)
    body = _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": secret,
        },
        transport,
    )
    # Google may rotate the refresh token; keep the old one otherwise.
    _store(engine, settings, body, str(body.get("refresh_token") or refresh))
    return str(body["access_token"])
