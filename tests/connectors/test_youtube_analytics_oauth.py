"""Exercise actual fixed Google request builder with an offline HTTP transport."""

from urllib.parse import parse_qs

import httpx
import pytest

from skriller.analytics.google import (
    SCOPES,
    AnalyticsUnavailable,
    GoogleAnalyticsOAuth,
    OAuthConfiguration,
)


def configuration():
    return OAuthConfiguration("client", "CLIENT_SECRET", "http://localhost:3000/callback")


def test_actual_google_exchange_uses_pkce_read_scopes_and_authenticated_owner_lookup(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            assert request.url == "https://oauth2.googleapis.com/token"
            form = parse_qs(request.content.decode())
            assert form["code_verifier"] == ["v" * 64]
            assert form["client_secret"] == ["CLIENT_SECRET"]
            assert "CLIENT_SECRET" not in str(request.url)
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "access_token": "ACCESS",
                    "refresh_token": "REFRESH",
                    "expires_in": 3600,
                    "scope": " ".join(SCOPES),
                },
            )
        assert request.headers["Authorization"] == "Bearer ACCESS"
        assert request.url.params["mine"] == "true"
        assert request.url.params["part"] == "id"
        return httpx.Response(200, json={"items": [{"id": "UC" + "x" * 22}]})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    tokens, channel = GoogleAnalyticsOAuth().exchange(configuration(), "code", "v" * 64)
    assert tokens["access_token"] == "ACCESS" and channel == "UC" + "x" * 22
    assert len(calls) == 2


@pytest.mark.parametrize(
    "kind",
    [
        "missing_scope",
        "write_scope",
        "bad_expiry",
        "header_injection",
        "redirect",
        "oversize",
        "foreign_channel",
    ],
)
def test_invalid_google_responses_fail_closed_without_leaking_tokens(monkeypatch, kind):
    calls = []

    def handle(request):
        calls.append(request)
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.invalid/ACCESS"})
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 65537)
        if len(calls) > 1:
            return httpx.Response(200, json={"items": [{"id": "not-an-owner-channel"}]})
        tokens = {
            "token_type": "Bearer",
            "access_token": "ACCESS",
            "expires_in": 3600,
            "scope": " ".join(SCOPES),
        }
        if kind == "missing_scope":
            tokens["scope"] = SCOPES[0]
        if kind == "write_scope":
            tokens["scope"] += " https://www.googleapis.com/auth/youtube"
        if kind == "bad_expiry":
            tokens["expires_in"] = True
        if kind == "header_injection":
            tokens["access_token"] = "ACCESS\r\nInjected: yes"
        return httpx.Response(200, json=tokens)

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    with pytest.raises(AnalyticsUnavailable) as error:
        GoogleAnalyticsOAuth().exchange(configuration(), "code", "v" * 64)
    assert "ACCESS" not in str(error.value)
    assert len(calls) == (2 if kind == "foreign_channel" else 1)


def test_google_refresh_preserves_original_scope_and_refresh_token_when_omitted(monkeypatch):
    def handle(request):
        assert request.url == "https://oauth2.googleapis.com/token"
        assert parse_qs(request.content.decode())["grant_type"] == ["refresh_token"]
        return httpx.Response(
            200, json={"token_type": "Bearer", "access_token": "NEW", "expires_in": 3600}
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    result = GoogleAnalyticsOAuth().refresh(configuration(), "REFRESH")
    assert result["refresh_token"] == "REFRESH" and result["access_token"] == "NEW"


def test_actual_report_request_pins_owner_and_types_403_quota_without_retry(monkeypatch):
    from datetime import date

    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.host == "youtubeanalytics.googleapis.com"
        assert request.url.params["ids"] == "channel==UC" + "a" * 22
        assert request.url.params["metrics"] == "views"
        assert request.url.params["maxResults"] == "31"
        assert request.headers["Authorization"] == "Bearer ACCESS"
        assert "ACCESS" not in str(request.url)
        return httpx.Response(
            403, json={"error": {"message": "SENTINEL", "errors": [{"reason": "quotaExceeded"}]}}
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    with pytest.raises(AnalyticsUnavailable) as error:
        GoogleAnalyticsOAuth().report(
            "ACCESS", "UC" + "a" * 22, date(2026, 1, 1), date(2026, 1, 2), ("views",)
        )
    assert error.value.code == "analytics_quota_exhausted" and "SENTINEL" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "uri,production",
    [
        ("http://remote.example/cb", False),
        ("http://localhost/cb", True),
        ("https://example.org/cb?secret=x", False),
        ("https://user:pass@example.org/cb", False),
    ],
)
def test_oauth_redirect_is_fixed_secure_and_has_no_embedded_secrets(uri, production):
    with pytest.raises(AnalyticsUnavailable):
        OAuthConfiguration("client", "secret", uri, production=production)
