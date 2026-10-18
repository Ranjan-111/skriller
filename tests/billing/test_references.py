import httpx
import pytest

from skriller.billing.providers import BillingProviderUnavailable, fetch_reference
from skriller.billing.runtime import ProviderConfiguration


def config(provider):
    return ProviderConfiguration(
        provider,
        "acct_fixture" if provider == "stripe" else "acc_fixture",
        False,
        b"synthetic-reference-secret",
        "sk_test_fixture_only" if provider == "stripe" else "rzp_test_fixture_only",
        api_secret="synthetic-secret-only",
        stripe_version="2025-06-30.basil",
    )


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_reference_fixed_host_auth_and_routing_only(provider):
    stripe = provider == "stripe"
    identifier = "ch_fixture" if stripe else "pay_fixture"
    customer = "cus_fixture" if stripe else "cust_fixture"

    def respond(request):
        assert request.method == "GET"
        assert request.url.host == ("api.stripe.com" if stripe else "api.razorpay.com")
        assert request.url.path == ("/v1/charges/" if stripe else "/v1/payments/") + identifier
        assert "authorization" in request.headers
        if stripe:
            assert request.headers["Stripe-Account"] == "acct_fixture"
        return httpx.Response(
            200,
            json={
                "id": identifier,
                "object" if stripe else "entity": "charge" if stripe else "payment",
                "customer" if stripe else "customer_id": customer,
                "livemode": False,
                "email": "discard@example.com",
            },
        )

    result = fetch_reference(config(provider), identifier, transport=httpx.MockTransport(respond))
    assert result.customer_id == customer and result.subscription_id is None
    assert not hasattr(result, "email")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(429),
        httpx.Response(200, content=b"x" * (256 * 1024 + 1)),
        httpx.Response(
            200, json={"id": "ch_other", "object": "charge", "customer": "cus_a", "livemode": False}
        ),
        httpx.Response(
            200,
            json={"id": "ch_fixture", "object": "charge", "customer": "cus_a", "livemode": True},
        ),
        httpx.Response(
            200, json={"id": "ch_fixture", "object": "charge", "customer": None, "livemode": False}
        ),
    ],
)
def test_reference_redirect_throttle_size_and_identity_fail_closed(response):
    calls = []

    def respond(request):
        calls.append(request)
        return response

    with pytest.raises(BillingProviderUnavailable):
        fetch_reference(config("stripe"), "ch_fixture", transport=httpx.MockTransport(respond))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "identifier", ["../customers/cus_x", "https://evil.example", "pay_wrong", "ch_x?a=b"]
)
def test_reference_identifiers_never_control_url(identifier):
    with pytest.raises(BillingProviderUnavailable):
        fetch_reference(
            config("stripe"),
            identifier,
            transport=httpx.MockTransport(lambda _: pytest.fail("Unsafe reference dispatched")),
        )
