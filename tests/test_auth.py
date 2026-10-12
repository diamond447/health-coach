import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Engine, text
from starlette.testclient import TestClient

from health_coach.config import Settings
from health_coach.mcp_server import server as server_module
from health_coach.mcp_server.auth import AuthConfigError, JwtTokenVerifier, build_auth

ISSUER = "https://auth.example.test/application/o/health-coach/"
AUDIENCE = "client-123"
PUBLIC_URL = "https://coach.example.test/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(key: Any = KEY, alg: str = "RS256", **overrides: Any) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "owner", "iat": now, "exp": now + 300}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg)


def verifier() -> JwtTokenVerifier:
    return JwtTokenVerifier(ISSUER, AUDIENCE, {"owner"}, PUBLIC_URL, lambda _t: KEY.public_key())


def test_valid_token() -> None:
    token = verifier().verify(make_token(scope="openid offline_access"))
    assert token is not None
    assert token.subject == "owner"
    assert token.scopes == ["openid", "offline_access"]
    assert token.resource == PUBLIC_URL


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(make_token(aud="other-client"), id="wrong audience"),
        pytest.param(make_token(iss="https://evil.test/"), id="wrong issuer"),
        pytest.param(make_token(exp=int(time.time()) - 120), id="expired"),
        pytest.param(make_token(sub="stranger"), id="subject not allowlisted"),
        pytest.param(make_token(key=OTHER_KEY), id="bad signature"),
        pytest.param(make_token(exp=None), id="no exp"),
        pytest.param(make_token(key="x" * 32, alg="HS256"), id="hmac algorithm"),
        pytest.param("not-a-jwt", id="garbage"),
    ],
)
def test_rejected_tokens(token: str) -> None:
    assert verifier().verify(token) is None


def test_alg_key_mismatch_is_rejected_not_raised() -> None:
    from cryptography.hazmat.primitives.asymmetric import ec

    token = make_token(key=ec.generate_private_key(ec.SECP256R1()), alg="ES256")
    jwk = jwt.PyJWK.from_dict(
        {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), "kid": "k1"}
    )
    v = JwtTokenVerifier(ISSUER, AUDIENCE, {"owner"}, PUBLIC_URL, lambda _t: jwk)
    assert v.verify(token) is None


def test_auth_must_be_configured_or_explicitly_disabled() -> None:
    with pytest.raises(AuthConfigError, match="HC_AUTH_ISSUER"):
        build_auth(Settings())
    assert build_auth(Settings(auth_disabled=True)) is None
    with pytest.raises(AuthConfigError, match="ALLOWED_SUBJECTS"):
        build_auth(Settings(auth_issuer=ISSUER, auth_audience=AUDIENCE, public_url=PUBLIC_URL))


@pytest.fixture
def http_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = Settings(
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
        public_url=PUBLIC_URL,
        auth_allowed_subjects=["owner"],
    )
    monkeypatch.setattr(
        "health_coach.mcp_server.auth.jwks_resolver", lambda _url: lambda _t: KEY.public_key()
    )
    app = server_module.create_server(settings, with_auth=True).streamable_http_app(
        host="coach.example.test"
    )
    with TestClient(app, base_url="http://coach.example.test") as client:
        yield client


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_unauthenticated_request_gets_401_with_metadata_pointer(http_client: TestClient) -> None:
    response = http_client.post("/mcp", json=INIT, headers=HEADERS)
    assert response.status_code == 401
    header = response.headers["www-authenticate"]
    assert header.startswith("Bearer")
    assert (
        'resource_metadata="https://coach.example.test/.well-known/oauth-protected-resource/mcp"'
        in header
    )


def test_protected_resource_metadata(http_client: TestClient) -> None:
    doc = http_client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert doc["resource"] == PUBLIC_URL
    assert doc["authorization_servers"] == [ISSUER]


def test_healthz_stays_public(http_client: TestClient) -> None:
    assert http_client.get("/healthz").status_code == 200


def test_bad_token_is_rejected(http_client: TestClient) -> None:
    headers = {**HEADERS, "Authorization": f"Bearer {make_token(sub='stranger')}"}
    assert http_client.post("/mcp", json=INIT, headers=headers).status_code == 401


def test_valid_token_reaches_tools_and_is_audited(http_client: TestClient, owner: Engine) -> None:
    headers = {**HEADERS, "Authorization": f"Bearer {make_token()}"}
    init = http_client.post("/mcp", json=INIT, headers=headers)
    assert init.status_code == 200, init.text
    session = init.headers.get("mcp-session-id")
    if session:
        headers["mcp-session-id"] = session
    http_client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers
    )
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "query_sql", "arguments": {"sql": "SELECT 1 AS one"}},
    }
    response = http_client.post("/mcp", json=call, headers=headers)
    assert response.status_code == 200, response.text
    assert '"one"' in response.text
    with owner.connect() as conn:
        subject = conn.execute(text("SELECT subject FROM mcp_audit")).scalar_one()
    assert subject == "owner"


def test_multiple_audiences_and_any_subject() -> None:
    v = JwtTokenVerifier(
        ISSUER,
        ["client-123", "client-456"],
        None,
        PUBLIC_URL,
        lambda _t: KEY.public_key(),
    )
    t1 = v.verify(make_token(aud="client-123", sub="alice"))
    assert t1 is not None
    assert t1.subject == "alice"

    t2 = v.verify(make_token(aud="client-456", sub="bob"))
    assert t2 is not None
    assert t2.subject == "bob"

    # Audience not in the list is rejected
    assert v.verify(make_token(aud="client-789", sub="charlie")) is None


def test_cross_audience_enforcement() -> None:
    hc_aud = "health-coach-client"
    fit_aud = ["fit-client-claude", "fit-client-chatgpt"]

    hc_verifier = JwtTokenVerifier(
        ISSUER, hc_aud, {"owner"}, PUBLIC_URL, lambda _t: KEY.public_key()
    )
    fit_verifier = JwtTokenVerifier(
        ISSUER, fit_aud, None, "https://fit.example.test/mcp", lambda _t: KEY.public_key()
    )

    hc_token = make_token(aud=hc_aud, sub="owner")
    fit_token = make_token(aud="fit-client-claude", sub="any-user")

    # Fit rejects health-coach token
    assert fit_verifier.verify(hc_token) is None
    # Health-coach rejects fit token
    assert hc_verifier.verify(fit_token) is None
