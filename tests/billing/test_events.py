import hmac
import json

import pytest

from skriller.billing.events import InvalidBillingEvent, verify_event

SECRET = b"synthetic-webhook-secret-only"
NOW = 1800000000


def stripe_doc(**changes):
    return {
        "id": "evt_fixture",
        "type": "customer.subscription.updated",
        "livemode": False,
        "data": {"object": {"object": "subscription", "id": "sub_fixture", "status": "active"}},
    } | changes


def signed(provider, doc, **kwargs):
    body = json.dumps(doc).encode() if isinstance(doc, dict) else doc
    message = str(NOW).encode() + b"." + body if provider == "stripe" else body
    signature = hmac.new(SECRET, message, "sha256").hexdigest()
    if provider == "stripe":
        signature = f"t={NOW},v1={signature}"
    return verify_event(provider, body, signature, secret=SECRET, now=NOW, **kwargs)


def test_stripe_returns_only_hint_and_stable_identity():
    hint = signed("stripe", stripe_doc())
    assert hint.subscription_id == "sub_fixture"
    assert hint.event_key == "evt_fixture"
    assert not hasattr(hint, "enabled") and not hasattr(hint, "workspace_id")
    assert hint == signed("stripe", stripe_doc())


@pytest.mark.parametrize(
    "doc",
    [
        stripe_doc(livemode=True),
        stripe_doc(livemode=0),
        stripe_doc(account="acct_unbound"),
        stripe_doc(id="other"),
        stripe_doc(data={"object": {"object": "payment_intent", "id": "sub_a"}}),
    ],
)
def test_stripe_rejects_wrong_mode_account_or_object(doc):
    with pytest.raises(InvalidBillingEvent):
        signed("stripe", doc)


@pytest.mark.parametrize("body", [b"[]", b"{", b'{"id":1,"id":2}', b'{"x":NaN}'])
def test_signed_malformed_documents_fail_closed(body):
    with pytest.raises(InvalidBillingEvent):
        signed("stripe", body)


@pytest.mark.parametrize(
    "signature", ["", "t=0,v1=" + "a" * 64, f"t={NOW},t={NOW},v1=x", f"t={NOW},v1=x"]
)
def test_forged_and_expired_signatures_rejected(signature):
    with pytest.raises(InvalidBillingEvent):
        verify_event("stripe", b"{}", signature, secret=SECRET, now=NOW)


def test_rotation_multiple_stripe_v1_signatures():
    body = json.dumps(stripe_doc()).encode()
    digest = hmac.new(SECRET, str(NOW).encode() + b"." + body, "sha256").hexdigest()
    hint = verify_event("stripe", body, f"t={NOW},v1=old,v1={digest}", secret=SECRET, now=NOW)
    assert hint.event_key == "evt_fixture"


def test_razorpay_signed_account_and_body_identity_not_unsigned_headers():
    doc = {
        "account_id": "acc_fixture",
        "event": "subscription.activated",
        "payload": {"subscription": {"entity": {"entity": "subscription", "id": "sub_fixture"}}},
    }
    hint = signed("razorpay", doc, account_id="acc_fixture")
    assert hint.event_key == "sha256:" + hint.payload_hash
    assert hint == signed("razorpay", doc, account_id="acc_fixture")
    for account in [None, "acc_other"]:
        with pytest.raises(InvalidBillingEvent):
            signed("razorpay", doc, account_id=account)


def test_irrelevant_events_do_not_request_reconciliation():
    assert signed("stripe", stripe_doc(type="checkout.session.completed")) is None


@pytest.mark.parametrize(
    "kind,amount_refunded,expected",
    [
        ("charge.refunded", 1000, "charge.refunded:full"),
        ("charge.refunded", 250, "charge.refunded:partial"),
        ("charge.dispute.created", 0, "billing.dispute.open"),
        ("charge.dispute.closed", 0, "billing.dispute.won"),
    ],
)
def test_stripe_payment_events_classify_only_with_provider_customer_and_subscription_link(
    kind, amount_refunded, expected
):
    obj = {
        "id": "ch_fixture" if kind.startswith("charge.refunded") else "dp_fixture",
        "object": "charge" if kind.startswith("charge.refunded") else "dispute",
        "customer": "cus_fixture",
        "subscription": "sub_fixture",
        "amount": 1000,
        "amount_refunded": amount_refunded,
        "status": "won",
    }
    hint = signed("stripe", stripe_doc(type=kind, data={"object": obj}))
    assert hint.subscription_id == "sub_fixture"
    assert hint.customer_id == "cus_fixture"
    assert hint.event_type == expected


def test_razorpay_refund_event_resolves_by_customer_when_subscription_is_omitted():
    doc = {
        "account_id": "acc_fixture",
        "event": "refund.processed",
        "payload": {
            "payment": {
                "entity": {
                    "entity": "payment",
                    "customer_id": "cust_fixture",
                    "amount": 1000,
                    "amount_refunded": 1000,
                }
            }
        },
    }
    hint = signed("razorpay", doc, account_id="acc_fixture")
    assert hint.subscription_id is None
    assert hint.customer_id == "cust_fixture"
    assert hint.event_type == "refund.processed:full"


@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("created", "open"),
        ("under_review", "open"),
        ("action_required", "open"),
        ("won", "won"),
        ("lost", "lost"),
        ("closed", "closed"),
    ],
)
def test_razorpay_dispute_keeps_only_verified_payment_reference(suffix, expected):
    doc = {
        "account_id": "acc_fixture",
        "event": "payment.dispute." + suffix,
        "payload": {
            "payment": {"entity": {"id": "pay_fixture", "email": "discard@example.com"}},
            "dispute": {"entity": {"entity": "dispute", "payment_id": "pay_fixture"}},
        },
    }
    hint = signed("razorpay", doc, account_id="acc_fixture")
    assert hint.reference_id == "pay_fixture" and hint.customer_id is None
    assert hint.subscription_id is None and hint.event_type == "billing.dispute." + expected
    doc["payload"]["payment"]["entity"]["id"] = "pay_other"
    with pytest.raises(InvalidBillingEvent):
        signed("razorpay", doc, account_id="acc_fixture")


def test_body_bounds_and_weak_missing_config():
    for body, secret in [(b"x" * (256 * 1024 + 1), SECRET), (b"{}", b"")]:
        with pytest.raises(InvalidBillingEvent):
            verify_event("razorpay", body, "a" * 64, secret=secret, now=NOW)


@pytest.mark.parametrize("refunded,expected", [(1000, "full"), (250, "partial")])
def test_razorpay_refund_without_customer_queues_payment_reference(refunded, expected):
    doc = {
        "account_id": "acc_fixture",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {"entity": "refund", "status": "processed", "payment_id": "pay_fixture"}
            },
            "payment": {
                "entity": {
                    "entity": "payment",
                    "id": "pay_fixture",
                    "amount": 1000,
                    "amount_refunded": refunded,
                }
            },
        },
    }
    hint = signed("razorpay", doc, account_id="acc_fixture")
    assert hint.reference_id == "pay_fixture" and hint.customer_id is None
    assert hint.event_type == "refund.processed:" + expected
    doc["payload"]["refund"]["entity"]["payment_id"] = "pay_other"
    with pytest.raises(InvalidBillingEvent):
        signed("razorpay", doc, account_id="acc_fixture")
