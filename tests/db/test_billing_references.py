import hmac
import json
import time
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_billing_runtime import setup, snapshot

from skriller.billing.access import bind_subscription
from skriller.billing.catalog import configure
from skriller.billing.inbox import inbox
from skriller.billing.providers import PaymentReference, fetch_reference
from skriller.billing.reconcile import Allowance, CurrentSubscription
from skriller.billing.references import references
from skriller.billing.runtime import ProviderConfiguration, create_ingress, run_once
from skriller.entitlements import policy_for

pytestmark = pytest.mark.integration_db


def dispute(config, charge, event_id=None):
    body = json.dumps(
        {
            "id": event_id or "evt_" + uuid4().hex,
            "type": "charge.dispute.created",
            "livemode": False,
            "account": config.account_id,
            "data": {
                "object": {
                    "object": "dispute",
                    "id": "dp_fixture",
                    "charge": charge,
                    "status": "needs_response",
                }
            },
        }
    ).encode()
    now = int(time.time())
    sig = hmac.new(config.webhook_secret, str(now).encode() + b"." + body, "sha256").hexdigest()
    return body, {"Stripe-Signature": f"t={now},v1={sig}"}


def test_signed_reference_survives_intake_and_resolves_before_entitlement_change(database):
    actor, workspace, config, subscription, engine = setup(database)
    try:
        client = TestClient(create_ingress(engine, (config,)))
        path = f"/webhooks/stripe/{config.scope}"
        body, headers = dispute(config, "ch_fixture")
        for expected in ("queued", "duplicate"):
            result = client.post(path, content=body, headers=headers)
            assert result.status_code == 200 and result.json() == {"status": expected}
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(references).where(references.c.account_scope == config.scope)
                )
                .mappings()
                .one()
            )
            assert row["attempt_count"] == 0 and row["state"] == "pending"
            assert (
                connection.execute(
                    sa.select(inbox).where(inbox.c.event_key == row["event_key"])
                ).first()
                is None
            )
        calls = []

        def lookup(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "ch_fixture",
                    "object": "charge",
                    "livemode": False,
                    "customer": "cus_fixture",
                },
            )

        assert run_once(
            engine,
            (config,),
            limit=1,
            resolve_reference=lambda cfg, ref: fetch_reference(
                cfg, ref, transport=httpx.MockTransport(lookup)
            ),
        ) == ["reference_resolved"]
        assert len(calls) == 1
        with engine.connect() as connection:
            row = (
                connection.execute(sa.select(inbox).where(inbox.c.event_key == row["event_key"]))
                .mappings()
                .one()
            )
            assert row["workspace_id"] == workspace and row["subscription_id"] == subscription
            assert row["event_type"] == "billing.dispute.open" and row["state"] == "pending"
        assert run_once(engine, (config,), limit=1, fetch_current=snapshot) == ["disabled"]
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
        with database.tenant(actor, workspace) as session, pytest.raises(sa.exc.DBAPIError):
            session.execute(sa.select(references))
    finally:
        engine.dispose()


def test_reference_failures_backoff_quarantine_and_event_conflicts(database):
    _, _, config, _, engine = setup(database)
    try:
        client = TestClient(create_ingress(engine, (config,)))
        path = f"/webhooks/stripe/{config.scope}"
        event_id = "evt_" + uuid4().hex
        body, headers = dispute(config, "ch_fixture", event_id)
        assert client.post(path, content=body, headers=headers).status_code == 200
        other_body, other_headers = dispute(config, "ch_other", event_id)
        assert client.post(path, content=other_body, headers=other_headers).status_code == 400
        calls = []

        def unmatched(_, ref):
            calls.append(ref)
            return PaymentReference("cus_unmapped")

        for attempt in range(1, 6):
            assert run_once(engine, (config,), limit=1, resolve_reference=unmatched) == [
                "reference_retry" if attempt < 5 else "reference_quarantined"
            ]
            with engine.begin() as connection:
                row = (
                    connection.execute(
                        sa.select(references).where(references.c.event_key == event_id)
                    )
                    .mappings()
                    .one()
                )
                assert row["attempt_count"] == attempt
                if attempt < 5:
                    # An immediate worker call cannot consume another reference attempt.
                    from skriller.billing.references import resolve_pending

                    assert (
                        resolve_pending(
                            engine,
                            {(config.provider, config.scope): config},
                            limit=1,
                            fetch=unmatched,
                        )
                        == []
                    )
                    connection.execute(
                        sa.update(references)
                        .where(references.c.event_key == event_id)
                        .values(next_attempt_at=sa.func.now())
                    )
        assert len(calls) == 5
        with engine.connect() as connection:
            assert (
                connection.execute(sa.select(inbox).where(inbox.c.event_key == event_id)).first()
                is None
            )
    finally:
        engine.dispose()


