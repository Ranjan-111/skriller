import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_outbox import planned

from skriller.billing.access import bind_subscription, bindings
from skriller.billing.inbox import inbox, receive
from skriller.billing.reconcile import Allowance, CurrentSubscription, audit, reconcile
from skriller.entitlements import policy_for, update_settings
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
SECRET = b"fixture-signature-secret-only"


def queue(connection, workspace, subscription, *, claimed_status="active"):
    now = int(datetime.now(UTC).timestamp())
    key = "evt_" + uuid4().hex
    body = json.dumps(
        {
            "id": key,
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {
                "object": {"id": subscription, "object": "subscription", "status": claimed_status}
            },
        }
    ).encode()
    signature = hmac.new(SECRET, str(now).encode() + b"." + body, "sha256").hexdigest()
    assert (
        receive(
            connection,
            "stripe",
            body,
            f"t={now},v1={signature}",
            secret=SECRET,
            now=now,
            workspace_id=workspace,
            subscription_id=subscription,
        )
        == "queued"
    )
    return key


def current(subscription, status="active", paid=True, customer="cus_fixture"):
    return CurrentSubscription(
        subscription,
        "self:test",
        customer,
        "price_fixture",
        status,
        paid,
        datetime.now(UTC) + timedelta(days=1),
    )


def test_current_state_not_delayed_event_controls_access_and_replay_is_audited_once(database):
    actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    allowance = Allowance("price_fixture", "cus_fixture", 50, 30, 4)
    with database.tenant(actor, workspace) as session:
        policy_for(session)
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
            first = queue(connection, workspace, subscription)
            assert (
                reconcile(
                    connection,
                    workspace,
                    first,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription),
                )
                == "enabled"
            )
        with database.tenant(actor, workspace) as session:
            policy = policy_for(session)
            assert policy["enabled"] is True and policy["run_limit"] == 50
            update_settings(session, enabled=False, result_limit=10, source_limit=2)
        with engine.begin() as connection:
            second = queue(connection, workspace, subscription)
            reconcile(
                connection,
                workspace,
                second,
                allowance=allowance,
                fetch_current=lambda _: current(subscription),
            )
        with database.tenant(actor, workspace) as session:
            policy = policy_for(session)
            assert (
                policy["enabled"] is False
                and policy["result_limit"] == 10
                and policy["source_limit"] == 2
            )
            update_settings(session, enabled=True, result_limit=10, source_limit=2)
        with engine.begin() as connection:
            delayed_active = queue(connection, workspace, subscription, claimed_status="active")
            assert (
                reconcile(
                    connection,
                    workspace,
                    delayed_active,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription, status="canceled"),
                )
                == "disabled"
            )

            def forbidden(_):
                pytest.fail("Duplicate event must not fetch or grant twice")

            assert (
                reconcile(
                    connection,
                    workspace,
                    delayed_active,
                    allowance=allowance,
                    fetch_current=forbidden,
                )
                == "already_processed"
            )
            rows = (
                connection.execute(sa.select(audit).where(audit.c.workspace_id == workspace))
                .mappings()
                .all()
            )
            assert len(rows) == 3 and sum(row["access_enabled"] for row in rows) == 2
            lease = (
                connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert lease["enabled"] is False
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
    finally:
        engine.dispose()


def test_wrong_customer_or_failed_current_read_rolls_back_and_unpaid_never_enables(database):
    actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    allowance = Allowance("price_fixture", "cus_fixture", 50, 30, 4)
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
            key = queue(connection, workspace, subscription)
        with engine.begin() as connection, pytest.raises(ValueError, match="does not match"):
            reconcile(
                connection,
                workspace,
                key,
                allowance=allowance,
                fetch_current=lambda _: current(subscription, customer="cus_other"),
            )

        def failed(_):
            raise TimeoutError("Synthetic provider timeout")

        with engine.begin() as connection, pytest.raises(TimeoutError):
            reconcile(connection, workspace, key, allowance=allowance, fetch_current=failed)
        with engine.begin() as connection:
            assert (
                reconcile(
                    connection,
                    workspace,
                    key,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription, paid=False),
                )
                == "disabled"
            )
            assert (
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(audit)
                    .where(audit.c.workspace_id == workspace)
                ).scalar_one()
                == 1
            )
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
    finally:
        engine.dispose()


