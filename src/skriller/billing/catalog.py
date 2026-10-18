"""Persistent operator catalog and refresh entry points, with no tenant grants."""

import hashlib
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.billing.access import bindings, lock_workspace
from skriller.billing.events import InvalidBillingEvent, verify_event
from skriller.billing.inbox import inbox, receive
from skriller.billing.reconcile import Allowance, reconcile
from skriller.db.schema import metadata

catalog = sa.Table(
    "billing_workspace_catalog",
    metadata,
    sa.Column(
        "workspace_id",
        UUID(as_uuid=False),
        sa.ForeignKey("billing_bindings.workspace_id"),
        primary_key=True,
    ),
    sa.Column("customer_id", sa.String(192), nullable=False),
    sa.Column("plan_id", sa.String(192), nullable=False),
    sa.Column("runs", sa.Integer, nullable=False),
    sa.Column("results", sa.Integer, nullable=False),
    sa.Column("sources", sa.Integer, nullable=False),
    sa.Column("monthly", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.CheckConstraint(
        "runs BETWEEN 1 AND 1000 AND results BETWEEN 1 AND 100 AND sources BETWEEN 1 AND 9"
    ),
)


def configure(connection, workspace_id, allowance: Allowance):
    workspace_id = lock_workspace(connection, workspace_id)
    if (
        connection.execute(
            sa.select(bindings.c.workspace_id).where(bindings.c.workspace_id == workspace_id)
        ).scalar_one_or_none()
        is None
    ):
        raise LookupError("Billing binding unavailable")
    values = {
        key: getattr(allowance, key)
        for key in ("customer_id", "plan_id", "runs", "results", "sources", "monthly")
    }
    connection.execute(
        insert(catalog)
        .values(workspace_id=workspace_id, **values)
        .on_conflict_do_update(
            index_elements=["workspace_id"],
            set_=values,
        )
    )
    # A changed commercial/customer mapping needs a fresh authoritative read.
    connection.execute(
        sa.update(bindings)
        .where(bindings.c.workspace_id == workspace_id)
        .values(
            enabled=False,
            valid_until=None,
        )
    )


def load(connection, workspace_id):
    row = (
        connection.execute(sa.select(catalog).where(catalog.c.workspace_id == workspace_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Billing catalog unavailable")
    return Allowance(
        **{
            key: row[key]
            for key in ("customer_id", "plan_id", "runs", "results", "sources", "monthly")
        }
    )


def receive_bound(
    connection, provider, body, signature, *, secret, now, account_id=None, live_mode=False
):
    """Resolve workspace exclusively from the stored subscription authority.

    account_id/mode/secret are endpoint operator configuration, never parameters
    provided by the sender. Any workspace claim in the signed payload is ignored.
    """
    hint = verify_event(
        provider,
        body,
        signature,
        secret=secret,
        now=now,
        account_id=account_id,
        live_mode=live_mode,
    )
    if hint is None:
        return "ignored"
    account_scope = (account_id or "self") + (":live" if live_mode else ":test")
    if hint.subscription_id is None and hint.customer_id is None and hint.reference_id:
        from skriller.billing.references import receive_reference

        return receive_reference(connection, hint, account_scope)
    if hint.subscription_id is not None:
        binding_rows = (
            connection.execute(
                sa.select(bindings)
                .where(
                    bindings.c.provider == provider,
                    bindings.c.account_scope == account_scope,
                    bindings.c.subscription_id == hint.subscription_id,
                )
                .limit(2)
            )
            .mappings()
            .all()
        )
    elif hint.customer_id is not None:
        binding_rows = (
            connection.execute(
                sa.select(bindings)
                .join(catalog, catalog.c.workspace_id == bindings.c.workspace_id)
                .where(
                    bindings.c.provider == provider,
                    bindings.c.account_scope == account_scope,
                    catalog.c.customer_id == hint.customer_id,
                )
                .limit(2)
            )
            .mappings()
            .all()
        )
    else:
        binding_rows = []
    # Customer-only payment events are accepted only when they resolve to one
    # configured workspace/subscription. Ambiguity fails closed without a write.
    binding = binding_rows[0] if len(binding_rows) == 1 else None
    if binding is None and hint.checkout_id:
        from skriller.billing.checkout import CheckoutUnavailable, queue_checkout_event

        try:
            return queue_checkout_event(connection, hint, account_scope)
        except CheckoutUnavailable:
            raise InvalidBillingEvent() from None
    if binding is None:
        raise InvalidBillingEvent()
    # Ensure configured commercial ceilings exist before accepting work.
    load(connection, binding["workspace_id"])
    return receive(
        connection,
        provider,
        body,
        signature,
        secret=secret,
        now=now,
        workspace_id=binding["workspace_id"],
        subscription_id=binding["subscription_id"],
        customer_id=load(connection, binding["workspace_id"]).customer_id,
        account_id=account_id,
        live_mode=live_mode,
    )


def queue_refresh(connection, workspace_id):
    """Persist internal refresh work before provider I/O; operator authority only."""
    workspace_id = lock_workspace(connection, workspace_id)
    binding = (
        connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace_id))
        .mappings()
        .one_or_none()
    )
    if binding is None:
        raise LookupError("Billing binding unavailable")
    load(connection, workspace_id)
    event_key = "refresh_" + uuid4().hex
    connection.execute(
        sa.insert(inbox).values(
            provider=binding["provider"],
            account_scope=binding["account_scope"],
            event_key=event_key,
            workspace_id=workspace_id,
            subscription_id=binding["subscription_id"],
            payload_hash=hashlib.sha256(event_key.encode()).hexdigest(),
            event_type="internal.subscription.refresh",
        )
    )
    return event_key


def refresh(connection, workspace_id, *, fetch_current):
    """One operator refresh through the same serialization/audit path."""
    event_key = queue_refresh(connection, workspace_id)
    return reconcile(
        connection,
        workspace_id,
        event_key,
        allowance=load(connection, workspace_id),
        fetch_current=fetch_current,
    )
