"""Salesforce fixed-origin PKCE exchange and refresh HTTP contracts, offline."""

import httpx
import pytest

from skriller.crm.oauth import SalesforceConfiguration, SalesforceOAuth, tokens
from skriller.crm.salesforce import SalesforceUnavailable

CONFIG = SalesforceConfiguration("client", "SECRET_CLIENT", "http://localhost:3000/callback")
DOCUMENT = {
    "access_token": "ACCESS_SENTINEL_123",
    "refresh_token": "REFRESH_SENTINEL_123",
    "token_type": "Bearer",
    "instance_url": "https://fixture.my.salesforce.com",
    "scope": "api refresh_token",
}


def test_fixed_exchange_and_refresh_form_contract():
    requests = []

    def handle(request):
        from urllib.parse import parse_qs

        requests.append(request)
        assert str(request.url) == "https://login.salesforce.com/services/oauth2/token"
        form = parse_qs(request.content.decode())
        assert form["client_secret"] == ["SECRET_CLIENT"]
        if form["grant_type"] == ["authorization_code"]:
            assert form["code_verifier"] == ["v" * 43]
            assert form["redirect_uri"] == [CONFIG.redirect_uri]
            return httpx.Response(200, json=DOCUMENT)
        assert form["refresh_token"] == [DOCUMENT["refresh_token"]]
        return httpx.Response(200, json={k: v for k, v in DOCUMENT.items() if k != "refresh_token"})

    provider = SalesforceOAuth(httpx.MockTransport(handle))
    assert (
        provider.exchange(CONFIG, "fixture-code", "v" * 43)["refresh_token"]
        == DOCUMENT["refresh_token"]
    )
    assert (
        provider.refresh(CONFIG, DOCUMENT["refresh_token"])["refresh_token"]
        == DOCUMENT["refresh_token"]
    )
    assert len(requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://evil.test"}),
        httpx.Response(400, json={"error_description": "SENTINEL_PRIVATE"}),
        httpx.Response(200, content=b'{"access_token":"one","access_token":"two"}'),
        httpx.Response(200, content=b"x" * 65537),
    ],
)
def test_denial_redirect_duplicate_key_and_large_response_redacted(response):
    with pytest.raises(SalesforceUnavailable) as exc:
        SalesforceOAuth(httpx.MockTransport(lambda request: response)).exchange(
            CONFIG, "fixture", "v" * 43
        )
    assert "SENTINEL" not in str(exc.value)


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "full api refresh_token"},
        {"instance_url": "http://localhost"},
        {"access_token": "private token with whitespace"},
        {"refresh_token": None},
    ],
)
def test_token_scope_origin_and_shape_are_strict(change):
    with pytest.raises(SalesforceUnavailable):
        tokens({**DOCUMENT, **change})


def test_sandbox_endpoint_and_reviewed_enhanced_domain_shapes():
    from skriller.crm.oauth import authorization_url
    from skriller.crm.salesforce import validate_instance

    config = SalesforceConfiguration(
        "client", "SECRET_CLIENT", "http://localhost:3000/callback", sandbox=True
    )
    assert authorization_url(config, "state", "v" * 43).startswith(
        "https://test.salesforce.com/services/oauth2/authorize?"
    )
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(
            200, json={**DOCUMENT, "instance_url": "https://fixture--dev.sandbox.my.salesforce.com"}
        )

    provider = SalesforceOAuth(httpx.MockTransport(handle))
    assert (
        provider.exchange(config, "code", "v" * 43)["instance_url"]
        == "https://fixture--dev.sandbox.my.salesforce.com"
    )
    assert seen == ["https://test.salesforce.com/services/oauth2/token"]
    assert validate_instance("https://fixture.develop.my.salesforce.com")
    with pytest.raises(SalesforceUnavailable):
        validate_instance("https://fixture.sandbox.my.salesforce.com.evil.test")


def test_upsert_401_is_distinguished_for_next_attempt_refresh():
    from uuid import uuid4

    from skriller.crm.salesforce import SalesforceAuthorizationExpired, map_lead, upsert_lead

    lead = map_lead(
        str(uuid4()),
        {
            "entity_id": str(uuid4()),
            "fit": "confirmed",
            "field.last_name": "Fixture",
            "field.company": "Company",
        },
        {"last_name": "LastName", "company": "Company"},
    )
    with pytest.raises(SalesforceAuthorizationExpired):
        upsert_lead(
            "https://fixture.my.salesforce.com",
            "fixture-access-token",
            lead,
            transport=httpx.MockTransport(lambda request: httpx.Response(401)),
        )
