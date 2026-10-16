"""Durable CRM delivery, adapted from the existing signed-webhook lease ledger.

Copied product claim/lease/retry structure from webhooks/service.py; delivery
uses the copied-export qualification path and native Salesforce external ID.
"""

import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa

from skriller.crm.salesforce import (
    SalesforceAuthorizationExpired,
    SalesforceUnavailable,
    prepare_leads,
    upsert_lead,
)
from skriller.crm.store import DestinationStore
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.db.schema import scoped
from skriller.erasure import privacy_lock
from skriller.storage import BlobUnavailable

deliveries = scoped(
    "crm_deliveries",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("destination_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("destination_generation", sa.Integer, nullable=False),
    sa.Column("plan_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("entity_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("selected_near", sa.Boolean, nullable=False),
    sa.Column("field_map", sa.JSON, nullable=False),
    sa.Column("idempotency_key", sa.String(100), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("lease_token", sa.Uuid(as_uuid=False)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("last_code", sa.String(40)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "destination_id"],
            ["crm_destinations.workspace_id", "crm_destinations.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.UniqueConstraint("workspace_id", "created_by", "idempotency_key"),
    ),
)


def public(row):
    return {
        key: row[key]
        for key in ("id", "destination_id", "entity_id", "state", "attempts", "last_code")
    }


def enqueue(
    session,
    storage,
    store: DestinationStore,
    destination_id,
    plan_id,
    entity_id,
    *,
    field_map,
    selected_near=False,
    idempotency_key,
    opt_in=False,
):
    require_owner(session)
    if (
        opt_in is not True
        or type(selected_near) is not bool
        or not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= 100
    ):
        raise ValueError("Explicit CRM selection and bounded idempotency key required")
    destination_id, plan_id, entity_id = (
        str(UUID(str(value))) for value in (destination_id, plan_id, entity_id)
    )
    privacy_lock(session)
    destination = store.get(session, destination_id, lock=True)
    store.credentials(session, destination_id, generation=destination["generation"])
    digest = hashlib.sha256(
        json.dumps(
            [
                destination_id,
                destination["generation"],
                plan_id,
                entity_id,
                selected_near,
                field_map,
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "crm-queue:" + scope(session)},
    )
    existing = (
        session.execute(
            sa.select(deliveries).where(
                deliveries.c.workspace_id == scope(session),
                deliveries.c.created_by == session.info["actor_id"],
                deliveries.c.idempotency_key == idempotency_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["request_hash"] != digest:
            raise ValueError("CRM idempotency key has different intent")
        return public(existing)
    count = session.execute(
        sa.select(sa.func.count())
        .select_from(deliveries)
        .where(
            deliveries.c.workspace_id == scope(session),
            deliveries.c.state.in_(("pending", "delivering")),
        )
    ).scalar_one()
    if count >= 100:
        raise ValueError("CRM pending selection limit reached")
    prepare_leads(
        session,
        storage,
        plan_id,
        (entity_id,),
        field_map=field_map,
        selected_near_ids=(entity_id,) if selected_near else (),
        opt_in=True,
    )
    return public(
        insert_row(
            session,
            deliveries,
            created_by=session.info["actor_id"],
            destination_id=destination_id,
            destination_generation=destination["generation"],
            plan_id=plan_id,
            entity_id=entity_id,
            selected_near=selected_near,
            field_map=field_map,
            idempotency_key=idempotency_key,
            request_hash=digest,
        )
    )


def claim(session):
    require_owner(session)
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    row = (
        session.execute(
            sa.select(deliveries)
            .where(
                deliveries.c.workspace_id == scope(session),
                deliveries.c.state.in_(("pending", "delivering")),
                deliveries.c.next_attempt_at <= now,
                sa.or_(
                    deliveries.c.lease_expires_at.is_(None), deliveries.c.lease_expires_at <= now
                ),
            )
            .order_by(deliveries.c.next_attempt_at, deliveries.c.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row["attempts"] >= 5:
        session.execute(
            sa.update(deliveries)
            .where(deliveries.c.workspace_id == scope(session), deliveries.c.id == row["id"])
            .values(
                state="failed", last_code="attempt_limit", lease_token=None, lease_expires_at=None
            )
        )
        return None
    token = str(uuid4())
    session.execute(
        sa.update(deliveries)
        .where(deliveries.c.workspace_id == scope(session), deliveries.c.id == row["id"])
        .values(
            state="delivering",
            attempts=row["attempts"] + 1,
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=45),
        )
    )
    return {"id": row["id"], "lease_token": token}


def deliver(session, task, storage, store: DestinationStore, *, send=upsert_lead):
    """Hold privacy and destination locks through a single bounded native upsert."""
    require_owner(session)
    privacy_lock(session)
    row = (
        session.execute(
            sa.select(deliveries)
            .where(
                deliveries.c.workspace_id == scope(session),
                deliveries.c.id == str(UUID(task["id"])),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if (
        row is None
        or row["state"] != "delivering"
        or row["lease_token"] != task["lease_token"]
        or row["lease_expires_at"] <= now
    ):
        return "stale"
    state, code = "failed", "selection_unavailable"
    try:
        leads = prepare_leads(
            session,
            storage,
            row["plan_id"],
            (row["entity_id"],),
            field_map=row["field_map"],
            selected_near_ids=(row["entity_id"],) if row["selected_near"] else (),
            opt_in=True,
        )
        instance, token = store.credentials(
            session, row["destination_id"], generation=row["destination_generation"]
        )
        current = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if row["lease_expires_at"] <= current + timedelta(seconds=15):
            raise SalesforceUnavailable()
        code = send(instance, token, leads[0])
        if code not in {"created", "updated"}:
            raise SalesforceUnavailable()
        state = "succeeded"
    except (BlobUnavailable, ValueError):
        state, code = "suppressed", "selection_unavailable"
    except SalesforceAuthorizationExpired:
        # Stop using a token rejected before our conservative local TTL. The
        # next bounded queue attempt refreshes OAuth first; never replay PATCH
        # immediately inside the delivery transaction.
        from skriller.crm.store import destinations

        session.execute(
            sa.update(destinations)
            .where(
                destinations.c.workspace_id == scope(session),
                destinations.c.id == row["destination_id"],
            )
            .values(expires_at=now)
        )
        state, code = ("pending" if row["attempts"] < 5 else "failed"), "authorization_expired"
    except SalesforceUnavailable:
        state, code = ("pending" if row["attempts"] < 5 else "failed"), "destination_unavailable"
    session.execute(
        sa.update(deliveries)
        .where(deliveries.c.workspace_id == scope(session), deliveries.c.id == row["id"])
        .values(
            state=state,
            last_code=code,
            next_attempt_at=now + timedelta(seconds=min(60 * 2 ** (row["attempts"] - 1), 900)),
            lease_token=None,
            lease_expires_at=None,
        )
    )
    return state
