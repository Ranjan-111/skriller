"""Bounded read-only provider clients; no checkout, charge or cancel operations."""

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from skriller.billing.events import InvalidBillingEvent, _document
from skriller.billing.reconcile import CurrentSubscription


class BillingProviderUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Authoritative billing state unavailable")


@dataclass(frozen=True)
class PaymentReference:
    customer_id: str | None
    subscription_id: str | None = None

    def __post_init__(self):
        if (
            self.customer_id is None
            and self.subscription_id is None
            or self.customer_id is not None
            and (
                not isinstance(self.customer_id, str)
                or not re.fullmatch(r"(?:cus|cust)_[A-Za-z0-9_]{1,180}", self.customer_id)
            )
            or self.subscription_id is not None
            and (
                not isinstance(self.subscription_id, str)
                or not re.fullmatch(r"sub_[A-Za-z0-9_]{1,180}", self.subscription_id)
            )
        ):
            raise BillingProviderUnavailable()


def fetch_reference(config, reference_id, *, transport=None):
    """Fixed-origin GET; discard payment details after extracting routing IDs."""
    config.__post_init__()
    stripe = config.provider == "stripe"
    prefix = "ch_" if stripe else "pay_"
    if not isinstance(reference_id, str) or not re.fullmatch(
        prefix + r"[A-Za-z0-9_]{1,180}", reference_id
    ):
        raise BillingProviderUnavailable()
    headers, auth = {}, None
    if stripe:
        headers = {
            "Authorization": "Bearer " + config.api_key,
            "Stripe-Version": config.stripe_version,
        }
        if config.account_id:
            headers["Stripe-Account"] = config.account_id
        url = "https://api.stripe.com/v1/charges/" + reference_id
    else:
        auth = httpx.BasicAuth(config.api_key, config.api_secret)
        url = "https://api.razorpay.com/v1/payments/" + reference_id
    deadline = time.monotonic() + 10
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(5, connect=3),
                transport=transport,
                trust_env=False,
                follow_redirects=False,
            ) as client,
            client.stream("GET", url, headers=headers, auth=auth) as response,
        ):
            if response.status_code != 200:
                raise BillingProviderUnavailable()
            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(body) + len(chunk) > 256 * 1024:
                    raise BillingProviderUnavailable()
                body.extend(chunk)
            doc = _document(bytes(body))
        if doc.get("id") != reference_id or doc.get("object" if stripe else "entity") != (
            "charge" if stripe else "payment"
        ):
            raise BillingProviderUnavailable()
        if stripe and (
            type(doc.get("livemode")) is not bool or doc["livemode"] != config.live_mode
        ):
            raise BillingProviderUnavailable()
        customer = doc.get("customer" if stripe else "customer_id")
        subscription = doc.get("subscription_id") if not stripe else None
        if customer is not None and (
            not isinstance(customer, str)
            or not re.fullmatch(("cus_" if stripe else "cust_") + r"[A-Za-z0-9_]{1,180}", customer)
        ):
            raise BillingProviderUnavailable()
        return PaymentReference(customer, subscription)
    except (httpx.HTTPError, InvalidBillingEvent):
        raise BillingProviderUnavailable() from None


def _timestamp(value):
    if value is None:
        return None
    if type(value) is not int or not 0 < value < 32503680000:
        raise BillingProviderUnavailable()
    return datetime.fromtimestamp(value, UTC)


