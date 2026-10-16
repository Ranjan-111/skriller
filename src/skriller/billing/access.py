"""Operator-owned subscription authority, independent of owner pause settings."""

from uuid import UUID as UUIDValue

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from skriller.db.schema import metadata

bindings = sa.Table(
    "billing_bindings",
    metadata,
    sa.Column(
        "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
    ),
    sa.Column("provider", sa.String(16), nullable=False),
    sa.Column("account_scope", sa.String(192), nullable=False),
    sa.Column("subscription_id", sa.String(192), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("valid_until", sa.DateTime(timezone=True)),
    sa.Column("period_start", sa.DateTime(timezone=True)),
    sa.Column("period_end", sa.DateTime(timezone=True)),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("provider", "account_scope", "subscription_id"),
    sa.CheckConstraint("provider IN ('stripe','razorpay')"),
    sa.CheckConstraint("NOT enabled OR valid_until IS NOT NULL"),
)


def operator(connection):
    allowed = connection.execute(
        sa.text("""SELECT r.rolsuper OR c.relowner=r.oid
      FROM pg_roles r,pg_class c WHERE r.rolname=current_user
      AND c.oid='billing_bindings'::regclass""")
    ).scalar_one()
    if not allowed:
        raise PermissionError("Billing operator role required")


def lock_workspace(connection, workspace_id):
    operator(connection)
    workspace_id = str(UUIDValue(str(workspace_id)))
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "entitlement:" + workspace_id},
    )
    # Same policy-row ordering as the independent admission trigger. Do not
    # acquire a job lock here: admission locks job before workspace policy.
    connection.execute(
        sa.text(
            "SELECT workspace_id FROM workspace_entitlements "
            "WHERE workspace_id=:workspace FOR UPDATE"
        ),
        {"workspace": workspace_id},
    )
    return workspace_id


def bind_subscription(connection, workspace_id, *, provider, account_scope, subscription_id):
    """Explicit operator binding starts disabled. Rebinding requires separate review.

    One billing authority per workspace prevents stacking Stripe/Razorpay grants.
    There is deliberately no tenant-callable binding or enable function.
    """
    import re

    workspace_id = lock_workspace(connection, workspace_id)
    if (
        provider not in {"stripe", "razorpay"}
        or not re.fullmatch(r"[A-Za-z0-9_]{1,180}:(test|live)", account_scope)
        or not re.fullmatch(r"sub_[A-Za-z0-9_]{1,180}", subscription_id)
    ):
        raise ValueError("Valid server-owned subscription binding required")
    existing = (
        connection.execute(
            sa.select(bindings).where(
                bindings.c.workspace_id == workspace_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    identity = {
        "provider": provider,
        "account_scope": account_scope,
        "subscription_id": subscription_id,
    }
    if existing:
        if any(existing[key] != value for key, value in identity.items()):
            raise ValueError("Workspace already has a different billing authority")
        return
    connection.execute(sa.insert(bindings).values(workspace_id=workspace_id, **identity))