def test_razorpay_dispute_payment_reference_to_workspace_policy(database):
    from datetime import UTC, datetime, timedelta

    from test_outbox import planned

    from skriller.settings import Settings

    actor, workspace, _, _ = planned(database)
    config = ProviderConfiguration(
        "razorpay",
        "acc_" + uuid4().hex,
        False,
        b"synthetic-reference-secret",
        "rzp_test_fixture_only",
        api_secret="synthetic-secret-only",
    )
    customer, subscription = "cust_" + uuid4().hex, "sub_" + uuid4().hex
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="razorpay",
                account_scope=config.scope,
                subscription_id=subscription,
            )
            configure(connection, workspace, Allowance("plan_fixture", customer, 50, 25, 3))
        client = TestClient(create_ingress(engine, (config,)))
        for suffix, enabled in [
            ("created", False),
            ("won", True),
            ("refund-full", False),
            ("refund-partial", True),
        ]:
            if suffix.startswith("refund-"):
                kind = "refund.processed"
                payload = {
                    "refund": {
                        "entity": {
                            "entity": "refund",
                            "status": "processed",
                            "payment_id": "pay_fixture",
                        }
                    },
                    "payment": {
                        "entity": {
                            "entity": "payment",
                            "id": "pay_fixture",
                            "amount": 1000,
                            "amount_refunded": 1000 if suffix == "refund-full" else 250,
                        }
                    },
                }
            else:
                kind = "payment.dispute." + suffix
                payload = {
                    "dispute": {"entity": {"entity": "dispute", "payment_id": "pay_fixture"}}
                }
            body = json.dumps(
                {
                    "account_id": config.account_id,
                    "event": kind,
                    "payload": payload,
                }
            ).encode()
            sig = hmac.new(config.webhook_secret, body, "sha256").hexdigest()
            result = client.post(
                f"/webhooks/razorpay/{config.scope}",
                content=body,
                headers={"X-Razorpay-Signature": sig},
            )
            assert result.status_code == 200 and result.json() == {"status": "queued"}

            def lookup(request):
                assert request.url.path == "/v1/payments/pay_fixture"
                return httpx.Response(
                    200, json={"entity": "payment", "id": "pay_fixture", "customer_id": customer}
                )

            assert run_once(
                engine,
                (config,),
                limit=1,
                resolve_reference=lambda cfg, ref: fetch_reference(
                    cfg, ref, transport=httpx.MockTransport(lookup)
                ),
            ) == ["reference_resolved"]

            def current(binding):
                return CurrentSubscription(
                    subscription,
                    config.scope,
                    customer,
                    "plan_fixture",
                    "active",
                    True,
                    datetime.now(UTC) + timedelta(days=1),
                )

            assert run_once(engine, (config,), limit=1, fetch_current=current) == [
                "enabled" if enabled else "disabled"
            ]
            with database.tenant(actor, workspace) as session:
                assert policy_for(session)["enabled"] is enabled
    finally:
        engine.dispose()


def test_reference_resolution_rejects_ambiguous_customer_and_ignores_other_accounts(database):
    from test_outbox import planned

    from skriller.billing.references import resolve_pending

    _, _, config, _, engine = setup(database)
    second_actor, second_workspace, _, _ = planned(database)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                second_workspace,
                provider="stripe",
                account_scope=config.scope,
                subscription_id="sub_" + uuid4().hex,
            )
            configure(
                connection, second_workspace, Allowance("price_fixture", "cus_fixture", 50, 25, 3)
            )
        client = TestClient(create_ingress(engine, (config,)))
        body, headers = dispute(config, "ch_fixture")
        assert (
            client.post(
                f"/webhooks/stripe/{config.scope}", content=body, headers=headers
            ).status_code
            == 200
        )

        def ambiguous(_, reference):
            return PaymentReference("cus_fixture")

        assert (
            resolve_pending(
                engine,
                {("stripe", "acct_other:test"): config},
                limit=1,
                fetch=lambda *_: pytest.fail("Cross-account lookup"),
            )
            == []
        )
        assert run_once(engine, (config,), limit=1, resolve_reference=ambiguous) == [
            "reference_retry"
        ]
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(references).where(references.c.account_scope == config.scope)
                )
                .mappings()
                .one()
            )
            assert row["state"] == "pending" and row["attempt_count"] == 1
            assert (
                connection.execute(
                    sa.select(inbox).where(inbox.c.event_key == row["event_key"])
                ).first()
                is None
            )
        with database.tenant(second_actor, second_workspace) as session:
            assert policy_for(session)["enabled"] is False
    finally:
        engine.dispose()


def test_reference_crash_commits_attempt_and_advisory_lock_prevents_duplicate_io(database):
    from skriller.billing.references import resolve_pending

    _, _, config, _, engine = setup(database)
    try:
        client = TestClient(create_ingress(engine, (config,)))
        event_id = "evt_" + uuid4().hex
        body, headers = dispute(config, "ch_fixture", event_id)
        assert (
            client.post(
                f"/webhooks/stripe/{config.scope}", content=body, headers=headers
            ).status_code
            == 200
        )
        lock = "billing-reference:stripe:" + config.scope + ":" + event_id
        configs = {(config.provider, config.scope): config}
        with engine.connect() as held:
            held.execute(
                sa.text("SELECT pg_advisory_lock(hashtextextended(:key,0))"), {"key": lock}
            )
            held.commit()
            assert resolve_pending(
                engine, configs, limit=1, fetch=lambda *_: pytest.fail("Duplicate lookup")
            ) == ["reference_busy"]
            held.execute(
                sa.text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": lock}
            )
            held.commit()

        def crash(*_):
            raise SystemExit("simulated process loss")

        with pytest.raises(SystemExit):
            resolve_pending(engine, configs, limit=1, fetch=crash)
        with engine.connect() as connection:
            row = (
                connection.execute(sa.select(references).where(references.c.event_key == event_id))
                .mappings()
                .one()
            )
            assert row["attempt_count"] == 1 and row["state"] == "pending"
        assert (
            resolve_pending(
                engine, configs, limit=1, fetch=lambda *_: pytest.fail("Backoff ignored")
            )
            == []
        )
    finally:
        engine.dispose()
