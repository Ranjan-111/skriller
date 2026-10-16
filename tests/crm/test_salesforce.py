from uuid import uuid4

import httpx
import pytest

from skriller.crm.salesforce import SalesforceUnavailable, map_lead, upsert_lead

WORKSPACE, ENTITY = str(uuid4()), str(uuid4())
MAP = {"last_name": "LastName", "company": "Company", "work_email": "Email"}


def record(**changes):
    return {
        "entity_id": ENTITY,
        "fit": "near_match",
        "field.last_name": "東京",
        "field.company": "Fixture Ltd",
        "field.work_email": None,
    } | changes


def test_retry_identity_preserves_near_match_and_missing_contact():
    a = map_lead(WORKSPACE, record(), MAP)
    assert a == map_lead(WORKSPACE, record(), MAP)
    assert a.fields == {
        "LastName": "東京",
        "Company": "Fixture Ltd",
        "Skriller_Fit__c": "near_match",
    }
    assert map_lead(str(uuid4()), record(), MAP).external_id != a.external_id
    assert "Status" not in a.fields and "Email" not in a.fields


@pytest.mark.parametrize(
    "mapping",
    [
        {"last_name": "LastName"},
        MAP | {"fit": "Status"},
        {"last_name": "LastName", "company": "Company", "name": "LastName"},
        {"last_name": "LastName", "company": "Company", "private_email": "Email"},
        {"last_name": "LastName", "company": "Company", "work_email": "Title"},
    ],
)
def test_unsupported_or_ambiguous_mapping_rejected(mapping):
    with pytest.raises(ValueError):
        map_lead(WORKSPACE, record(), mapping)


@pytest.mark.parametrize(
    "changes",
    [
        {"fit": "excluded"},
        {"field.last_name": None},
        {"field.company": ["a", "b"]},
        {"field.last_name": "x" * 81},
    ],
)
def test_no_invented_or_truncated_required_values(changes):
    with pytest.raises(ValueError):
        map_lead(WORKSPACE, record(**changes), MAP)


def test_real_http_contract_retries_same_upsert_identity_without_duplicate_create():
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(201 if len(requests) == 1 else 204)

    transport = httpx.MockTransport(receive)
    lead = map_lead(WORKSPACE, record(), MAP)
    assert (
        upsert_lead(
            "https://fixture.my.salesforce.com", "fixture-token-only", lead, transport=transport
        )
        == "created"
    )
    assert (
        upsert_lead(
            "https://fixture.my.salesforce.com", "fixture-token-only", lead, transport=transport
        )
        == "updated"
    )
    assert requests[0].url == requests[1].url
    assert requests[0].method == "PATCH"
    assert requests[0].content == requests[1].content


@pytest.mark.parametrize(
    "origin",
    [
        "http://fixture.my.salesforce.com",
        "https://127.0.0.1",
        "https://fixture.my.salesforce.com.evil.test",
        "https://fixture.my.salesforce.com/redirect",
        "https://user@fixture.my.salesforce.com",
    ],
)
def test_non_salesforce_origin_never_sends_credentials(origin):
    def forbidden(request):
        pytest.fail("Unexpected network operation")

    with pytest.raises(SalesforceUnavailable):
        upsert_lead(
            origin,
            "fixture-token-only",
            map_lead(WORKSPACE, record(), MAP),
            transport=httpx.MockTransport(forbidden),
        )


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
def test_redirects_and_remote_failure_are_not_followed_or_retried(status):
    seen = []

    def receive(request):
        seen.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"})

    with pytest.raises(SalesforceUnavailable):
        upsert_lead(
            "https://fixture.my.salesforce.com",
            "fixture-token-only",
            map_lead(WORKSPACE, record(), MAP),
            transport=httpx.MockTransport(receive),
        )
    assert len(seen) == 1
