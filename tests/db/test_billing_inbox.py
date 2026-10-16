import hmac
import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.billing.events import InvalidBillingEvent
from skriller.billing.inbox import inbox, receive
from skriller.entitlements import policy_for
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
SECRET = b"fixture-billing-secret-only"
NOW = 1800000000


def event(event_id, status="active"):
    body = json.dumps(
        {
            "id": event_id,
            "type": "customer.subscription.updated",
            "livemode": False,
            "data": {"object": {"id": "sub_fixture", "object": "subscription", "status": status}},
        }
    ).encode()
    digest = hmac.new(SECRET, str(NOW).encode() + b"." + body, "sha256").hexdigest()
    return body, f"t={NOW},v1={digest}"


def test_durable_duplicate_forgery_and_conflicting_replay_do_not_change_access(database):
    actor = "billing-" + uuid4().hex
    workspace = database.create_workspace(actor, "Billing fixture")["id"]
    with database.tenant(actor, workspace) as session:
        before = dict(policy_for(session))
    engine = sa.create_engine(Settings().database_url)
    event_id = "evt_" + uuid4().hex
    body, signature = event(event_id)
    arguments = {
        "secret": SECRET,
        "now": NOW,
        "workspace_id": workspace,
        "subscription_id": "sub_fixture",
    }
    try:
        with engine.begin() as connection:
            assert receive(connection, "stripe", body, signature, **arguments) == "queued"
        with engine.begin() as connection:
            assert receive(connection, "stripe", body, signature, **arguments) == "duplicate"
        with engine.begin() as connection, pytest.raises(InvalidBillingEvent):
            receive(connection, "stripe", body, "t=0,v1=forged", **arguments)
        altered, altered_signature = event(event_id, status="canceled")
        with engine.begin() as connection, pytest.raises(InvalidBillingEvent):
            receive(connection, "stripe", altered, altered_signature, **arguments)
        with engine.begin() as connection:
            rows = (
                connection.execute(sa.select(inbox).where(inbox.c.workspace_id == workspace))
                .mappings()
                .all()
            )
            assert len(rows) == 1 and rows[0]["state"] == "pending"
            assert "body" not in rows[0] and "secret" not in rows[0]
        with database.tenant(actor, workspace) as session:
            assert dict(policy_for(session)) == before
        with database.tenant(actor, workspace) as session, pytest.raises(DBAPIError):
            session.execute(sa.select(inbox))
    finally:
        engine.dispose()


def test_bound_subscription_required_and_duplicate_cannot_be_rebound(database):
    actor = "billing-binding-" + uuid4().hex
    first = database.create_workspace(actor, "First billing")["id"]
    second = database.create_workspace(actor, "Second billing")["id"]
    engine = sa.create_engine(Settings().database_url)
    body, signature = event("evt_" + uuid4().hex)
    try:
        with engine.begin() as connection, pytest.raises(InvalidBillingEvent):
            receive(
                connection,
                "stripe",
                body,
                signature,
                secret=SECRET,
                now=NOW,
                workspace_id=first,
                subscription_id="sub_unbound",
            )
        with engine.begin() as connection:
            receive(
                connection,
                "stripe",
                body,
                signature,
                secret=SECRET,
                now=NOW,
                workspace_id=first,
                subscription_id="sub_fixture",
            )
        with engine.begin() as connection, pytest.raises(InvalidBillingEvent):
            receive(
                connection,
                "stripe",
                body,
                signature,
                secret=SECRET,
                now=NOW,
                workspace_id=second,
                subscription_id="sub_fixture",
            )
    finally:
        engine.dispose()
