from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from test_billing_reconciliation import queue
from test_entitlements import queued
from test_outbox import planned

from skriller.billing.access import bind_subscription
from skriller.billing.reconcile import Allowance, CurrentSubscription, reconcile
from skriller.entitlements import admissions, execution_allowed, used_runs
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def test_verified_period_counts_only_current_admissions_without_erasing_history(database):
    actor, workspace, conversation, plan = planned(database)
    trial = queued(database, actor, workspace, conversation, plan)
    with database.tenant(actor, workspace) as session:
        assert execution_allowed(session, trial)
        assert used_runs(session) == 1
    start = datetime.now(UTC)
    subscription = "sub_" + uuid4().hex
    allowance = Allowance("price_fixture", "cus_fixture", 1, 25, 3, monthly=True)
    engine = sa.create_engine(Settings().database_url)
    current = CurrentSubscription(
        subscription,
        "self:test",
        "cus_fixture",
        "price_fixture",
        "active",
        True,
        start + timedelta(days=30),
        start,
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
            key = queue(connection, workspace, subscription)
            assert (
                reconcile(
                    connection, workspace, key, allowance=allowance, fetch_current=lambda _: current
                )
                == "enabled"
            )
        with database.tenant(actor, workspace) as session:
            assert used_runs(session) == 0
            assert (
                session.execute(
                    sa.select(sa.func.count())
                    .select_from(admissions)
                    .where(admissions.c.workspace_id == workspace)
                ).scalar_one()
                == 1
            )
        paid = queued(database, actor, workspace, conversation, plan)
        denied = queued(database, actor, workspace, conversation, plan)
        with database.tenant(actor, workspace) as session:
            # The application role must not evade monthly accounting by inserting
            # a backdated admission outside the provider's current window.
            session.execute(
                sa.insert(admissions).values(
                    workspace_id=workspace,
                    job_id=paid,
                    actor_id=actor,
                    admitted_at=start - timedelta(days=31),
                )
            )
            assert execution_allowed(session, paid)
            assert used_runs(session) == 1
        with engine.begin() as connection:
            repeat = queue(connection, workspace, subscription)
            reconcile(
                connection, workspace, repeat, allowance=allowance, fetch_current=lambda _: current
            )
        with database.tenant(actor, workspace) as session:
            assert used_runs(session) == 1
            assert not execution_allowed(session, denied)
        with database.tenant(actor, workspace) as session, pytest.raises(DBAPIError):
            session.execute(
                sa.insert(admissions).values(workspace_id=workspace, job_id=denied, actor_id=actor)
            )
        with engine.begin() as connection, pytest.raises(ValueError, match="monthly"):
            key = queue(connection, workspace, subscription)
            stale = CurrentSubscription(
                subscription,
                "self:test",
                "cus_fixture",
                "price_fixture",
                "active",
                True,
                start + timedelta(days=29),
                start - timedelta(days=1),
            )
            reconcile(
                connection, workspace, key, allowance=allowance, fetch_current=lambda _: stale
            )
    finally:
        engine.dispose()
