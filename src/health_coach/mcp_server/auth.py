"""Bearer token validation for the remote connector (see docs/adr/0001).

Authentik is the authorization server; this server is only a resource server. A token is
accepted when its signature verifies against Authentik's JWKS, `iss` and `aud` match, it
has not expired, and its `sub` is on the allowlist.
"""

import logging
from collections.abc import Callable
from typing import Any

import anyio.to_thread
import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from health_coach.config import Settings

log = logging.getLogger(__name__)

ALGORITHMS = ["RS256", "ES256"]
LEEWAY_SECONDS = 30

KeyResolver = Callable[[str], Any]


class AuthConfigError(RuntimeError):
    pass


class JwtTokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str | list[str] | set[str],
        allowed_subjects: set[str] | None,
        resource: str,
        key_resolver: KeyResolver,
    ) -> None:
        if allowed_subjects is not None and not allowed_subjects:
            raise AuthConfigError("HC_AUTH_ALLOWED_SUBJECTS must name at least one subject")
        if not audience:
            raise AuthConfigError("audience must name at least one audience")
        self.issuer = issuer
        self.audience = audience
        self.allowed_subjects = allowed_subjects
        self.resource = resource
        self._key_resolver = key_resolver

    def verify(self, token: str) -> AccessToken | None:
        try:
            key = self._key_resolver(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # any failure (bad key type, JWKS down) rejects the token
            log.info("rejected bearer token: %s: %s", type(exc).__name__, exc)
            return None
        subject = str(claims["sub"])
        if self.allowed_subjects is not None and subject not in self.allowed_subjects:
            log.warning("rejected bearer token for subject %r: not allowlisted", subject)
            return None
        scope = claims.get("scope", "")
        aud_claim = claims.get("aud")
        if isinstance(aud_claim, list):
            aud_str = aud_claim[0] if aud_claim else ""
        else:
            aud_str = str(aud_claim) if aud_claim else ""
        default_client_id = (
            self.audience
            if isinstance(self.audience, str)
            else (next(iter(self.audience)) if self.audience else "")
        )
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or aud_str or default_client_id),
            scopes=scope.split() if isinstance(scope, str) else [],
            expires_at=int(claims["exp"]),
            resource=self.resource,
            subject=subject,
            claims={"iss": claims["iss"]},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        # JWKS lookups may block on HTTP; keep them off the event loop.
        return await anyio.to_thread.run_sync(self.verify, token)


def jwks_resolver(jwks_url: str) -> KeyResolver:
    # cache_keys=False: the per-kid cache never expires, so a key removed from the JWKS
    # would stay trusted. The JWK set itself is cached for an hour.
    client = jwt.PyJWKClient(
        jwks_url, cache_keys=False, cache_jwk_set=True, lifespan=3600, timeout=5
    )

    def resolve(token: str) -> Any:
        # Returning the PyJWK (not its raw key) lets PyJWT check that the token's alg
        # matches the key type.
        return client.get_signing_key_from_jwt(token)

    return resolve


def build_verifier(
    issuer: str,
    audience: str | list[str] | set[str],
    resource: str,
    jwks_url: str | None = None,
    allowed_subjects: set[str] | None = None,
    key_resolver: KeyResolver | None = None,
) -> tuple[JwtTokenVerifier, AuthSettings]:
    """Construct verifier and AuthSettings from explicit parameters."""
    jwks_url = jwks_url or issuer.rstrip("/") + "/jwks/"
    resolver = key_resolver or jwks_resolver(jwks_url)
    verifier = JwtTokenVerifier(
        issuer=issuer,
        audience=audience,
        allowed_subjects=allowed_subjects,
        resource=resource,
        key_resolver=resolver,
    )
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
        validate_token_resource=False,  # the verifier checks `aud` itself
        required_scopes=None,
    )
    return verifier, auth


def build_auth(settings: Settings) -> tuple[JwtTokenVerifier, AuthSettings] | None:
    """Verifier and SDK auth settings, or None when auth is explicitly disabled."""
    if settings.auth_disabled:
        log.warning("MCP auth is DISABLED: only acceptable on a loopback-only dev setup")
        return None
    missing = [
        name
        for name, value in (
            ("HC_AUTH_ISSUER", settings.auth_issuer),
            ("HC_AUTH_AUDIENCE", settings.auth_audience),
            ("HC_PUBLIC_URL", settings.public_url),
        )
        if not value
    ]
    if missing:
        raise AuthConfigError(
            f"missing {', '.join(missing)} (or set HC_AUTH_DISABLED=true for local development)"
        )
    assert settings.auth_issuer and settings.auth_audience and settings.public_url
    if not settings.auth_allowed_subjects:
        raise AuthConfigError("HC_AUTH_ALLOWED_SUBJECTS must name at least one subject")
    return build_verifier(
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        resource=settings.public_url,
        jwks_url=settings.auth_jwks_url,
        allowed_subjects=set(settings.auth_allowed_subjects),
    )
