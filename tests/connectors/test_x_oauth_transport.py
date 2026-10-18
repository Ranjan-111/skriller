"""Offline X OAuth native transport and read-scope bounds."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from skriller.connectors.x_oauth import (
    SCOPES,
    XOAuth,
    XOAuthConfiguration,
    XOAuthUnavailable,
    authorization_url,
    tokens,
)

CONFIG = XOAuthConfiguration("fixture-client", "SECRET_CLIENT", "http://localhost:3000/callback")
DOCUMENT = {
    "access_token": "X_ACCESS_SENTINEL_123",
    "refresh_token": "X_REFRESH_SENTINEL_123",
    "token_type": "Bearer",
    "scope": SCOPES,
    "expires_in": 7200,
}


def test_fixed_endpoint_confidential_auth_pkce_and_refresh():
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://api.x.com/2/oauth2/token"
        assert request.headers["authorization"].startswith("Basic ")
        form = parse_qs(request.content.decode())
        assert "client_secret" not in form
        if form["grant_type"] == ["authorization_code"]:
            assert form["code_verifier"] == ["v" * 43]
            assert form["redirect_uri"] == [CONFIG.redirect_uri]
        else:
            assert form["refresh_token"] == [DOCUMENT["refresh_token"]]
        return httpx.Response(200, json=DOCUMENT)

    provider = XOAuth(httpx.MockTransport(respond))
    provider.exchange(CONFIG, "fixture", "v" * 43)
    provider.refresh(CONFIG, DOCUMENT["refresh_token"])
    assert len(calls) == 2
    query = parse_qs(urlsplit(authorization_url(CONFIG, "s" * 43, "v" * 43)).query)
    assert query["scope"] == [SCOPES] and query["code_challenge_method"] == ["S256"]
    assert "SECRET_CLIENT" not in str(query) and query["code_challenge"] != ["v" * 43]


@pytest.mark.parametrize(
    "change",
    [
        {"scope": SCOPES + " tweet.write"},
        {"scope": "tweet.read users.read"},
        {"refresh_token": None},
        {"expires_in": True},
        {"expires_in": 86401},
        {"access_token": "token with whitespace"},
    ],
)
def test_invalid_scope_lifetime_or_rotating_refresh_receipt_fails(change):
    with pytest.raises(XOAuthUnavailable):
        tokens({**DOCUMENT, **change})


@pytest.mark.parametrize(
    "receipt",
    [
        httpx.Response(302, headers={"location": "https://evil.test"}),
        httpx.Response(429, text="SENTINEL_PRIVATE"),
        httpx.Response(200, content=b'{"access_token":"one","access_token":"two"}'),
        httpx.Response(200, content=b"x" * 65537),
    ],
)
def test_native_errors_and_unbounded_receipts_are_redacted(receipt):
    with pytest.raises(XOAuthUnavailable) as exc:
        XOAuth(httpx.MockTransport(lambda request: receipt)).exchange(CONFIG, "fixture", "v" * 43)
    assert "SENTINEL" not in str(exc.value)
