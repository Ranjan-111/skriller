import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_outbox import planned

from skriller.auth import Identity, require_identity
from skriller.billing.access import bindings
from skriller.billing.catalog import catalog
from skriller.billing.checkout import CheckoutConfiguration, intents
from skriller.billing.checkout_http import fetch_checkout
from skriller.billing.provisioning import remote_plans
from skriller.billing.reconcile import CurrentSubscription
from skriller.billing.runtime import ProviderConfiguration, create_ingress, run_once
from skriller.db.schema import memberships
from skriller.entitlements import policy_for
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def setup_checkout(database, provider="stripe", slug="starter"):
    actor, workspace, _, _ = planned(database)
    config = ProviderConfiguration(
        provider,
        ("acct_" if provider == "stripe" else "acc_") + uuid4().hex,
        False,
        b"synthetic-checkout-secret",
        "sk_test_fixture_only" if provider == "stripe" else "rzp_test_fixture_only",
        api_secret="synthetic-secret-only",
        stripe_version="2025-06-30.basil",
    )
    engine = sa.create_engine(Settings().database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(remote_plans).values(
                provider=provider,
                account_scope=config.scope,
                slug=slug,
                request_hash="0" * 64,
                state="ready",
                remote_id="price_fixture" if provider == "stripe" else "plan_fixture",
            )
        )
    app = create_ingress(
        engine,
        (config,),
        checkout=CheckoutConfiguration("skriller-fixture", "http://localhost:3000"),
    )
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    return actor, workspace, config, engine, app, TestClient(app)


def create_response(config, request):
    assert request.method == "POST"
    if config.provider == "stripe":
        data = parse_qs(request.content.decode())
        identifier = data["client_reference_id"][0]
        assert data["mode"] == ["subscription"] and data["line_items[0][quantity]"] == ["1"]
        assert data["line_items[0][price]"] == ["price_fixture"]
        assert data["success_url"] == ["http://localhost:3000/?billing=returned"]
        assert (
            "customer_email" not in data and request.headers["Stripe-Account"] == config.account_id
        )
        assert request.headers["Idempotency-Key"] == "skriller-checkout-" + identifier
        return httpx.Response(
            200,
            json={
                "id": "cs_test_fixture",
                "object": "checkout.session",
                "mode": "subscription",
                "livemode": False,
                "status": "open",
                "client_reference_id": identifier,
                "metadata": {"skriller_checkout_intent": identifier},
                "expires_at": int(data["expires_at"][0]),
                "url": "https://checkout.stripe.com/c/pay/fixture",
            },
        )
    data = json.loads(request.content)
    assert data["total_count"] == 12 and data["quantity"] == 1 and data["plan_id"] == "plan_fixture"
    assert "addons" not in data and "customer_email" not in data
    return httpx.Response(
        200,
        json={
            "id": "sub_fixture",
            "entity": "subscription",
            "status": "created",
            **data,
            "short_url": "https://rzp.io/rzp/fixture",
        },
    )


def event(config, identifier, subscription="sub_fixture"):
    if config.provider == "stripe":
        doc = {
            "id": "evt_" + uuid4().hex,
            "account": config.account_id,
            "type": "customer.subscription.created",
            "livemode": False,
            "data": {
                "object": {
                    "object": "subscription",
                    "id": subscription,
                    "customer": "cus_fixture",
                    "metadata": {"skriller_checkout_intent": identifier},
                }
            },
        }
    else:
        doc = {
            "account_id": config.account_id,
            "event": "subscription.activated",
            "payload": {
                "subscription": {
                    "entity": {
                        "entity": "subscription",
                        "id": subscription,
                        "customer_id": "cust_fixture",
                        "notes": {"skriller_checkout_intent": identifier},
                    }
                }
            },
        }
    body = json.dumps(doc).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(
        config.webhook_secret,
        stamp.encode() + b"." + body if config.provider == "stripe" else body,
        "sha256",
    ).hexdigest()
    headers = (
        {"Stripe-Signature": f"t={stamp},v1={digest}"}
        if config.provider == "stripe"
        else {"X-Razorpay-Signature": digest}
    )
    return body, headers