def normalize(provider, doc, *, subscription_id, account_scope):
    """Parse only the reviewed one-item subscription contract, fail closed."""
    try:
        if doc["id"] != subscription_id:
            raise BillingProviderUnavailable()
        if provider == "stripe":
            if (
                doc["object"] != "subscription"
                or type(doc["livemode"]) is not bool
                or doc["livemode"] != account_scope.endswith(":live")
                or doc["items"]["has_more"] is not False
                or len(doc["items"]["data"]) != 1
            ):
                raise BillingProviderUnavailable()
            item = doc["items"]["data"][0]
            if type(item["quantity"]) is not int or item["quantity"] != 1:
                raise BillingProviderUnavailable()
            customer, plan = doc["customer"], item["price"]["id"]
            end = _timestamp(item["current_period_end"])
            start = _timestamp(item.get("current_period_start"))
            invoice = doc.get("latest_invoice")
            paid = False
            if isinstance(invoice, dict):
                parent = invoice.get("parent") or {}
                invoice_subscription = invoice.get("subscription") or (
                    parent.get("subscription_details") or {}
                ).get("subscription")
                paid = (
                    invoice.get("status") == "paid"
                    and invoice.get("customer") == customer
                    and invoice_subscription == subscription_id
                )
            # An active send_invoice subscription can still be unpaid; a paused
            # collection subscription can also remain active in provider state.
            paid = paid and doc.get("pause_collection") is None
        elif provider == "razorpay":
            if (
                doc["entity"] != "subscription"
                or type(doc["quantity"]) is not int
                or doc["quantity"] != 1
            ):
                raise BillingProviderUnavailable()
            customer, plan = doc["customer_id"], doc["plan_id"]
            end = _timestamp(doc["current_end"])
            start = _timestamp(doc["current_start"])
            paid = (
                type(doc["paid_count"]) is int
                and doc["paid_count"] > 0
                and start is not None
                and start <= datetime.now(UTC)
                and end is not None
                and end > start
            )
        else:
            raise BillingProviderUnavailable()
        if (
            not isinstance(customer, str)
            or not re.fullmatch(
                (r"cus_" if provider == "stripe" else r"cust_") + r"[A-Za-z0-9_]{1,180}", customer
            )
            or not isinstance(plan, str)
            or not re.fullmatch(r"(?:plan|price)_[A-Za-z0-9_]{1,180}", plan)
            or not isinstance(doc["status"], str)
        ):
            raise BillingProviderUnavailable()
        return CurrentSubscription(
            subscription_id, account_scope, customer, plan, doc["status"], paid, end, start
        )
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise BillingProviderUnavailable() from None


def fetch_subscription(
    binding,
    *,
    api_key: str,
    api_secret: str | None = None,
    stripe_version: str | None = None,
    transport: httpx.BaseTransport | None = None,
):
    """Server-owned binding controls fixed origin/account/mode and subscription.

    Stripe API version is an explicit deployment setting, not silently upgraded.
    No credentials or body are retained in exceptions. Provider retries belong
    to the durable worker, never this bounded GET operation.
    """
    provider, scope, subscription = (
        binding[k] for k in ("provider", "account_scope", "subscription_id")
    )
    if (
        not re.fullmatch(r"sub_[A-Za-z0-9_]{1,180}", subscription)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,180}:(test|live)", scope)
        or not isinstance(api_key, str)
        or not 16 <= len(api_key) <= 8192
        or not api_key.isascii()
        or any(c.isspace() for c in api_key)
    ):
        raise BillingProviderUnavailable()
    mode = scope.rsplit(":", 1)[1]
    headers, params, auth = {}, {}, None
    if provider == "stripe":
        if (
            not api_key.startswith("sk_" + mode + "_")
            or not stripe_version
            or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}\.[a-z]+", stripe_version)
        ):
            raise BillingProviderUnavailable()
        headers = {"Authorization": "Bearer " + api_key, "Stripe-Version": stripe_version}
        account = scope.rsplit(":", 1)[0]
        if account != "self":
            if not re.fullmatch(r"acct_[A-Za-z0-9_]+", account):
                raise BillingProviderUnavailable()
            headers["Stripe-Account"] = account
        params = {"expand[]": "latest_invoice"}
        url = "https://api.stripe.com/v1/subscriptions/" + subscription
    elif provider == "razorpay":
        if (
            not api_key.startswith("rzp_" + mode + "_")
            or not api_secret
            or not 16 <= len(api_secret) <= 8192
        ):
            raise BillingProviderUnavailable()
        auth = httpx.BasicAuth(api_key, api_secret)
        url = "https://api.razorpay.com/v1/subscriptions/" + subscription
    else:
        raise BillingProviderUnavailable()
    deadline = time.monotonic() + 10
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(5, connect=3),
                transport=transport,
                trust_env=False,
                follow_redirects=False,
            ) as client,
            client.stream("GET", url, headers=headers, params=params, auth=auth) as response,
        ):
            if response.status_code != 200:
                raise BillingProviderUnavailable()
            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline or len(body) + len(chunk) > 256 * 1024:
                    raise BillingProviderUnavailable()
                body.extend(chunk)
            doc = _document(bytes(body))
        return normalize(provider, doc, subscription_id=subscription, account_scope=scope)
    except (httpx.HTTPError, InvalidBillingEvent):
        raise BillingProviderUnavailable() from None
