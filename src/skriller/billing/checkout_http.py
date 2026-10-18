"""Bounded native checkout POST and receipt GET; callbacks and redirects grant nothing."""

import re
import time
from urllib.parse import urlsplit

import httpx

from skriller.billing.checkout import RAZORPAY_CYCLES, CheckoutUnavailable
from skriller.billing.events import _document
from skriller.billing.providers import PaymentReference


def request(config, method, path, *, data=None, payload=None, params=None, transport=None):
    config.__post_init__()
    stripe = config.provider == "stripe"
    headers, auth = {}, None
    if stripe:
        headers = {
            "Authorization": "Bearer " + config.api_key,
            "Stripe-Version": config.stripe_version,
        }
        if config.account_id:
            headers["Stripe-Account"] = config.account_id
        if method == "POST":
            headers["Idempotency-Key"] = "skriller-checkout-" + data["client_reference_id"]
    else:
        auth = httpx.BasicAuth(config.api_key, config.api_secret)
    origin = "https://api.stripe.com" if stripe else "https://api.razorpay.com"
    deadline = time.monotonic() + 10
    with (
        httpx.Client(
            timeout=httpx.Timeout(5, connect=3),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        ) as client,
        client.stream(
            method,
            origin + path,
            headers=headers,
            auth=auth,
            data=data,
            json=payload,
            params=params,
        ) as response,
    ):
        if response.status_code not in ({200, 201} if method == "POST" else {200}):
            raise CheckoutUnavailable()
        body = bytearray()
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > 256 * 1024 or time.monotonic() > deadline:
                raise CheckoutUnavailable()
            body.extend(chunk)
        return _document(bytes(body))


def create_remote(config, options, row, *, transport=None):
    stripe = config.provider == "stripe"
    if stripe:
        doc = request(
            config,
            "POST",
            "/v1/checkout/sessions",
            data={
                "mode": "subscription",
                "client_reference_id": row["id"],
                "line_items[0][price]": row["plan_id"],
                "line_items[0][quantity]": "1",
                "subscription_data[metadata][skriller_checkout_intent]": row["id"],
                "metadata[skriller_checkout_intent]": row["id"],
                "success_url": options.return_origin + "/?billing=returned",
                "cancel_url": options.return_origin + "/?billing=cancelled",
                "expires_at": str(int(row["expires_at"].timestamp())),
            },
            transport=transport,
        )
        valid = (
            doc.get("object") == "checkout.session"
            and doc.get("mode") == "subscription"
            and doc.get("livemode") is config.live_mode
            and doc.get("status") == "open"
            and doc.get("client_reference_id") == row["id"]
            and doc.get("metadata", {}).get("skriller_checkout_intent") == row["id"]
            and type(doc.get("expires_at")) is int
            and doc["expires_at"] == int(row["expires_at"].timestamp())
        )
        prefix, url = "cs_", doc.get("url")
    else:
        doc = request(
            config,
            "POST",
            "/v1/subscriptions",
            payload={
                "plan_id": row["plan_id"],
                "quantity": 1,
                "total_count": RAZORPAY_CYCLES,
                "customer_notify": True,
                "expire_by": int(row["expires_at"].timestamp()),
                "notes": {"skriller_checkout_intent": row["id"]},
            },
            transport=transport,
        )
        valid = (
            doc.get("entity") == "subscription"
            and doc.get("status") == "created"
            and doc.get("plan_id") == row["plan_id"]
            and type(doc.get("quantity")) is int
            and doc["quantity"] == 1
            and type(doc.get("total_count")) is int
            and doc["total_count"] == RAZORPAY_CYCLES
            and type(doc.get("expire_by")) is int
            and doc["expire_by"] == int(row["expires_at"].timestamp())
            and doc.get("notes", {}).get("skriller_checkout_intent") == row["id"]
        )
        prefix, url = "sub_", doc.get("short_url")
    if (
        not valid
        or not isinstance(doc.get("id"), str)
        or not re.fullmatch(prefix + r"[A-Za-z0-9_]{1,180}", doc["id"])
    ):
        raise CheckoutUnavailable()
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (
        parsed is None
        or len(url) > 4096
        or parsed.scheme != "https"
        or parsed.hostname != ("checkout.stripe.com" if stripe else "rzp.io")
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not parsed.path.startswith("/")
    ):
        raise CheckoutUnavailable()
    return doc["id"], url


def fetch_checkout(config, row, *, transport=None):
    stripe = config.provider == "stripe"
    prefix = "cs_" if stripe else "sub_"
    if not re.fullmatch(prefix + r"[A-Za-z0-9_]{1,180}", row["remote_id"]):
        raise CheckoutUnavailable()
    doc = request(
        config,
        "GET",
        ("/v1/checkout/sessions/" if stripe else "/v1/subscriptions/") + row["remote_id"],
        params={"expand[]": "line_items"} if stripe else None,
        transport=transport,
    )
    if doc.get("id") != row["remote_id"]:
        raise CheckoutUnavailable()
    if stripe:
        lines = doc.get("line_items", {})
        items = lines.get("data", [])
        if (
            doc.get("object") != "checkout.session"
            or doc.get("livemode") is not config.live_mode
            or doc.get("mode") != "subscription"
            or doc.get("status") != "complete"
            or doc.get("payment_status") != "paid"
            or doc.get("client_reference_id") != row["id"]
            or doc.get("metadata", {}).get("skriller_checkout_intent") != row["id"]
            or lines.get("has_more") is not False
            or len(items) != 1
            or items[0].get("price", {}).get("id") != row["plan_id"]
            or type(items[0].get("quantity")) is not int
            or items[0]["quantity"] != 1
        ):
            raise CheckoutUnavailable()
        customer, subscription = doc.get("customer"), doc.get("subscription")
    else:
        if (
            doc.get("entity") != "subscription"
            or doc.get("plan_id") != row["plan_id"]
            or doc.get("notes", {}).get("skriller_checkout_intent") != row["id"]
            or type(doc.get("quantity")) is not int
            or doc["quantity"] != 1
            or type(doc.get("total_count")) is not int
            or doc["total_count"] != RAZORPAY_CYCLES
        ):
            raise CheckoutUnavailable()
        customer, subscription = doc.get("customer_id"), doc["id"]
    if not isinstance(customer, str) or not customer.startswith("cus_" if stripe else "cust_"):
        raise CheckoutUnavailable()
    return PaymentReference(customer, subscription)
