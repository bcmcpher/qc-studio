"""Resolve the identity (email) of the user connected to this Streamlit session.

QC-Studio is exposed through a Cloudflare Tunnel protected by Cloudflare Access.
Access authenticates the user and forwards two headers to the origin on every
request, including the websocket upgrade Streamlit uses:

* ``Cf-Access-Authenticated-User-Email`` – the plain-text email
* ``Cf-Access-Jwt-Assertion`` – a signed JWT whose ``email`` claim is the same user

Resolution order (first match wins):

1. **JWT mode** – when ``CF_ACCESS_TEAM_DOMAIN`` and ``CF_ACCESS_AUD`` are set, the
   JWT is verified against the team's public keys and its ``email`` claim is used.
   The plain header is *never* trusted in this mode, so a request that bypasses the
   tunnel cannot spoof an identity.
2. **Header mode** – otherwise the ``Cf-Access-Authenticated-User-Email`` header is
   trusted. Only safe when Streamlit is bound to ``127.0.0.1`` so the tunnel is the
   sole way in.
3. **Dev mode** – otherwise ``QC_STUDIO_DEV_USER_EMAIL`` (for local testing without a
   tunnel). Never set this in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st

EMAIL_HEADER = "cf-access-authenticated-user-email"
JWT_HEADER = "cf-access-jwt-assertion"
JWT_COOKIE = "CF_Authorization"

ENV_TEAM_DOMAIN = "CF_ACCESS_TEAM_DOMAIN"
ENV_AUD = "CF_ACCESS_AUD"
ENV_DEV_USER = "QC_STUDIO_DEV_USER_EMAIL"

_SESSION_KEY = "auth_user_identity"


class IdentityError(RuntimeError):
    """Raised when identity verification is misconfigured (not when a user is unknown)."""


@dataclass(frozen=True)
class UserIdentity:
    email: str
    source: str  # "jwt" | "header" | "dev"


def normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def get_request_headers() -> dict[str, str]:
    """Request headers of the current session with lower-cased keys (``{}`` if unavailable)."""
    try:
        headers = st.context.headers
        return {str(k).lower(): str(v) for k, v in headers.items()}
    except Exception:
        return {}


def get_request_cookies() -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in st.context.cookies.items()}
    except Exception:
        return {}


def _team_base_url(team_domain: str) -> str:
    domain = team_domain.strip().rstrip("/")
    if not domain.startswith(("https://", "http://")):
        domain = f"https://{domain}"
    return domain


def jwt_mode_config() -> tuple[str, str] | None:
    """``(team_base_url, aud)`` when JWT verification is configured, else ``None``."""
    team = os.environ.get(ENV_TEAM_DOMAIN, "").strip()
    aud = os.environ.get(ENV_AUD, "").strip()
    if team and aud:
        return _team_base_url(team), aud
    if team or aud:
        raise IdentityError(f"Set both {ENV_TEAM_DOMAIN} and {ENV_AUD} to enable Cloudflare Access JWT verification (only one is set).")
    return None


@st.cache_resource(show_spinner=False)
def _jwks_client(certs_url: str):
    """One JWKS client per process; PyJWT caches the signing keys internally."""
    try:
        import jwt  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on env
        raise IdentityError("JWT verification is configured but PyJWT is not installed: pip install 'PyJWT[crypto]'") from exc
    return jwt.PyJWKClient(certs_url, cache_keys=True, lifespan=3600)


def verify_access_jwt(token: str, team_base_url: str, aud: str, jwks_client=None) -> str | None:
    """Return the verified ``email`` claim of a Cloudflare Access JWT, or ``None`` if invalid."""
    if not token:
        return None
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - depends on env
        raise IdentityError("JWT verification is configured but PyJWT is not installed: pip install 'PyJWT[crypto]'") from exc
    client = jwks_client or _jwks_client(f"{team_base_url}/cdn-cgi/access/certs")
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=aud,
            issuer=team_base_url,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    email = normalize_email(claims.get("email"))
    return email or None


def resolve_identity_from_request(headers: dict[str, str], cookies: dict[str, str] | None = None, jwks_client=None) -> UserIdentity | None:
    """Pure resolution logic (no session caching) — see module docstring for the order."""
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    cookies = cookies or {}

    jwt_cfg = jwt_mode_config()
    if jwt_cfg is not None:
        team_base_url, aud = jwt_cfg
        token = headers.get(JWT_HEADER) or cookies.get(JWT_COOKIE, "")
        email = verify_access_jwt(token, team_base_url, aud, jwks_client=jwks_client)
        return UserIdentity(email=email, source="jwt") if email else None

    email = normalize_email(headers.get(EMAIL_HEADER))
    if email:
        return UserIdentity(email=email, source="header")

    dev_email = normalize_email(os.environ.get(ENV_DEV_USER))
    if dev_email:
        return UserIdentity(email=dev_email, source="dev")
    return None


def get_current_user() -> UserIdentity | None:
    """Identity of the user behind the current Streamlit session (cached per session)."""
    cached = st.session_state.get(_SESSION_KEY)
    if isinstance(cached, UserIdentity):
        return cached
    identity = resolve_identity_from_request(get_request_headers(), get_request_cookies())
    if identity is not None:
        st.session_state[_SESSION_KEY] = identity
    return identity
