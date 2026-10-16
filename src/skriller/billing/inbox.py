"""Operator-only durable reconciliation inbox, separate from tenant privileges.

Verified events enqueue work only. This module intentionally cannot mutate
entitlements; subscription fetching and authoritative paid-access fences must
be wired before a webhook endpoint is enabled.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.billing.events import InvalidBillingEvent, verify_event
from skriller.db.schema import metadata

inbox = sa.Table(
    "billing_event_inbox",
    metadata,
    sa.Column("provider", sa.String(16), primary_key=True),
    sa.Column("account_scope", sa.String(192), primary_key=True),
    sa.Column("event_key", sa.String(192), primary_key=True),
    sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False),
    sa.Column("subscription_id", sa.String(192), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("event_type", sa.String(80), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("provider IN ('stripe','razorpay')"),
    sa.CheckConstraint("state IN ('pending','reconciled','quarantined')"),
    sa.CheckConstraint("attempt_count BETWEEN 0 AND 5", name="billing_attempt_bounds"),
)


def receive(
    connection,
    provider,
    body,
    signature,
    *,
    secret,
    now,
    workspace_id,
    subscription_id,
    customer_id=None,
    account_id=None,
    live_mode=False,
):
    """Server-owned endpoint binding supplies workspace/account/subscription.

    Binding values must come from operator configuration, never webhook metadata
    or query parameters. Restricted application DB roles have no inbox grants.
    No raw payload, contact data, secret, or payment data is retained.
    """
    hint = verify_event(
        provider,
        body,
        signature,
        secret=secret,
        now=now,
        live_mode=live_mode,
        account_id=account_id,
    )
    if hint is None:
        return "ignored"
    if hint.subscription_id is not None and hint.subscription_id != subscription_id:
        raise InvalidBillingEvent()
    if hint.subscription_id is None and (customer_id is None or hint.customer_id != customer_id):
        raise InvalidBillingEvent()
    if hint.customer_id is not None and hint.customer_id != customer_id:
        raise InvalidBillingEvent()
    account_scope = (account_id or "self") + (":live" if live_mode else ":test")
    if len(account_scope) > 192:
        raise InvalidBillingEvent()
    key = {"provider": provider, "account_scope": account_scope, "event_key": hint.event_key}
    inserted = connection.execute(
        insert(inbox)
        .values(
            **key,
            workspace_id=workspace_id,
            subscription_id=subscription_id,
            payload_hash=hint.payload_hash,
            event_type=hint.event_type,
        )
        .on_conflict_do_nothing()
        .returning(inbox.c.event_key)
    ).scalar_one_or_none()
    if inserted is not None:
        return "queued"
    original = (
        connection.execute(
            sa.select(inbox).where(*(inbox.c[name] == value for name, value in key.items()))
        )
        .mappings()
        .one()
    )
    if (
        original["payload_hash"] != hint.payload_hash
        or str(original["workspace_id"]) != str(workspace_id)
        or original["subscription_id"] != subscription_id
    ):
        raise InvalidBillingEvent()
    return "duplicate"
