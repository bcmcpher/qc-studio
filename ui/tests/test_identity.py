"""Tests for utils.identity (Cloudflare Access user identity resolution)."""

import time
from types import SimpleNamespace

import pytest

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

from utils import identity  # noqa: E402
from utils.identity import IdentityError, UserIdentity, resolve_identity_from_request  # noqa: E402

TEAM = "https://myteam.cloudflareaccess.com"
AUD = "test-aud-tag"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (identity.ENV_TEAM_DOMAIN, identity.ENV_AUD, identity.ENV_DEV_USER):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(rsa_key):
    """Stand-in for PyJWKClient that always returns our test public key."""
    return SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=rsa_key.public_key()))


@pytest.fixture
def jwt_mode(monkeypatch):
    monkeypatch.setenv(identity.ENV_TEAM_DOMAIN, "myteam.cloudflareaccess.com")
    monkeypatch.setenv(identity.ENV_AUD, AUD)


def _token(key, **overrides):
    now = int(time.time())
    claims = {"email": "Alice@McGill.ca", "aud": [AUD], "iss": TEAM, "iat": now, "exp": now + 600}
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


class TestHeaderMode:
    def test_email_header_is_normalized(self):
        ident = resolve_identity_from_request({"Cf-Access-Authenticated-User-Email": "  Alice@McGill.CA "})
        assert ident == UserIdentity(email="alice@mcgill.ca", source="header")

    def test_missing_header_returns_none(self):
        assert resolve_identity_from_request({"host": "x"}) is None

    def test_dev_env_fallback(self, monkeypatch):
        monkeypatch.setenv(identity.ENV_DEV_USER, "Dev@Example.org")
        assert resolve_identity_from_request({}) == UserIdentity(email="dev@example.org", source="dev")

    def test_header_wins_over_dev_env(self, monkeypatch):
        monkeypatch.setenv(identity.ENV_DEV_USER, "dev@example.org")
        ident = resolve_identity_from_request({identity.EMAIL_HEADER: "bob@mcgill.ca"})
        assert ident.email == "bob@mcgill.ca"


class TestJwtMode:
    def test_valid_jwt_header(self, jwt_mode, rsa_key, jwks):
        ident = resolve_identity_from_request({identity.JWT_HEADER: _token(rsa_key)}, jwks_client=jwks)
        assert ident == UserIdentity(email="alice@mcgill.ca", source="jwt")

    def test_valid_jwt_cookie(self, jwt_mode, rsa_key, jwks):
        ident = resolve_identity_from_request({}, {identity.JWT_COOKIE: _token(rsa_key)}, jwks_client=jwks)
        assert ident.email == "alice@mcgill.ca"

    def test_plain_header_not_trusted_in_jwt_mode(self, jwt_mode, jwks, monkeypatch):
        monkeypatch.setenv(identity.ENV_DEV_USER, "dev@example.org")
        headers = {identity.EMAIL_HEADER: "mallory@evil.com"}
        assert resolve_identity_from_request(headers, jwks_client=jwks) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"aud": ["other-app"]},
            {"iss": "https://evil.cloudflareaccess.com"},
            {"exp": int(time.time()) - 10},
        ],
    )
    def test_invalid_claims_rejected(self, jwt_mode, rsa_key, jwks, overrides):
        token = _token(rsa_key, **overrides)
        assert resolve_identity_from_request({identity.JWT_HEADER: token}, jwks_client=jwks) is None

    def test_wrong_signing_key_rejected(self, jwt_mode, jwks):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _token(other_key)
        assert resolve_identity_from_request({identity.JWT_HEADER: token}, jwks_client=jwks) is None

    def test_partial_config_is_an_error(self, monkeypatch):
        monkeypatch.setenv(identity.ENV_AUD, AUD)
        with pytest.raises(IdentityError):
            resolve_identity_from_request({identity.EMAIL_HEADER: "alice@mcgill.ca"})
