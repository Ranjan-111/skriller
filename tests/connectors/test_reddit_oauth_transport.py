"""Reddit protocol deltas around the reused bounded OAuth transport."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from skriller.connectors.reddit_oauth import (
    RedditOAuth,
    RedditOAuthConfiguration,
    RedditOAuthUnavailable,
    authorization_url,
    tokens,
)

CONFIG = RedditOAuthConfiguration(
    "fixture-client",
    "PRIVATE_CLIENT",
    "http://localhost:3000/callback",
    "web:skriller-fixture:v0.1 (by /u/fixture)",
)
DOCUMENT = {
    "access_token": "REDDIT_ACCESS_SENTINEL_123",
    "refresh_token": "REDDIT_REFRESH_SENTINEL_123",
    "token_type": "Bearer",
    "scope": "read",
    "expires_in": 3600,
}


def test_read_only_confidential_exchange_and_nonrotating_refresh():
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://www.reddit.com/api/v1/access_token"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.headers["user-agent"] == CONFIG.user_agent
        form = parse_qs(request.content.decode())
        assert "client_secret" not in form and "code_verifier" not in form
        if form["grant_type"] == ["authorization_code"]:
            assert form["redirect_uri"] == [CONFIG.redirect_uri]
            return httpx.Response(200, json=DOCUMENT)
        assert form["refresh_token"] == [DOCUMENT["refresh_token"]]
        return httpx.Response(200, json={k: v for k, v in DOCUMENT.items() if k != "refresh_token"})

    provider = RedditOAuth(httpx.MockTransport(respond))
    assert provider.exchange(CONFIG, "fixture-code")["refresh_token"] == DOCUMENT["refresh_token"]
    assert (
        provider.refresh(CONFIG, DOCUMENT["refresh_token"])["refresh_token"]
        == DOCUMENT["refresh_token"]
    )
    assert len(calls) == 2
    url = urlsplit(authorization_url(CONFIG, "s" * 43))
    query = parse_qs(url.query)
    assert url.netloc == "www.reddit.com" and url.path == "/api/v1/authorize"
    assert query["scope"] == ["read"] and query["duration"] == ["permanent"]
    assert "code_challenge" not in query and "PRIVATE_CLIENT" not in str(query)


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "read submit"},
        {"scope": "*"},
        {"refresh_token": None},
        {"expires_in": True},
        {"expires_in": 86401},
        {"access_token": "a\nb"},
    ],
)
def test_invalid_receipt_never_authorizes_access(change):
    with pytest.raises(RedditOAuthUnavailable):
        tokens({**DOCUMENT, **change})


@pytest.mark.parametrize(
    "receipt",
    [
        httpx.Response(302, headers={"location": "https://evil.test"}),
        httpx.Response(429, text="PRIVATE_SENTINEL"),
        httpx.Response(200, content=b'{"scope":"read","scope":"submit"}'),
        httpx.Response(200, content=b"x" * 65537),
    ],
)
def test_redacted_failure_is_one_attempt_without_refresh_replay(receipt):
    calls = []

    def respond(request):
        calls.append(request)
        return receipt

    with pytest.raises(RedditOAuthUnavailable) as exc:
        RedditOAuth(httpx.MockTransport(respond)).refresh(CONFIG, DOCUMENT["refresh_token"])
    assert "PRIVATE" not in str(exc.value) and len(calls) == 1
