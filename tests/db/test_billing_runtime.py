import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_outbox import planned

from skriller.billing.access import bind_subscription, bindings
from skriller.billing.catalog import configure
from skriller.billing.inbox import inbox
from skriller.billing.reconcile import Allowance, CurrentSubscription, audit
from skriller.billing.runtime import ProviderConfiguration, create_ingress, run_once
from skriller.entitlements import policy_for
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def setup(database):
    actor, workspace, _, _ = planned(database)
    config = ProviderConfiguration(
        "stripe",
        "acct_" + uuid4().hex,
        False,
        b"synthetic-billing-secret-only",
        "sk_test_fixture_only",
        stripe_version="2025-06-30.basil",
    )
    subscription = "sub_" + uuid4().hex
    engine = sa.create_engine(Settings().database_url)
    with engine.begin() as connection:
        bind_subscription(
            connection,
            workspace,
            provider=config.provider,
            account_scope=config.scope,
            subscription_id=subscription,
        )
        configure(connection, workspace, Allowance("price_fixture", "cus_fixture", 50, 30, 4))
    return actor, workspace, config, subscription, engine


def request(config, subscription):
    now = int(datetime.now(UTC).timestamp())
    body = json.dumps(
        {
            "id": "evt_" + uuid4().hex,
            "account": config.account_id,
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {"object": {"id": subscription, "object": "subscription"}},
        }
    ).encode()
    digest = hmac.new(config.webhook_secret, str(now).encode() + b"." + body, "sha256").hexdigest()
    return body, f"t={now},v1={digest}"


def snapshot(binding, status="active"):
    return CurrentSubscription(
        binding["subscription_id"],
        binding["account_scope"],
        "cus_fixture",
        "price_fixture",
        status,
        True,
        datetime.now(UTC) + timedelta(days=1),
    )


def test_isolated_http_intake_to_worker_to_policy_and_periodic_cancellation(database):
    actor, workspace, config, subscription, engine = setup(database)
    calls = []
    try:
        client = TestClient(create_ingress(engine, (config,)))
        path = f"/webhooks/stripe/{config.scope}"
        body, signature = request(config, subscription)
        for expected in ["queued", "duplicate"]:
            response = client.post(path, content=body, headers={"Stripe-Signature": signature})
            assert response.status_code == 200 and response.json() == {"status": expected}
        assert (
            client.post(path, content=body, headers={"Stripe-Signature": "forged"}).status_code
            == 400
        )
        assert (
            client.post(
                path,
                content=body,
                headers=[("Stripe-Signature", signature), ("Stripe-Signature", signature)],
            ).status_code
            == 400
        )
        assert (
            client.post(
                path, content=b"x" * (256 * 1024 + 1), headers={"Stripe-Signature": signature}
            ).status_code
            == 413
        )
        assert client.post("/webhooks/stripe/unconfigured", content=body).status_code == 404

        def fetch(binding):
            calls.append(binding)
            return snapshot(binding)

        assert run_once(engine, (config,), fetch_current=fetch) == ["enabled"]
        assert len(calls) == 1
        assert run_once(engine, (config,), fetch_current=fetch) == []
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is True
        with engine.begin() as connection:
            row = (
                connection.execute(sa.select(inbox).where(inbox.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert row["attempt_count"] == 1 and row["state"] == "reconciled"
            connection.execute(
                sa.update(bindings)
                .where(bindings.c.workspace_id == workspace)
                .values(updated_at=datetime.now(UTC) - timedelta(minutes=6))
            )
        assert run_once(
            engine, (config,), fetch_current=lambda binding: snapshot(binding, "canceled")
        ) == ["disabled"]
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
        with engine.begin() as connection:
            assert (
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(audit)
                    .where(audit.c.workspace_id == workspace)
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()


def test_provider_failure_backoff_commits_attempts_then_quarantines_without_new_refresh(database):
    actor, workspace, config, _, engine = setup(database)
    calls = []

    def failed(binding):
        calls.append(binding)
        raise TimeoutError("synthetic secret must not reach result")

    try:
        for attempt in range(1, 6):
            assert run_once(engine, (config,), fetch_current=failed) == [
                "retry" if attempt < 5 else "quarantined"
            ]
            assert run_once(engine, (config,), fetch_current=failed) == []
            with engine.begin() as connection:
                rows = (
                    connection.execute(sa.select(inbox).where(inbox.c.workspace_id == workspace))
                    .mappings()
                    .all()
                )
                assert len(rows) == 1 and rows[0]["attempt_count"] == attempt
                assert rows[0]["state"] == ("pending" if attempt < 5 else "quarantined")
                connection.execute(
                    sa.update(inbox)
                    .where(inbox.c.workspace_id == workspace)
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )
        assert len(calls) == 5
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
    finally:
        engine.dispose()


def test_restricted_app_role_cannot_start_operator_ingress_or_worker(database):
    _, _, config, _, engine = setup(database)
    restricted = sa.create_engine(Settings().application_database_url)
    try:
        with pytest.raises(PermissionError):
            create_ingress(restricted, (config,))
        with pytest.raises(PermissionError):
            run_once(restricted, (config,))
        assert "synthetic-billing-secret" not in repr(config) and "sk_test" not in repr(config)
    finally:
        engine.dispose()
        restricted.dispose()


def test_real_once_process_loads_private_configuration_without_starting_listener(
    database, tmp_path
):
    import subprocess
    import sys

    # Unique unbound endpoint: actual PostgreSQL scan, no external API calls.
    account = "acct_" + uuid4().hex
    config = {
        "operator_database_url": Settings().database_url,
        "endpoints": [
            {
                "provider": "stripe",
                "account_id": account,
                "webhook_secret": "synthetic_process_secret_only",
                "api_key": "sk_test_fixture_only",
                "stripe_version": "2025-06-30.basil",
            }
        ],
    }
    path = tmp_path / "private-billing.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    result = subprocess.run(
        [sys.executable, "-m", "skriller.billing_runtime", "once", "--config-file", str(path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"processed": 0, "statuses": []}
    assert "synthetic_process_secret" not in result.stderr and "sk_test" not in result.stderr