@pytest.mark.parametrize("event_type", ["charge.refunded:full", "billing.dispute.open"])
def test_confirmed_full_refund_or_dispute_pauses_until_a_later_active_provider_read(
    database, event_type
):
    actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    allowance = Allowance("price_fixture", "cus_fixture", 50, 30, 4)
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
            key = queue(connection, workspace, subscription)
            connection.execute(
                sa.update(inbox).where(inbox.c.event_key == key).values(event_type=event_type)
            )
            assert (
                reconcile(
                    connection,
                    workspace,
                    key,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription),
                )
                == "disabled"
            )
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is False
        with engine.begin() as connection:
            next_event = queue(connection, workspace, subscription)
            assert (
                reconcile(
                    connection,
                    workspace,
                    next_event,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription),
                )
                == "enabled"
            )
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is True
    finally:
        engine.dispose()


def test_partial_refund_preserves_access_only_when_fresh_provider_state_is_paid(database):
    actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    allowance = Allowance("price_fixture", "cus_fixture", 50, 30, 4)
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
            key = queue(connection, workspace, subscription)
            connection.execute(
                sa.update(inbox)
                .where(inbox.c.event_key == key)
                .values(event_type="charge.refunded:partial")
            )
            assert (
                reconcile(
                    connection,
                    workspace,
                    key,
                    allowance=allowance,
                    fetch_current=lambda _: current(subscription),
                )
                == "enabled"
            )
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is True
    finally:
        engine.dispose()


def test_payment_reconciliation_never_resets_existing_job_admissions(database):
    from test_entitlements import queued

    from skriller.entitlements import execution_allowed, used_runs

    actor, workspace, conversation, plan = planned(database)
    job = queued(database, actor, workspace, conversation, plan)
    with database.tenant(actor, workspace) as session:
        assert execution_allowed(session, job)
        assert used_runs(session) == 1
    subscription = "sub_" + uuid4().hex
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
            for _ in range(2):
                key = queue(connection, workspace, subscription)
                reconcile(
                    connection,
                    workspace,
                    key,
                    allowance=Allowance("price_fixture", "cus_fixture", 50, 30, 4),
                    fetch_current=lambda _: current(subscription),
                )
        with database.tenant(actor, workspace) as session:
            assert used_runs(session) == 1
            assert policy_for(session)["run_limit"] == 50
    finally:
        engine.dispose()


def test_concurrent_reconciliation_serializes_fetch_before_applying_state(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    _, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    engine = sa.create_engine(Settings().database_url, pool_size=2, max_overflow=0)
    first_started, release_first, second_started = Event(), Event(), Event()
    allowance = Allowance("price_fixture", "cus_fixture", 50, 30, 4)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="stripe",
                account_scope="self:test",
                subscription_id=subscription,
            )
            first, second = (
                queue(connection, workspace, subscription),
                queue(connection, workspace, subscription),
            )

        def fetch_first(_):
            first_started.set()
            assert release_first.wait(5)
            return current(subscription)

        def fetch_second(_):
            second_started.set()
            return current(subscription, status="canceled")

        def process(key, fetch):
            with engine.begin() as connection:
                return reconcile(
                    connection, workspace, key, allowance=allowance, fetch_current=fetch
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(process, first, fetch_first)
            assert first_started.wait(5)
            b = pool.submit(process, second, fetch_second)
            try:
                assert not second_started.wait(0.1)
            finally:
                release_first.set()
            assert a.result(timeout=5) == "enabled"
            assert b.result(timeout=5) == "disabled"
        with engine.begin() as connection:
            row = (
                connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            assert row["enabled"] is False
    finally:
        release_first.set()
        engine.dispose()
