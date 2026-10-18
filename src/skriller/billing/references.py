"""Durable verified payment references, resolved before subscription reconciliation."""

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.billing.access import bindings, operator
from skriller.billing.events import InvalidBillingEvent
from skriller.billing.inbox import inbox
from skriller.db.schema import metadata

references = sa.Table(
    "billing_event_references",
    metadata,
    sa.Column("provider", sa.String(16), primary_key=True),
    sa.Column("account_scope", sa.String(192), primary_key=True),
    sa.Column("event_key", sa.String(192), primary_key=True),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column("event_type", sa.String(80), nullable=False),
    sa.Column("reference_id", sa.String(192), nullable=False),
    sa.Column("checkout_id", UUID(as_uuid=False), sa.ForeignKey("billing_checkout_intents.id")),
    sa.Column("expected_subscription_id", sa.String(192)),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("provider IN ('stripe','razorpay')"),
    sa.CheckConstraint("state IN ('pending','resolved','quarantined')"),
    sa.CheckConstraint("attempt_count BETWEEN 0 AND 5"),
    sa.CheckConstraint(
        "(checkout_id IS NULL)=(expected_subscription_id IS NULL)", name="checkout_reference_pair"
    ),
)


def receive_reference(connection, hint, account_scope, *, checkout=False):
    operator(connection)
    if checkout:
        if not hint.checkout_id or not hint.subscription_id:
            raise InvalidBillingEvent()
    elif not hint.reference_id or hint.subscription_id or hint.customer_id:
        raise InvalidBillingEvent()
    key = {"provider": hint.provider, "account_scope": account_scope, "event_key": hint.event_key}
    values = {name: getattr(hint, name) for name in ("payload_hash", "event_type", "reference_id")}
    values.update(
        reference_id=hint.checkout_id if checkout else hint.reference_id,
        checkout_id=hint.checkout_id if checkout else None,
        expected_subscription_id=hint.subscription_id if checkout else None,
    )
    inserted = connection.execute(
        insert(references)
        .values(**key, **values)
        .on_conflict_do_nothing()
        .returning(references.c.event_key)
    ).scalar_one_or_none()
    if inserted is not None:
        return "queued"
    row = (
        connection.execute(
            sa.select(references).where(
                *(references.c[name] == value for name, value in key.items())
            )
        )
        .mappings()
        .one()
    )
    if any(row[name] != value for name, value in values.items()):
        raise InvalidBillingEvent()
    return "duplicate"


def _resolve(connection, row, config, fetch, checkout_fetch):
    from skriller.billing.catalog import catalog
    from skriller.billing.providers import PaymentReference

    key = {name: row[name] for name in ("provider", "account_scope", "event_key")}
    where = tuple(references.c[name] == value for name, value in key.items())
    lock = "billing-reference:" + ":".join(key.values())
    held = connection.execute(
        sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": lock}
    ).scalar_one()
    connection.commit()
    if not held:
        return "reference_busy"
    try:
        with connection.begin():
            row = connection.execute(sa.select(references).where(*where)).mappings().one()
            now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            if row["state"] != "pending" or row["next_attempt_at"] > now:
                return "reference_deferred"
            if row["attempt_count"] >= 5:
                connection.execute(sa.update(references).where(*where).values(state="quarantined"))
                return "reference_quarantined"
            attempt = row["attempt_count"] + 1
            connection.execute(
                sa.update(references)
                .where(*where)
                .values(
                    attempt_count=attempt,
                    next_attempt_at=now + timedelta(seconds=min(60 * 2 ** (attempt - 1), 900)),
                )
            )
        try:
            intent = None
            if row["checkout_id"]:
                from skriller.billing.checkout import load_intent
                from skriller.billing.checkout_http import fetch_checkout

                with connection.begin():
                    intent = load_intent(connection, row["checkout_id"], config)
                current = (checkout_fetch or fetch_checkout)(config, intent)
            else:
                current = fetch(config, row["reference_id"])
            if not isinstance(current, PaymentReference):
                raise InvalidBillingEvent()
            with connection.begin():
                if intent is not None:
                    from skriller.billing.checkout import bind_checkout

                    binding = bind_checkout(
                        connection, intent, current, row["expected_subscription_id"]
                    )
                else:
                    query = (
                        sa.select(bindings)
                        .join(catalog, catalog.c.workspace_id == bindings.c.workspace_id)
                        .where(
                            bindings.c.provider == row["provider"],
                            bindings.c.account_scope == row["account_scope"],
                        )
                    )
                    if current.customer_id is not None:
                        query = query.where(catalog.c.customer_id == current.customer_id)
                    if current.subscription_id is not None:
                        query = query.where(bindings.c.subscription_id == current.subscription_id)
                    matches = connection.execute(query.limit(2)).mappings().all()
                    if len(matches) != 1:
                        raise InvalidBillingEvent()
                    binding = matches[0]
                values = dict(
                    key,
                    workspace_id=binding["workspace_id"],
                    subscription_id=binding["subscription_id"],
                    payload_hash=row["payload_hash"],
                    event_type=row["event_type"],
                )
                connection.execute(insert(inbox).values(**values).on_conflict_do_nothing())
                saved = (
                    connection.execute(
                        sa.select(inbox).where(
                            *(inbox.c[name] == value for name, value in key.items())
                        )
                    )
                    .mappings()
                    .one()
                )
                if any(saved[name] != value for name, value in values.items()):
                    raise InvalidBillingEvent()
                connection.execute(sa.update(references).where(*where).values(state="resolved"))
            return "reference_resolved"
        except Exception:  # noqa: BLE001 - retain attempt, no provider payload in diagnostics
            connection.rollback()
            if attempt == 5:
                with connection.begin():
                    connection.execute(
                        sa.update(references).where(*where).values(state="quarantined")
                    )
            return "reference_retry" if attempt < 5 else "reference_quarantined"
    finally:
        connection.rollback()
        connection.execute(
            sa.text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": lock}
        )
        connection.commit()


def resolve_pending(engine, configs, *, limit, fetch, checkout_fetch=None):
    if type(limit) is not int or not 1 <= limit <= 10 or not 1 <= len(configs) <= 8:
        raise ValueError("Bounded billing reference batch required")
    with engine.begin() as connection:
        operator(connection)
        rows = (
            connection.execute(
                sa.select(references)
                .where(
                    references.c.state == "pending",
                    references.c.next_attempt_at <= sa.func.clock_timestamp(),
                    sa.or_(
                        *(
                            sa.and_(
                                references.c.provider == provider,
                                references.c.account_scope == scope,
                            )
                            for provider, scope in configs
                        )
                    ),
                )
                .order_by(references.c.received_at, references.c.event_key)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    statuses = []
    for row in rows:
        with engine.connect() as connection:
            statuses.append(
                _resolve(
                    connection,
                    row,
                    configs[(row["provider"], row["account_scope"])],
                    fetch,
                    checkout_fetch,
                )
            )
    return statuses
