"""Reviewed price/plan creation with durable uncertainty, never blind retries."""

import hashlib
import json
import re
import time
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from skriller.billing.access import operator
from skriller.billing.events import _document
from skriller.billing.plans import PLANS, razorpay_plan_payload, stripe_price_payload
from skriller.db.schema import metadata

remote_plans = sa.Table(
    "billing_remote_plans",
    metadata,
    sa.Column("provider", sa.String(16), primary_key=True),
    sa.Column("account_scope", sa.String(192), primary_key=True),
    sa.Column("slug", sa.String(16), primary_key=True),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("remote_id", sa.String(192)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("state IN ('dispatching','ready','uncertain')"),
)


def _create(config, slug, request_hash, *, transport=None):
    plan = PLANS[slug]
    kwargs: dict[str, Any]
    if config.provider == "stripe":
        # Form encoding is required by the Stripe REST price-create contract.
        payload = stripe_price_payload(slug)
        data = {
            "currency": payload["currency"],
            "unit_amount": str(payload["unit_amount"]),
            "recurring[interval]": "month",
            "recurring[interval_count]": "1",
            "product_data[name]": plan.name,
            "metadata[skriller_plan]": slug,
            "metadata[catalog_version]": "2026-10-17",
        }
        headers = {
            "Authorization": "Bearer " + config.api_key,
            "Stripe-Version": config.stripe_version,
            "Idempotency-Key": "skriller-plan-" + request_hash,
        }
        if config.account_id:
            headers["Stripe-Account"] = config.account_id
        url, auth, kwargs = "https://api.stripe.com/v1/prices", None, {"data": data}
    else:
        headers, url = {}, "https://api.razorpay.com/v1/plans"
        auth = httpx.BasicAuth(config.api_key, config.api_secret)
        kwargs = {"json": razorpay_plan_payload(slug)}
    deadline = time.monotonic() + 10
    with (
        httpx.Client(
            timeout=httpx.Timeout(5, connect=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client,
        client.stream("POST", url, headers=headers, auth=auth, **kwargs) as response,
    ):
        if response.status_code not in {200, 201}:
            raise ValueError("Provider plan creation unavailable")
        body = bytearray()
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > 65536 or time.monotonic() > deadline:
                raise ValueError("Provider plan creation exceeded bounds")
            body.extend(chunk)
        doc = _document(bytes(body))
    if config.provider == "stripe":
        valid = (
            doc.get("object") == "price"
            and doc.get("unit_amount") == plan.usd_cents
            and doc.get("currency") == "usd"
            and doc.get("livemode") is config.live_mode
            and doc.get("recurring", {}).get("interval") == "month"
            and doc.get("recurring", {}).get("interval_count") == 1
        )
        prefix = "price_"
    else:
        item = doc.get("item", {})
        valid = (
            doc.get("entity") == "plan"
            and doc.get("period") == "monthly"
            and doc.get("interval") == 1
            and item.get("currency") == "INR"
            and item.get("amount") == plan.inr_paise
        )
        prefix = "plan_"
    if (
        not valid
        or not isinstance(doc.get("id"), str)
        or not re.fullmatch(prefix + r"[A-Za-z0-9_]{1,180}", doc["id"])
    ):
        raise ValueError("Provider plan receipt does not match approved catalog")
    return doc["id"]


def provision_plan(engine, config, slug, *, transport=None):
    """Explicit operator action creates a plan, never a charge or subscription.

    User approved the four catalog entries. A timeout/crash is uncertain, not a
    reason to create another Razorpay plan; operator reconciliation is required.
    Stripe additionally receives a stable native idempotency key.
    """
    if slug not in PLANS:
        raise ValueError("Unknown approved plan")
    payload = (
        stripe_price_payload(slug) if config.provider == "stripe" else razorpay_plan_payload(slug)
    )
    digest = hashlib.sha256(
        json.dumps([config.provider, config.scope, payload], sort_keys=True).encode()
    ).hexdigest()
    key = {"provider": config.provider, "account_scope": config.scope, "slug": slug}
    where = tuple(remote_plans.c[name] == value for name, value in key.items())
    with engine.begin() as connection:
        operator(connection)
        inserted = connection.execute(
            insert(remote_plans)
            .values(**key, request_hash=digest, state="dispatching")
            .on_conflict_do_nothing()
            .returning(remote_plans.c.slug)
        ).scalar_one_or_none()
        if inserted is None:
            row = connection.execute(sa.select(remote_plans).where(*where)).mappings().one()
            if row["request_hash"] == digest and row["state"] == "ready":
                return {"state": "ready", "remote_id": row["remote_id"]}
            return {"state": "requires_reconciliation", "remote_id": None}
    try:
        identifier = _create(config, slug, digest, transport=transport)
    except Exception:  # noqa: BLE001 - unknown write outcome and no provider diagnostics in logs
        with engine.begin() as connection:
            connection.execute(sa.update(remote_plans).where(*where).values(state="uncertain"))
        return {"state": "requires_reconciliation", "remote_id": None}
    with engine.begin() as connection:
        connection.execute(
            sa.update(remote_plans).where(*where).values(state="ready", remote_id=identifier)
        )
    return {"state": "ready", "remote_id": identifier}
