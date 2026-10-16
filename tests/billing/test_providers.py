from datetime import UTC, datetime, timedelta

import httpx
import pytest

from skriller.billing.providers import BillingProviderUnavailable, fetch_subscription, normalize


def stripe():
    return {
        "id": "sub_fixture",
        "object": "subscription",
        "customer": "cus_fixture",
        "status": "active",
        "livemode": False,
        "pause_collection": None,
        "items": {
            "has_more": False,
            "data": [
                {
                    "quantity": 1,
                    "price": {"id": "price_fixture"},
                    "current_period_end": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
                }
            ],
        },
        "latest_invoice": {
            "status": "paid",
            "customer": "cus_fixture",
            "parent": {"subscription_details": {"subscription": "sub_fixture"}},
        },
    }


def razorpay():
    return {
        "id": "sub_fixture",
        "entity": "subscription",
        "customer_id": "cust_fixture",
        "plan_id": "plan_fixture",
        "quantity": 1,
        "status": "active",
        "paid_count": 1,
        "current_start": int(datetime.now(UTC).timestamp()) - 100,
        "current_end": int((datetime.now(UTC) + timedelta(days=1)).timestamp()),
    }


@pytest.mark.parametrize(
    "provider,fixture,key,scope",
    [
        ("stripe", stripe, "sk_test_fixture_only", "self:test"),
        ("razorpay", razorpay, "rzp_test_fixture_only", "acc_fixture:test"),
    ],
)
def test_exact_read_only_provider_contract(provider, fixture, key, scope):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=fixture())

    current = fetch_subscription(
        {"provider": provider, "account_scope": scope, "subscription_id": "sub_fixture"},
        api_key=key,
        api_secret="fixture_secret_only",
        stripe_version="2025-06-30.basil",
        transport=httpx.MockTransport(respond),
    )
    assert current.paid is True and current.account_scope == scope
    assert len(seen) == 1 and seen[0].method == "GET"
    assert seen[0].url.host == ("api.stripe.com" if provider == "stripe" else "api.razorpay.com")
    assert seen[0].url.path == "/v1/subscriptions/sub_fixture"


@pytest.mark.parametrize(
    "change", ["unpaid", "wrong_customer", "wrong_subscription", "unexpanded", "paused_collection"]
)
def test_stripe_active_alone_never_means_paid(change):
    doc = stripe()
    if change == "unpaid":
        doc["latest_invoice"]["status"] = "open"
    if change == "wrong_customer":
        doc["latest_invoice"]["customer"] = "cus_other"
    if change == "wrong_subscription":
        doc["latest_invoice"]["parent"]["subscription_details"]["subscription"] = "sub_other"
    if change == "unexpanded":
        doc["latest_invoice"] = "in_fixture"
    if change == "paused_collection":
        doc["pause_collection"] = {"behavior": "void"}
    assert (
        normalize("stripe", doc, subscription_id="sub_fixture", account_scope="self:test").paid
        is False
    )


@pytest.mark.parametrize("mutate", ["live", "quantity", "pagination", "wrong_id"])
def test_stripe_unsupported_or_mismatched_contract_fails_closed(mutate):
    doc = stripe()
    if mutate == "live":
        doc["livemode"] = True
    if mutate == "quantity":
        doc["items"]["data"][0]["quantity"] = 2
    if mutate == "pagination":
        doc["items"]["has_more"] = True
    if mutate == "wrong_id":
        doc["id"] = "sub_other"
    with pytest.raises(BillingProviderUnavailable):
        normalize("stripe", doc, subscription_id="sub_fixture", account_scope="self:test")


def test_razorpay_mandate_without_paid_cycle_is_not_paid_access():
    doc = razorpay() | {"paid_count": 0}
    assert (
        normalize(
            "razorpay", doc, subscription_id="sub_fixture", account_scope="acc_fixture:test"
        ).paid
        is False
    )


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_errors_never_follow_redirects_or_retry(status):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(status, headers={"location": "http://127.0.0.1"})

    with pytest.raises(BillingProviderUnavailable):
        fetch_subscription(
            {"provider": "stripe", "account_scope": "self:test", "subscription_id": "sub_fixture"},
            api_key="sk_test_fixture_only",
            stripe_version="2025-06-30.basil",
            transport=httpx.MockTransport(respond),
        )
    assert len(seen) == 1


def test_wrong_key_mode_or_unpinned_version_never_connects():
    def forbidden(request):
        pytest.fail("Misconfigured client connected")

    for key, version in [
        ("sk_live_fixture_only", "2025-06-30.basil"),
        ("sk_test_fixture_only", None),
    ]:
        with pytest.raises(BillingProviderUnavailable):
            fetch_subscription(
                {
                    "provider": "stripe",
                    "account_scope": "self:test",
                    "subscription_id": "sub_fixture",
                },
                api_key=key,
                stripe_version=version,
                transport=httpx.MockTransport(forbidden),
            )
