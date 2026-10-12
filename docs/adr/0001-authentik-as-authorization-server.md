# ADR 0001: An external OIDC provider is the OAuth authorization server

Status: accepted (2026-10-11). Tested with Authentik.

## Context

Remote MCP connectors in Claude, ChatGPT and Gemini use OAuth 2.1. The MCP server could
implement the authorization server itself (authorization code + PKCE, dynamic client
registration, sign-in, consent, token and refresh storage), but that is a lot of
security-sensitive code with edge cases each client is strict about.

Self-hosters usually already run an identity provider such as Authentik, Keycloak or
Zitadel. Connectors find the authorization server through RFC 9728 protected resource
metadata, which may point at another host, and they accept a pre-registered client ID
and secret in their advanced settings, so dynamic client registration is not required.
Claude Code uses its own client metadata document with loopback redirects.

## Decision

- The OIDC provider is the authorization server. Each MCP server gets a confidential
  OAuth client that issues RS256-signed JWT access tokens with a short lifetime and
  refresh tokens (`offline_access`). The health coach client is bound to the owner only;
  the fit client to everyone allowed to use it.
- Redirect URIs: `https://claude.ai/api/mcp/auth_callback` (Claude web, desktop,
  mobile), loopback `http://localhost:<port>/callback` and `http://127.0.0.1:<port>/callback`
  (Claude Code), and the ChatGPT and Gemini callbacks listed in [fit.md](../fit.md).
- The MCP servers are resource servers only. They answer unauthenticated requests with
  `401` and `WWW-Authenticate: Bearer resource_metadata="https://coach.example.com/.well-known/oauth-protected-resource/mcp"`,
  serve that document with `authorization_servers: [<issuer>]`, and validate each bearer
  token: signature against the provider's JWKS, `iss`, `aud` (the client ID), `exp`, and
  for the health server `sub` in an allowlist from the environment. Because both clients
  are signed by the same provider, the `iss`/`aud` checks keep a token for one server
  from working on the other.
- The user adds the connector with the client ID and secret.

## Consequences

- No OAuth server code in this repository; sign-in, MFA, consent and token issuance live
  in a maintained product.
- Access is managed in the identity provider.
- Without dynamic client registration an assistant cannot self-register; adding the
  connector needs the client secret once. Acceptable for a handful of users.
- If an assistant turns out to need dynamic registration, a small registration shim can
  be added later without changing token validation.
