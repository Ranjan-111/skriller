from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from test_entitlements import queued
from test_outbox import planned

from skriller.billing.access import bind_subscription, bindings
from skriller.entitlements import admissions, execution_allowed, policy_for, update_settings
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def test_owner_cannot_reenable_unpaid_access_and_direct_admission_is_fenced(database):
    actor, workspace, conversation, plan = planned(database)
    job = queued(database, actor, workspace, conversation, plan)
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="stripe",
                account_scope="self:test",
                subscription_id="sub_" + uuid4().hex,
            )
        with database.tenant(actor, workspace) as session:
            policy = update_settings(session, enabled=True, result_limit=25, source_limit=3)
            assert policy["enabled"] is False
            assert execution_allowed(session, job) is False
        with database.tenant(actor, workspace) as session, pytest.raises(DBAPIError):
            session.execute(
                sa.insert(admissions).values(workspace_id=workspace, job_id=job, actor_id=actor)
            )
        with database.tenant(actor, workspace) as session, pytest.raises(DBAPIError):
            session.execute(sa.update(bindings).values(enabled=True))
    finally:
        engine.dispose()


@pytest.mark.parametrize("expired", [False, True])
def test_paid_window_expiry_and_owner_pause_are_both_enforced(database, expired):
    actor, workspace, _, _ = planned(database)
    with database.tenant(actor, workspace) as session:
        assert policy_for(session)["enabled"] is True
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            bind_subscription(
                connection,
                workspace,
                provider="razorpay",
                account_scope="acc_fixture:test",
                subscription_id="sub_" + uuid4().hex,
            )
            connection.execute(
                sa.update(bindings)
                .where(bindings.c.workspace_id == workspace)
                .values(
                    enabled=True,
                    valid_until=datetime.now(UTC) + timedelta(hours=-1 if expired else 1),
                )
            )
        with database.tenant(actor, workspace) as session:
            assert policy_for(session)["enabled"] is not expired
            assert (
                update_settings(session, enabled=False, result_limit=25, source_limit=3)["enabled"]
                is False
            )
        other = database.create_workspace(actor, "Unaffected workspace")["id"]
        with database.tenant(actor, other) as session:
            assert policy_for(session)["enabled"] is True
        foreign_actor = "foreign-billing-" + uuid4().hex
        foreign = database.create_workspace(foreign_actor, "Foreign")["id"]
        with database.tenant(foreign_actor, foreign) as session:
            assert (
                session.execute(
                    sa.text("SELECT billing_access_allowed(:workspace)"), {"workspace": workspace}
                ).scalar_one()
                is False
            )
    finally:
        engine.dispose()


def test_one_billing_authority_and_app_cannot_bind_subscription(database):
    actor, workspace, _, _ = planned(database)
    subscription = "sub_" + uuid4().hex
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            for _ in range(2):
                bind_subscription(
                    connection,
                    workspace,
                    provider="stripe",
                    account_scope="self:test",
                    subscription_id=subscription,
                )
            with pytest.raises(ValueError, match="different billing authority"):
                bind_subscription(
                    connection,
                    workspace,
                    provider="razorpay",
                    account_scope="acc_fixture:test",
                    subscription_id=subscription,
                )
        with database.tenant(actor, workspace) as session, pytest.raises(PermissionError):
            bind_subscription(
                session,
                workspace,
                provider="stripe",
                account_scope="self:test",
                subscription_id=subscription,
            )
    finally:
        engine.dispose()
