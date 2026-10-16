"""Serialized billing reconciliation; event snapshots never decide access."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.billing.access import bindings, lock_workspace
from skriller.billing.inbox import inbox
from skriller.db.schema import metadata
from skriller.entitlements import policies

audit = sa.Table(
    "billing_reconciliations",
    metadata,
    sa.Column("id", UUID(as_uuid=False), primary_key=True),
    sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False),
    sa.Column("provider", sa.String(16), nullable=False),
    sa.Column("event_key", sa.String(192), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("access_enabled", sa.Boolean, nullable=False),
    sa.Column("valid_until", sa.DateTime(timezone=True)),
    sa.Column("plan_id", sa.String(192), nullable=False),
    sa.Column("allowance", sa.JSON),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


@dataclass(frozen=True)
class Allowance:
    """Explicit server catalog entry: finite lifetime pilot ceiling, no resets."""

    plan_id: str
    customer_id: str
    runs: int
    results: int
    sources: int
    monthly: bool = False

    def __post_init__(self):
        if (
            not 1 <= len(self.plan_id) <= 192
            or not 1 <= len(self.customer_id) <= 192
            or type(self.runs) is not int
            or not 1 <= self.runs <= 1000
            or type(self.results) is not int
            or not 1 <= self.results <= 100
            or type(self.sources) is not int
            or not 1 <= self.sources <= 9
            or type(self.monthly) is not bool
        ):
            raise ValueError("Explicit finite billing catalog required")


@dataclass(frozen=True)
class CurrentSubscription:
    """Trusted provider client output, never constructed from the webhook body."""

    subscription_id: str
    account_scope: str
    customer_id: str
    plan_id: str
    status: str
    paid: bool
    period_end: datetime | None
    period_start: datetime | None = None


def reconcile(connection, workspace_id, event_key, *, allowance: Allowance, fetch_current):
    """Operator transaction owns all writes; fetch must be bounded and read-only.

    Lock before retrieval so concurrent/delayed event workers cannot apply an
    older retrieval after a newer one. Access leases last at most fifteen minutes
    and require periodic current-state refresh; a missing worker fails closed.
    Neither quota admissions nor the owner's enabled/pause choice are reset.
    """
    workspace_id = lock_workspace(connection, workspace_id)
    binding = (
        connection.execute(
            sa.select(bindings)
            .where(
                bindings.c.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if binding is None:
        raise LookupError("Billing binding unavailable")
    event = (
        connection.execute(
            sa.select(inbox)
            .where(
                inbox.c.workspace_id == workspace_id,
                inbox.c.provider == binding["provider"],
                inbox.c.account_scope == binding["account_scope"],
                inbox.c.event_key == event_key,
                inbox.c.subscription_id == binding["subscription_id"],
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if event is None:
        raise LookupError("Billing event unavailable")
    if event["state"] != "pending":
        return "already_processed"
    current = fetch_current(dict(binding))
    if (
        not isinstance(current, CurrentSubscription)
        or current.subscription_id != binding["subscription_id"]
        or current.account_scope != binding["account_scope"]
        or current.customer_id != allowance.customer_id
        or current.plan_id != allowance.plan_id
        or current.status
        not in {
            "active",
            "canceled",
            "cancelled",
            "completed",
            "expired",
            "trialing",
            "past_due",
            "unpaid",
            "paused",
            "pending",
            "halted",
            "created",
            "authenticated",
            "incomplete",
            "incomplete_expired",
        }
        or type(current.paid) is not bool
        or (
            current.period_end is not None
            and (not isinstance(current.period_end, datetime) or current.period_end.tzinfo is None)
        )
    ):
        raise ValueError("Authoritative subscription does not match billing binding/catalog")
    now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    provider_paid_active = (
        current.status == "active"
        and current.paid
        and current.period_end is not None
        and current.period_end > now
    )
    event_type = event["event_type"]
    confirmed_hold = event_type in {
        "billing.dispute.open",
        "billing.dispute.lost",
    } or event_type.endswith((".full_refund", ":full"))
    # A verified full refund or open/lost dispute pauses this reconciliation
    # even if the subscription snapshot itself still appears active. A later
    # provider refresh may restore access only from current active/paid state.
    enabled = provider_paid_active and not confirmed_hold
    valid_until = min(current.period_end, now + timedelta(minutes=15)) if enabled else None
    window: dict[str, datetime | None] = {}
    if enabled and allowance.monthly:
        if (
            current.period_end is None
            or current.period_start is None
            or current.period_start.tzinfo is None
            or not current.period_start <= now < current.period_end
            or current.period_end - current.period_start > timedelta(days=32)
            or (
                binding["period_start"] is not None
                and current.period_start < binding["period_start"]
            )
        ):
            raise ValueError("Verified monthly subscription period required")
        # Provider periods, never event timestamps, define the quota window.
        window = {"period_start": current.period_start, "period_end": current.period_end}
    elif enabled:
        window = {"period_start": None, "period_end": None}
    connection.execute(
        sa.update(bindings)
        .where(bindings.c.workspace_id == workspace_id)
        .values(
            enabled=enabled,
            valid_until=valid_until,
            updated_at=now,
            **window,
        )
    )
    if enabled:
        values = {
            "workspace_id": workspace_id,
            "tier": "pilot",
            "run_limit": allowance.runs,
            "result_cap": allowance.results,
            "source_cap": allowance.sources,
            "result_limit": allowance.results,
            "source_limit": allowance.sources,
            "enabled": True,
            "invoice_reference": "billing:" + str(uuid4()),
            "updated_by": "operator:billing",
        }
        statement = insert(policies).values(**values)
        # A user pause and lower per-run settings survive paid-state updates.
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={
                    **{
                        key: values[key]
                        for key in (
                            "tier",
                            "run_limit",
                            "result_cap",
                            "source_cap",
                            "invoice_reference",
                            "updated_by",
                        )
                    },
                    "result_limit": sa.func.least(policies.c.result_limit, allowance.results),
                    "source_limit": sa.func.least(policies.c.source_limit, allowance.sources),
                },
            )
        )
    connection.execute(
        sa.insert(audit).values(
            id=str(uuid4()),
            workspace_id=workspace_id,
            provider=binding["provider"],
            event_key=event_key,
            status=current.status,
            access_enabled=enabled,
            valid_until=valid_until,
            plan_id=current.plan_id,
            allowance={
                "runs": allowance.runs,
                "results": allowance.results,
                "sources": allowance.sources,
                "monthly": allowance.monthly,
                "billing_action": event_type,
                "period_start": current.period_start.isoformat() if current.period_start else None,
                "period_end": current.period_end.isoformat() if current.period_end else None,
            },
        )
    )
    connection.execute(
        sa.update(inbox)
        .where(
            inbox.c.provider == event["provider"],
            inbox.c.account_scope == event["account_scope"],
            inbox.c.event_key == event_key,
        )
        .values(state="reconciled")
    )
    return "enabled" if enabled else "disabled"
