import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from test_outbox import planned

from skriller.billing.access import bind_subscription
from skriller.billing.catalog import catalog, configure, load, receive_bound, refresh
from skriller.billing.events import InvalidBillingEvent
from skriller.billing.inbox import inbox
from skriller.billing.providers import fetch_subscription
from skriller.billing.reconcile import Allowance
from skriller.entitlements import policy_for
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
SECRET = b"catalog-fixture-signature-only"


def test_stored_binding_overrides_payload_workspace_and_periodic_refresh_uses_same_pipeline(
    database,
):
    actor, workspace, _, _ = planned(database)
    other = database.create_workspace(actor, "Not the billing destination")["id"]
    subscription = "sub_" + uuid4().hex
    key = "evt_" + uuid4().hex
    now = int(datetime.now(UTC).timestamp())
    body = json.dumps(
        {
            "id": key,
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {
                "object": {
                    "id": subscription,
                    "object": "subscription",
                    "metadata": {"workspace_id": other},
                }
            },
        }
    ).encode()
    digest = hmac.new(SECRET, str(now).encode() + b"." + body, "sha256").hexdigest()
    engine = sa.create_engine(Settings().database_url)
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": subscription,
                "object": "subscription",
                "customer": "cus_fixture",
                "status": "active",
                "livemode": False,
                "items": {
                    "has_more": False,
                    "data": [
                        {
                            "quantity": 1,
                            "price": {"id": "price_fixture"},
                            "current_period_end": int(
                                (datetime.now(UTC) + timedelta(days=1)).timestamp()
                            ),
                        }
                    ],
                },
                "latest_invoice": {
                    "status": "paid",
                    "customer": "cus_fixture",
                    "subscription": subscription,
                },
            },
        )

    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="stripe",
                account_scope="self:test",
                subscription_id=subscription,
            )
            configure(connection, workspace, Allowance("price_fixture", "cus_fixture", 50, 30, 4))
            assert (
                receive_bound(
                    connection, "stripe", body, f"t={now},v1={digest}", secret=SECRET, now=now
                )
                == "queued"
            )
            row = (
                connection.execute(sa.select(inbox).where(inbox.c.event_key == key))
                .mappings()
                .one()
            )
            assert row["workspace_id"] == workspace
            allowance = load(connection, workspace)
            assert allowance.runs == 50
            assert (
                refresh(
                    connection,
                    workspace,
                    fetch_current=lambda binding: fetch_subscription(
                        binding,
                        api_key="sk_test_fixture_only",
                        stripe_version="2025-06-30.basil",
                        transport=httpx.MockTransport(response),
                    ),
                )
                == "enabled"
            )
        assert len(requests) == 1 and requests[0].method == "GET"
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is True
        with database.tenant(actor, workspace) as session, pytest.raises(DBAPIError):
            session.execute(sa.select(catalog))
        with engine.begin() as connection:
            configure(connection, workspace, Allowance("price_other", "cus_other", 20, 10, 2))
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
    finally:
        engine.dispose()


def test_unknown_subscription_never_creates_inbox_or_grants(database):
    actor, workspace, _, _ = planned(database)
    now = int(datetime.now(UTC).timestamp())
    body = json.dumps(
        {
            "id": "evt_" + uuid4().hex,
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {"object": {"id": "sub_" + uuid4().hex, "object": "subscription"}},
        }
    ).encode()
    digest = hmac.new(SECRET, str(now).encode() + b"." + body, "sha256").hexdigest()
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection, pytest.raises(InvalidBillingEvent):
            receive_bound(
                connection, "stripe", body, f"t={now},v1={digest}", secret=SECRET, now=now
            )
        with database.tenant(actor, workspace) as session, pytest.raises(PermissionError):
            refresh(session, workspace, fetch_current=lambda _: pytest.fail("Untrusted refresh"))
    finally:
        engine.dispose()


def test_full_refund_payment_event_routes_by_unique_provider_customer(database):
    _actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    customer = "cus_" + uuid4().hex
    event_id = "evt_" + uuid4().hex
    now = int(datetime.now(UTC).timestamp())
    body = json.dumps(
        {
            "id": event_id,
            "type": "charge.refunded",
            "livemode": False,
            "data": {
                "object": {
                    "id": "ch_" + uuid4().hex,
                    "object": "charge",
                    "customer": customer,
                    "invoice": "in_fixture",
                    "amount": 1000,
                    "amount_refunded": 1000,
                }
            },
        }
    ).encode()
    digest = hmac.new(SECRET, str(now).encode() + b"." + body, "sha256").hexdigest()
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="stripe",
                account_scope="self:test",
                subscription_id=subscription,
            )
            configure(connection, workspace, Allowance("price_fixture", customer, 50, 30, 4))
            assert (
                receive_bound(
                    connection,
                    "stripe",
                    body,
                    f"t={now},v1={digest}",
                    secret=SECRET,
                    now=now,
                )
                == "queued"
            )
            row = (
                connection.execute(sa.select(inbox).where(inbox.c.event_key == event_id))
                .mappings()
                .one()
            )
            assert row["subscription_id"] == subscription
            assert row["event_type"] == "charge.refunded:full"
            assert row["workspace_id"] == workspace
    finally:
        engine.dispose()


def test_customer_only_payment_event_rejects_ambiguous_workspace_binding(database):
    actor, first, _, _ = planned(database)
    second = database.create_workspace(actor, "Second billing workspace")["id"]
    subscription_a, subscription_b = "sub_" + uuid4().hex, "sub_" + uuid4().hex
    now = int(datetime.now(UTC).timestamp())
    event_id = "evt_" + uuid4().hex
    body = json.dumps(
        {
            "id": event_id,
            "type": "charge.refunded",
            "livemode": False,
            "data": {
                "object": {
                    "id": "ch_" + uuid4().hex,
                    "object": "charge",
                    "customer": "cus_fixture",
                    "amount": 1000,
                    "amount_refunded": 1000,
                }
            },
        }
    ).encode()
    digest = hmac.new(SECRET, str(now).encode() + b"." + body, "sha256").hexdigest()
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            for workspace, subscription in ((first, subscription_a), (second, subscription_b)):
                bind_subscription(
                    connection,
                    workspace,
                    provider="stripe",
                    account_scope="self:test",
                    subscription_id=subscription,
                )
                configure(
                    connection, workspace, Allowance("price_fixture", "cus_fixture", 50, 30, 4)
                )
            with pytest.raises(InvalidBillingEvent):
                receive_bound(
                    connection,
                    "stripe",
                    body,
                    f"t={now},v1={digest}",
                    secret=SECRET,
                    now=now,
                )
            assert (
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(inbox)
                    .where(inbox.c.event_key == event_id)
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()