def receipt(config, row, subscription="sub_fixture"):
    if config.provider == "stripe":
        return {
            "id": row["remote_id"],
            "object": "checkout.session",
            "mode": "subscription",
            "livemode": False,
            "status": "complete",
            "payment_status": "paid",
            "client_reference_id": row["id"],
            "metadata": {"skriller_checkout_intent": row["id"]},
            "customer": "cus_fixture",
            "subscription": subscription,
            "line_items": {
                "has_more": False,
                "data": [{"quantity": 1, "price": {"id": row["plan_id"]}}],
            },
        }
    return {
        "id": row["remote_id"],
        "entity": "subscription",
        "plan_id": row["plan_id"],
        "customer_id": "cust_fixture",
        "quantity": 1,
        "total_count": 12,
        "notes": {"skriller_checkout_intent": row["id"]},
    }


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
@pytest.mark.parametrize(
    "slug,runs,results,sources", [("starter", 50, 25, 3), ("pro", 200, 100, 5)]
)
def test_checkout_owner_intent_native_receipt_and_fresh_subscription_before_access(
    database, provider, slug, runs, results, sources
):
    actor, workspace, config, engine, app, client = setup_checkout(database, provider, slug)
    calls = []

    def respond(request):
        calls.append(request)
        return create_response(config, request)

    app.state.checkout_transport = httpx.MockTransport(respond)
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": provider, "plan": slug, "idempotency_key": uuid4().hex, "opt_in": True}
    try:
        response = client.post(path, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["state"] == "ready" and result["checkout_url"].startswith("https://")
        assert result["maximum_monthly_cycles"] == (12 if provider == "razorpay" else None)
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post(path, json=body).json() == result and len(calls) == 1
        assert client.post(path, json=body | {"idempotency_key": uuid4().hex}).status_code == 409
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(bindings).where(bindings.c.workspace_id == workspace)
                ).first()
                is None
            )
        raw, headers = event(config, result["id"])
        webhook = f"/webhooks/{provider}/{config.scope}"
        assert client.post(webhook, content=raw, headers=headers).json() == {"status": "queued"}
        assert client.post(webhook, content=raw, headers=headers).json() == {"status": "duplicate"}
        if slug == "pro":
            # A restored receipt may be checked afresh, but never reopens its archived URL.
            with engine.begin() as connection:
                connection.execute(
                    sa.update(intents)
                    .where(intents.c.id == result["id"])
                    .values(state="uncertain", checkout_url=None)
                )

        def read(cfg, row):
            return fetch_checkout(
                cfg,
                row,
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=receipt(cfg, row))
                ),
            )

        assert run_once(engine, (config,), limit=1, resolve_checkout=read) == ["reference_resolved"]
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
        with engine.connect() as connection:
            binding = (
                connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert binding["enabled"] is False and binding["subscription_id"] == "sub_fixture"
            commercial = (
                connection.execute(sa.select(catalog).where(catalog.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert (
                commercial["monthly"] is True
                and commercial["runs"] == runs
                and commercial["results"] == results
                and commercial["sources"] == sources
            )

        def fresh(binding):
            return CurrentSubscription(
                binding["subscription_id"],
                config.scope,
                "cus_fixture" if provider == "stripe" else "cust_fixture",
                "price_fixture" if provider == "stripe" else "plan_fixture",
                "active",
                True,
                datetime.now(UTC) + timedelta(days=30),
                datetime.now(UTC) - timedelta(minutes=1),
            )

        assert run_once(engine, (config,), limit=1, fetch_current=fresh) == ["enabled"]
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is True
        status = client.get(path + "/" + result["id"]).json()
        assert status["state"] == "bound" and status["checkout_url"] is None
        assert client.post(webhook, content=raw, headers=headers).json() == {"status": "duplicate"}
        with database.tenant(actor, workspace) as session, pytest.raises(sa.exc.DBAPIError):
            session.execute(sa.select(intents))
    finally:
        engine.dispose()


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_uncertain_checkout_write_never_repeats_or_grants_access(database, provider):
    _actor, workspace, _config, engine, app, client = setup_checkout(database, provider)
    calls = []

    def lost(request):
        calls.append(request)
        raise httpx.ReadTimeout("Synthetic response loss")

    app.state.checkout_transport = httpx.MockTransport(lost)
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": provider, "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}
    try:
        for _ in range(2):
            response = client.post(path, json=body)
            assert response.status_code == 200 and response.json()["state"] == "uncertain"
            assert response.json()["checkout_url"] is None
        assert len(calls) == 1
        assert client.post(path, json=body | {"idempotency_key": uuid4().hex}).status_code == 409
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(bindings).where(bindings.c.workspace_id == workspace)
                ).first()
                is None
            )
    finally:
        engine.dispose()


def test_checkout_auth_owner_opt_in_body_and_cors_boundaries(database):
    actor, workspace, _config, engine, app, client = setup_checkout(database)
    app.state.checkout_transport = httpx.MockTransport(
        lambda _: pytest.fail("Unapproved checkout POST")
    )
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": "stripe", "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}
    try:
        app.dependency_overrides.clear()
        assert client.post(path, json=body).status_code == 401
        app.dependency_overrides[require_identity] = lambda: Identity("foreign-" + uuid4().hex)
        assert client.post(path, json=body).status_code == 409
        member = "member-" + uuid4().hex
        with engine.begin() as connection:
            connection.execute(
                sa.insert(memberships).values(
                    workspace_id=workspace, actor_id=member, role="member"
                )
            )
        app.dependency_overrides[require_identity] = lambda: Identity(member)
        assert client.post(path, json=body).status_code == 409
        app.dependency_overrides[require_identity] = lambda: Identity(actor)
        assert client.post(path, json=body | {"opt_in": False}).status_code == 409
        response = client.post(path, json=body | {"return_url": "secret-value"})
        assert response.status_code == 422 and "secret-value" not in response.text
        assert (
            client.post(
                path, content=b"x" * 4097, headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        headers = {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
        assert "access-control-allow-origin" not in client.options(path, headers=headers).headers
        headers["Origin"] = "http://localhost:3000"
        assert (
            client.options(path, headers=headers).headers["Access-Control-Allow-Origin"]
            == "http://localhost:3000"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
@pytest.mark.parametrize(
    "failure", ["wrong_subscription", "wrong_plan", "wrong_checkout", "redirect"]
)
def test_untrusted_callback_cannot_bind_without_matching_native_receipt(
    database, provider, failure
):
    _, workspace, config, engine, app, client = setup_checkout(database, provider)
    app.state.checkout_transport = httpx.MockTransport(
        lambda request: create_response(config, request)
    )
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": provider, "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}
    try:
        result = client.post(path, json=body).json()
        raw, headers = event(
            config, result["id"], "sub_other" if failure == "wrong_subscription" else "sub_fixture"
        )
        assert client.post(
            f"/webhooks/{provider}/{config.scope}", content=raw, headers=headers
        ).json() == {"status": "queued"}

        def read(cfg, row):
            doc = receipt(cfg, row)
            if failure == "wrong_plan":
                if provider == "stripe":
                    doc["line_items"]["data"][0]["price"]["id"] = "price_other"
                else:
                    doc["plan_id"] = "plan_other"
            if failure == "wrong_checkout":
                doc["metadata" if provider == "stripe" else "notes"]["skriller_checkout_intent"] = (
                    str(uuid4())
                )
            calls = []

            def respond(request):
                calls.append(request)
                return (
                    httpx.Response(302, headers={"Location": "https://evil.example"})
                    if failure == "redirect"
                    else httpx.Response(200, json=doc)
                )

            try:
                return fetch_checkout(cfg, row, transport=httpx.MockTransport(respond))
            finally:
                assert len(calls) == 1

        assert run_once(engine, (config,), limit=1, resolve_checkout=read) == ["reference_retry"]
        with engine.connect() as connection:
            assert (
                connection.execute(
                    sa.select(bindings).where(bindings.c.workspace_id == workspace)
                ).first()
                is None
            )
        assert client.get(path + "/" + result["id"]).json()["state"] == "ready"
    finally:
        engine.dispose()


def test_checkout_catalog_missing_plan_expiry_and_worker_loss(database):
    _, workspace, config, engine, app, client = setup_checkout(database)
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": "stripe", "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}
    try:
        catalog_result = client.get(path)
        assert catalog_result.status_code == 200 and catalog_result.json()["can_start"] is True
        starter, pro = catalog_result.json()["offers"]
        assert starter["amount_minor"] == 2900 and starter["configured"] is True
        assert pro["amount_minor"] == 7900 and pro["configured"] is False
        assert client.post(path, json=body | {"plan": "pro"}).status_code == 409

        def crash(request):
            raise SystemExit("simulated process loss after dispatch")

        app.state.checkout_transport = httpx.MockTransport(crash)
        # Call the service boundary directly: ASGI correctly does not consume process-exit signals.
        from skriller.billing.checkout import create_checkout

        with pytest.raises(SystemExit):
            create_checkout(
                engine,
                config,
                app.state.checkout_options,
                workspace,
                app.dependency_overrides[require_identity]().uid,
                "starter",
                body["idempotency_key"],
                opt_in=True,
                transport=app.state.checkout_transport,
            )
        app.state.checkout_transport = httpx.MockTransport(
            lambda _: pytest.fail("Crashed write was replayed")
        )
        result = client.post(path, json=body).json()
        assert result["state"] == "dispatching" and result["checkout_url"] is None
        assert client.get(path).json()["can_start"] is False
        raw, headers = event(config, str(uuid4()))
        assert (
            client.post(
                f"/webhooks/stripe/{config.scope}", content=raw, headers=headers
            ).status_code
            == 400
        )
        with engine.begin() as connection:
            connection.execute(
                sa.update(intents)
                .where(intents.c.id == result["id"])
                .values(
                    state="ready",
                    remote_id="cs_test_fixture",
                    checkout_url="https://checkout.stripe.com/c/pay/fixture",
                    expires_at=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
        assert client.get(path + "/" + result["id"]).json()["checkout_url"] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
@pytest.mark.parametrize("failure", ["unsafe_url", "wrong_expiry", "wrong_receipt"])
def test_checkout_rejects_unmatched_provider_creation_receipts(database, provider, failure):
    _, workspace, config, engine, app, client = setup_checkout(database, provider)
    calls = []

    def respond(request):
        calls.append(request)
        response = create_response(config, request)
        doc = response.json()
        if failure == "unsafe_url":
            doc["url" if provider == "stripe" else "short_url"] = "https://evil.example/steal"
        elif failure == "wrong_expiry":
            doc["expires_at" if provider == "stripe" else "expire_by"] += 86400
        elif provider == "stripe":
            doc["livemode"] = True
        else:
            doc["total_count"] = 24
        return httpx.Response(200, json=doc)

    app.state.checkout_transport = httpx.MockTransport(respond)
    try:
        body = {
            "provider": provider,
            "plan": "starter",
            "idempotency_key": uuid4().hex,
            "opt_in": True,
        }
        for _ in range(2):
            result = client.post(f"/v1/workspaces/{workspace}/checkout", json=body)
            assert result.status_code == 200 and result.json()["state"] == "uncertain"
            assert result.json()["checkout_url"] is None
        assert len(calls) == 1
    finally:
        engine.dispose()


def test_concurrent_checkout_requests_dispatch_one_provider_post(database):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from skriller.billing.checkout import create_checkout

    actor, workspace, config, engine, app, _ = setup_checkout(database)
    started, finish = threading.Event(), threading.Event()
    calls = []
    key = uuid4().hex

    def respond(request):
        calls.append(request)
        started.set()
        assert finish.wait(5), "Controlled provider request did not finish"
        return create_response(config, request)

    def start():
        return create_checkout(
            engine,
            config,
            app.state.checkout_options,
            workspace,
            actor,
            "starter",
            key,
            opt_in=True,
            transport=httpx.MockTransport(respond),
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(start)
            try:
                assert started.wait(5)
                second = start()
                assert second["state"] == "dispatching" and second["checkout_url"] is None
                assert len(calls) == 1
            finally:
                finish.set()
            assert first.result(timeout=5)["state"] == "ready"
        assert len(calls) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("state", ["dispatching", "ready", "bound"])
def test_expired_checkout_is_reconciled_without_replay_or_reviving_bound_state(database, state):
    _actor, workspace, config, engine, app, client = setup_checkout(database)
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": "stripe", "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}
    app.state.checkout_transport = httpx.MockTransport(
        lambda request: create_response(config, request)
    )
    try:
        receipt = client.post(path, json=body).json()
        with engine.begin() as connection:
            connection.execute(
                sa.update(intents)
                .where(intents.c.id == receipt["id"])
                .values(state=state, expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        app.state.checkout_transport = httpx.MockTransport(
            lambda _: pytest.fail("Expired purchase replayed")
        )
        for result in (
            client.get(path + "/" + receipt["id"]).json(),
            client.post(path, json=body).json(),
        ):
            assert result["state"] == ("bound" if state == "bound" else "uncertain")
            assert result["checkout_url"] is None
        assert client.get(path).json()["can_start"] is False
        with engine.begin() as connection:
            saved = (
                connection.execute(sa.select(intents).where(intents.c.id == receipt["id"]))
                .mappings()
                .one()
            )
            assert saved["remote_id"] == "cs_test_fixture"
            if state != "bound":
                assert saved["checkout_url"] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_late_native_receipt_after_expiry_is_kept_without_payment_link(database, provider):
    from skriller.billing.checkout import view

    actor, workspace, config, engine, app, client = setup_checkout(database, provider)
    path = f"/v1/workspaces/{workspace}/checkout"
    body = {"provider": provider, "plan": "starter", "idempotency_key": uuid4().hex, "opt_in": True}

    def suspended_request(request):
        response = create_response(config, request)
        with engine.begin() as connection:
            identifier = connection.execute(
                sa.select(intents.c.id).where(intents.c.workspace_id == workspace)
            ).scalar_one()
            connection.execute(
                sa.update(intents)
                .where(intents.c.id == identifier)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            assert view(connection, workspace, actor, identifier)["state"] == "uncertain"
        return response

    app.state.checkout_transport = httpx.MockTransport(suspended_request)
    try:
        result = client.post(path, json=body)
        assert result.status_code == 200
        assert result.json()["state"] == "uncertain" and result.json()["checkout_url"] is None
        with engine.begin() as connection:
            saved = (
                connection.execute(sa.select(intents).where(intents.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert saved["remote_id"] is not None and saved["checkout_url"] is None
        app.state.checkout_transport = httpx.MockTransport(
            lambda _: pytest.fail("Late native write replayed")
        )
        assert client.post(path, json=body).json()["state"] == "uncertain"
    finally:
        engine.dispose()
