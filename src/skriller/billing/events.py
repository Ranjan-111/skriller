"""Verify bounded raw provider events before extracting reconciliation hints.

These hints are deliberately not entitlement commands. Provider state must be
retrieved for a server-bound subscription before access changes. In particular,
event creation timestamps are not subscription versions.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Provider = Literal["stripe", "razorpay"]
MAX_BODY = 256 * 1024


class InvalidBillingEvent(ValueError):
    def __init__(self):
        super().__init__("Billing event unavailable or invalid")


@dataclass(frozen=True)
class ReconcileHint:
    provider: Provider
    event_key: str
    payload_hash: str
    subscription_id: str | None
    event_type: str
    customer_id: str | None = None
    reference_id: str | None = None
    checkout_id: str | None = None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidBillingEvent()
        result[key] = value
    return result


def _document(body: bytes):
    try:
        doc = json.loads(
            body,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(InvalidBillingEvent()),
        )
        if not isinstance(doc, dict):
            raise InvalidBillingEvent()
        return doc
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidBillingEvent() from None


def _identifier(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"[A-Za-z0-9_]{1,180}", value):
        raise InvalidBillingEvent()
    return value


def verify_event(
    provider: Provider,
    body: bytes,
    signature: str,
    *,
    secret: bytes,
    now: int,
    live_mode: bool = False,
    account_id: str | None = None,
) -> ReconcileHint | None:
    """Return a verified subscription hint, or None for an irrelevant event.

    Razorpay's event-id header is unsigned; derive identity from signed bytes
    instead. Its signature has no delivery timestamp: durable deduplication and
    current-state reconciliation remain mandatory even after validation.
    """
    if (
        provider not in {"stripe", "razorpay"}
        or not isinstance(body, bytes)
        or not 1 <= len(body) <= MAX_BODY
        or len(secret) < 16
        or not isinstance(signature, str)
        or len(signature) > 4096
        or type(now) is not int
        or type(live_mode) is not bool
    ):
        raise InvalidBillingEvent()
    if provider == "stripe":
        parts = signature.split(",")
        timestamps = [p[2:] for p in parts if p.startswith("t=")]
        signatures = [p[3:] for p in parts if p.startswith("v1=")]
        if len(timestamps) != 1 or not re.fullmatch(r"[0-9]{1,12}", timestamps[0]):
            raise InvalidBillingEvent()
        if abs(now - int(timestamps[0])) > 300:
            raise InvalidBillingEvent()
        expected = hmac.new(secret, timestamps[0].encode() + b"." + body, "sha256").hexdigest()
        if not any(
            re.fullmatch(r"[0-9a-f]{64}", candidate) and hmac.compare_digest(expected, candidate)
            for candidate in signatures
        ):
            raise InvalidBillingEvent()
    else:
        expected = hmac.new(secret, body, "sha256").hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(
            expected, signature
        ):
            raise InvalidBillingEvent()
    doc = _document(body)
    digest = hashlib.sha256(body).hexdigest()
    try:
        customer = reference = checkout = None
        if provider == "stripe":
            # Separate signing secrets/configuration must be used for test/live.
            if type(doc.get("livemode")) is not bool or doc["livemode"] != live_mode:
                raise InvalidBillingEvent()
            if doc.get("account") != account_id:
                raise InvalidBillingEvent()
            event_key = _identifier(doc["id"], "evt_")
            kind = doc["type"]
            if kind in {
                "customer.subscription.created",
                "customer.subscription.updated",
                "customer.subscription.deleted",
            }:
                obj = doc["data"]["object"]
                if obj["object"] != "subscription":
                    raise InvalidBillingEvent()
                subscription = _identifier(obj["id"], "sub_")
                checkout = obj.get("metadata", {}).get("skriller_checkout_intent")
                if checkout is not None:
                    if not isinstance(checkout, str):
                        raise InvalidBillingEvent()
                    checkout = str(UUID(checkout))
                    customer = _identifier(obj.get("customer"), "cus_")
            elif kind in {
                "charge.refunded",
                "charge.dispute.created",
                "charge.dispute.closed",
                "charge.dispute.funds_reinstated",
                "charge.dispute.funds_withdrawn",
            }:
                obj = doc["data"]["object"]
                if not isinstance(obj, dict) or obj.get("object") != (
                    "charge" if kind == "charge.refunded" else "dispute"
                ):
                    raise InvalidBillingEvent()
                # Resolve only by an explicit subscription ID or provider
                # customer ID. Never infer from email or arbitrary metadata.
                subscription_value = obj.get("subscription")
                invoice = obj.get("invoice")
                if isinstance(invoice, dict):
                    subscription_value = invoice.get("subscription")
                charge = obj.get("charge")
                if isinstance(charge, dict):
                    charge_invoice = charge.get("invoice")
                    if isinstance(charge_invoice, dict):
                        subscription_value = charge_invoice.get("subscription")
                    subscription_value = charge.get("subscription", subscription_value)
                if isinstance(subscription_value, dict):
                    subscription_value = subscription_value.get("id")
                subscription = (
                    _identifier(subscription_value, "sub_")
                    if subscription_value is not None
                    else None
                )
                customer_value = obj.get("customer")
                if customer_value is None and isinstance(charge, dict):
                    customer_value = charge.get("customer")
                if isinstance(customer_value, dict):
                    customer_value = customer_value.get("id")
                customer = (
                    _identifier(customer_value, "cus_") if customer_value is not None else None
                )
                if subscription is None and customer is None:
                    reference = _identifier(
                        obj.get("id") if kind == "charge.refunded" else charge,
                        "ch_",
                    )
                if kind == "charge.refunded":
                    amount, refunded = obj.get("amount"), obj.get("amount_refunded")
                    if (
                        type(amount) is not int
                        or type(refunded) is not int
                        or amount <= 0
                        or not 0 <= refunded <= amount
                    ):
                        raise InvalidBillingEvent()
                    kind += ":full" if refunded == amount else ":partial"
                elif kind == "charge.dispute.created" or kind == "charge.dispute.funds_withdrawn":
                    kind = "billing.dispute.open"
                elif kind == "charge.dispute.funds_reinstated":
                    kind = "billing.dispute.won"
                else:
                    status = obj.get("status")
                    if status not in {"won", "lost", "warning_closed"}:
                        raise InvalidBillingEvent()
                    kind = "billing.dispute.won" if status == "won" else "billing.dispute.lost"
            else:
                return None
        else:
            # Mode is selected by endpoint secret, never a client/header claim.
            if not account_id or doc["account_id"] != account_id:
                raise InvalidBillingEvent()
            kind = doc["event"]
            if kind in {
                "subscription.authenticated",
                "subscription.activated",
                "subscription.charged",
                "subscription.completed",
                "subscription.pending",
                "subscription.halted",
                "subscription.cancelled",
                "subscription.paused",
                "subscription.resumed",
            }:
                obj = doc["payload"]["subscription"]["entity"]
                if obj["entity"] != "subscription":
                    raise InvalidBillingEvent()
                subscription = _identifier(obj["id"], "sub_")
                checkout = (obj.get("notes") or {}).get("skriller_checkout_intent")
                if checkout is not None:
                    if not isinstance(checkout, str):
                        raise InvalidBillingEvent()
                    checkout = str(UUID(checkout))
                    customer = _identifier(obj.get("customer_id"), "cust_")
                payment = doc.get("payload", {}).get("payment", {}).get("entity")
                if isinstance(payment, dict) and payment.get("entity") == "payment":
                    amount, refunded = payment.get("amount"), payment.get("amount_refunded", 0)
                    if (
                        type(amount) is int
                        and type(refunded) is int
                        and amount > 0
                        and 0 <= refunded <= amount
                        and refunded > 0
                    ):
                        kind += ".full_refund" if refunded == amount else ".partial_refund"
            elif kind in {
                "payment.dispute.created",
                "payment.dispute.won",
                "payment.dispute.lost",
                "payment.dispute.closed",
                "payment.dispute.under_review",
                "payment.dispute.action_required",
            }:
                obj = doc["payload"]["dispute"]["entity"]
                if obj.get("entity") != "dispute":
                    raise InvalidBillingEvent()
                reference = _identifier(obj.get("payment_id"), "pay_")
                payment = doc["payload"].get("payment", {}).get("entity")
                if isinstance(payment, dict) and payment.get("id") != reference:
                    raise InvalidBillingEvent()
                subscription = None
                if kind.endswith(".won"):
                    kind = "billing.dispute.won"
                elif kind.endswith(".lost"):
                    kind = "billing.dispute.lost"
                elif kind.endswith(".closed"):
                    kind = "billing.dispute.closed"
                else:
                    kind = "billing.dispute.open"
            elif kind == "refund.processed":
                payload = doc.get("payload", {})
                payment = payload.get("payment", {}).get("entity")
                subscription_entity = payload.get("subscription", {}).get("entity")
                if not isinstance(payment, dict) or payment.get("entity") != "payment":
                    return None
                subscription_value = (
                    subscription_entity.get("id")
                    if isinstance(subscription_entity, dict)
                    and subscription_entity.get("entity") == "subscription"
                    else None
                )
                subscription = (
                    _identifier(subscription_value, "sub_")
                    if subscription_value is not None
                    else None
                )
                customer_value = payment.get("customer_id")
                customer = (
                    _identifier(customer_value, "cust_") if customer_value is not None else None
                )
                if subscription is None and customer is None:
                    reference = _identifier(payment.get("id"), "pay_")
                refund = payload.get("refund", {}).get("entity")
                if refund is not None and (
                    not isinstance(refund, dict)
                    or refund.get("entity") != "refund"
                    or refund.get("status") != "processed"
                    or refund.get("payment_id") != payment.get("id")
                ):
                    raise InvalidBillingEvent()
                amount, refunded = payment.get("amount"), payment.get("amount_refunded")
                if (
                    type(amount) is not int
                    or type(refunded) is not int
                    or amount <= 0
                    or not 0 <= refunded <= amount
                ):
                    raise InvalidBillingEvent()
                kind += ":full" if refunded == amount else ":partial"
            else:
                return None
            event_key = "sha256:" + digest
        return ReconcileHint(
            provider, event_key, digest, subscription, kind, customer, reference, checkout
        )
    except (KeyError, TypeError, AttributeError, ValueError):
        raise InvalidBillingEvent() from None
