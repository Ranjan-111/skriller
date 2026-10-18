"""Owner-authorized initial checkout intents; remote writes are never blindly retried."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from skriller.billing.access import bind_subscription, bindings, lock_workspace, operator
from skriller.billing.plans import PLANS, allowance_for
from skriller.billing.provisioning import remote_plans
from skriller.db.schema import memberships, metadata

RAZORPAY_CYCLES = 12  # User approved 2026-10-17; monthly, not an upfront charge.


class CheckoutUnavailable(ValueError):
    def __init__(self):
        super().__init__("Checkout unavailable or requires operator reconciliation")


@dataclass(frozen=True)
class CheckoutConfiguration:
    firebase_project_id: str
    return_origin: str

    def __post_init__(self):
        url = urlsplit(self.return_origin)
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", self.firebase_project_id)
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path
            or not url.hostname
            or self.return_origin != url.geturl()
            or not (
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}", url.hostname)
                or url.hostname == "::1"
            )
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
        ):
            raise CheckoutUnavailable()
        # Accessing port also validates malformed or out-of-range ports.
        _ = url.port


intents = sa.Table(
    "billing_checkout_intents",
    metadata,
    sa.Column("id", PGUUID(as_uuid=False), primary_key=True),
    sa.Column(
        "workspace_id",
        PGUUID(as_uuid=False),
        sa.ForeignKey("workspaces.id"),
        nullable=False,
        unique=True,
    ),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("provider", sa.String(16), nullable=False),
    sa.Column("account_scope", sa.String(192), nullable=False),
    sa.Column("slug", sa.String(16), nullable=False),
    sa.Column("plan_id", sa.String(192), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, server_default="dispatching"),
    sa.Column("remote_id", sa.String(192)),
    sa.Column("checkout_url", sa.String(4096)),
    sa.Column("subscription_id", sa.String(192)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("provider IN ('stripe','razorpay')"),
    sa.CheckConstraint("slug IN ('starter','pro')"),
    sa.CheckConstraint("state IN ('dispatching','ready','uncertain','bound')"),
)


def require_checkout_owner(connection, workspace, actor):
    operator(connection)
    if not isinstance(actor, str) or not 1 <= len(actor) <= 128:
        raise CheckoutUnavailable()
    workspace = str(UUID(str(workspace)))
    if (
        connection.execute(
            sa.select(memberships.c.role).where(
                memberships.c.workspace_id == workspace,
                memberships.c.actor_id == actor,
                memberships.c.role == "owner",
            )
        ).scalar_one_or_none()
        is None
    ):
        raise CheckoutUnavailable()
    return workspace


def view(connection, workspace, actor, identifier):
    require_checkout_owner(connection, workspace, actor)
    row = (
        connection.execute(
            sa.select(intents).where(
                intents.c.id == str(UUID(str(identifier))),
                intents.c.workspace_id == str(workspace),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CheckoutUnavailable()
    now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if row["expires_at"] <= now and row["state"] in {"dispatching", "ready"}:
        # Expiry cannot prove that a native purchase did not occur. Stop waiting
        # and retire the link, but never permit a second automatic purchase.
        connection.execute(
            sa.update(intents)
            .where(
                intents.c.id == row["id"],
                intents.c.state.in_(("dispatching", "ready")),
                intents.c.expires_at <= now,
            )
            .values(state="uncertain", checkout_url=None)
        )
        row = (
            connection.execute(sa.select(intents).where(intents.c.id == row["id"])).mappings().one()
        )
    return {
        "id": row["id"],
        "provider": row["provider"],
        "plan": row["slug"],
        "state": row["state"],
        "expires_at": row["expires_at"],
        "checkout_url": row["checkout_url"]
        if row["state"] == "ready" and row["expires_at"] > now
        else None,
        "maximum_monthly_cycles": RAZORPAY_CYCLES if row["provider"] == "razorpay" else None,
    }


def create_checkout(
    engine, config, options, workspace, actor, slug, idempotency_key, *, opt_in, transport=None
):
    from skriller.billing.checkout_http import create_remote

    if (
        opt_in is not True
        or slug not in PLANS
        or not isinstance(idempotency_key, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", idempotency_key)
    ):
        raise CheckoutUnavailable()
    config.__post_init__()
    options.__post_init__()
    digest = hashlib.sha256(
        json.dumps(
            [
                config.provider,
                config.scope,
                str(workspace),
                actor,
                slug,
                idempotency_key,
                options.return_origin,
                RAZORPAY_CYCLES,
            ]
        ).encode()
    ).hexdigest()
    with engine.begin() as connection:
        workspace = require_checkout_owner(connection, workspace, actor)
        lock_workspace(connection, workspace)
        existing = (
            connection.execute(sa.select(intents).where(intents.c.workspace_id == workspace))
            .mappings()
            .one_or_none()
        )
        if existing:
            if existing["request_hash"] != digest:
                raise CheckoutUnavailable()
            return view(connection, workspace, actor, existing["id"])
        if connection.execute(
            sa.select(bindings).where(bindings.c.workspace_id == workspace)
        ).first():
            raise CheckoutUnavailable()
        plan_id = connection.execute(
            sa.select(remote_plans.c.remote_id).where(
                remote_plans.c.provider == config.provider,
                remote_plans.c.account_scope == config.scope,
                remote_plans.c.slug == slug,
                remote_plans.c.state == "ready",
            )
        ).scalar_one_or_none()
        if not plan_id or not re.fullmatch(
            ("price_" if config.provider == "stripe" else "plan_") + r"[A-Za-z0-9_]{1,180}", plan_id
        ):
            raise CheckoutUnavailable()
        now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        row = {
            "id": str(uuid4()),
            "workspace_id": workspace,
            "created_by": actor,
            "provider": config.provider,
            "account_scope": config.scope,
            "slug": slug,
            "plan_id": plan_id,
            "request_hash": digest,
            "state": "dispatching",
            "expires_at": now + timedelta(minutes=35),
        }
        connection.execute(sa.insert(intents).values(**row))
    # Intent commits before the first POST. A crash/timeout never authorizes replay.
    try:
        remote_id, url = create_remote(config, options, row, transport=transport)
    except Exception:  # noqa: BLE001 - do not expose provider bodies or keys
        with engine.begin() as connection:
            connection.execute(
                sa.update(intents).where(intents.c.id == row["id"]).values(state="uncertain")
            )
    else:
        with engine.begin() as connection:
            connection.execute(
                sa.update(intents)
                .where(intents.c.id == row["id"], intents.c.state == "dispatching")
                .values(state="ready", remote_id=remote_id, checkout_url=url)
            )
            # A suspended caller may finish after expiry was observed. Preserve
            # its verified receipt for reconciliation without reviving a link.
            connection.execute(
                sa.update(intents)
                .where(
                    intents.c.id == row["id"],
                    intents.c.state == "uncertain",
                    intents.c.remote_id.is_(None),
                )
                .values(remote_id=remote_id)
            )
    with engine.begin() as connection:
        return view(connection, workspace, actor, row["id"])


def queue_checkout_event(connection, hint, scope):
    from skriller.billing.references import receive_reference

    row = (
        connection.execute(
            sa.select(intents).where(
                intents.c.id == hint.checkout_id,
                intents.c.provider == hint.provider,
                intents.c.account_scope == scope,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not hint.subscription_id:
        raise CheckoutUnavailable()
    return receive_reference(connection, hint, scope, checkout=True)


def load_intent(connection, identifier, config):
    row = (
        connection.execute(
            sa.select(intents).where(
                intents.c.id == identifier,
                intents.c.provider == config.provider,
                intents.c.account_scope == config.scope,
            )
        )
        .mappings()
        .one()
    )
    if row["state"] not in {"ready", "bound", "uncertain"} or not row["remote_id"]:
        raise CheckoutUnavailable()
    return dict(row)


def bind_checkout(connection, row, current, expected_subscription):
    from skriller.billing.catalog import configure

    if current.subscription_id != expected_subscription or not current.customer_id:
        raise CheckoutUnavailable()
    workspace = require_checkout_owner(connection, row["workspace_id"], row["created_by"])
    lock_workspace(connection, workspace)
    bind_subscription(
        connection,
        workspace,
        provider=row["provider"],
        account_scope=row["account_scope"],
        subscription_id=current.subscription_id,
    )
    saved = (
        connection.execute(sa.select(intents).where(intents.c.id == row["id"]).with_for_update())
        .mappings()
        .one()
    )
    if saved["state"] == "bound" and saved["subscription_id"] != current.subscription_id:
        raise CheckoutUnavailable()
    if saved["state"] != "bound":
        configure(
            connection, workspace, allowance_for(row["slug"], row["plan_id"], current.customer_id)
        )
        connection.execute(
            sa.update(intents)
            .where(intents.c.id == row["id"])
            .values(state="bound", subscription_id=current.subscription_id, checkout_url=None)
        )
    return (
        connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace))
        .mappings()
        .one()
    )
