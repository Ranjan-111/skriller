"""Owner opt-in, immutable event identity, durable leases and bounded retries."""

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.dialects.postgresql import insert

from skriller.connections.keys import Keyring
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.lists import list_snapshots, saved_lists
from skriller.research.changes import meaningful_changes
from skriller.webhooks import transport
from skriller.webhooks.tables import deliveries, endpoints

MAX_ATTEMPTS = 5


def _aad(workspace, endpoint):
    return json.dumps(
        [
            "skriller-webhook-v1",
            str(workspace),
            endpoint["id"],
            endpoint["list_id"],
            endpoint["url"],
            endpoint["key_version"],
        ],
        separators=(",", ":"),
    ).encode()


def public_endpoint(row):
    return {key: row[key] for key in ("id", "list_id", "url", "enabled", "created_at")}


def create_endpoint(session, list_id: str, url: str, *, opt_in: bool, keyring: Keyring):
    require_owner(session)
    if opt_in is not True:
        raise ValueError("Explicit webhook opt-in required")
    url = transport.validate_endpoint(url).url
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "webhooks:" + scope(session)},
    )
    header = session.execute(
        sa.select(saved_lists.c.id).where(
            saved_lists.c.workspace_id == scope(session), saved_lists.c.id == str(UUID(list_id))
        )
    ).scalar_one_or_none()
    if header is None:
        raise LookupError("Saved list unavailable")
    count = session.execute(
        sa.select(sa.func.count())
        .select_from(endpoints)
        .where(endpoints.c.workspace_id == scope(session))
    ).scalar_one()
    if count >= 10:
        raise ValueError("Webhook endpoint limit reached")
    identifier, secret, nonce = str(uuid4()), secrets.token_urlsafe(32), os.urandom(12)
    values = {"id": identifier, "list_id": header, "url": url, "key_version": keyring.active}
    encrypted = AESGCM(keyring.keys[keyring.active]).encrypt(
        nonce, secret.encode(), _aad(scope(session), values)
    )
    row = insert_row(
        session,
        endpoints,
        **values,
        enabled=True,
        created_by=session.info["actor_id"],
        nonce=nonce,
        secret_ciphertext=encrypted,
    )
    return {**public_endpoint(row), "signing_secret": secret}


def disable_endpoint(session, endpoint_id: str):
    require_owner(session)
    row = session.execute(
        sa.update(endpoints)
        .where(endpoints.c.workspace_id == scope(session), endpoints.c.id == str(UUID(endpoint_id)))
        .values(enabled=False, secret_ciphertext=b"")
        .returning(endpoints.c.id)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Webhook endpoint unavailable")
    session.execute(
        sa.update(deliveries)
        .where(
            deliveries.c.workspace_id == scope(session),
            deliveries.c.endpoint_id == row,
            deliveries.c.state.in_(("pending", "delivering")),
        )
        .values(state="cancelled", lease_token=None, lease_expires_at=None, last_code="disabled")
    )


def enqueue_snapshot(session, snapshot):
    """Queue only opt-in, actionable role-change events in the snapshot transaction."""
    require_owner(session)
    previous = session.execute(
        sa.select(list_snapshots.c.payload).where(
            list_snapshots.c.workspace_id == scope(session),
            list_snapshots.c.list_id == snapshot["list_id"],
            list_snapshots.c.revision == snapshot["revision"] - 1,
        )
    ).scalar_one_or_none()
    if previous is None or not meaningful_changes(previous, snapshot["payload"]):
        return
    for endpoint in session.execute(
        sa.select(endpoints.c.id)
        .where(
            endpoints.c.workspace_id == scope(session),
            endpoints.c.list_id == snapshot["list_id"],
            endpoints.c.enabled.is_(True),
        )
        .limit(10)
    ).scalars():
        session.execute(
            insert(deliveries)
            .values(
                workspace_id=scope(session),
                id=str(uuid4()),
                endpoint_id=endpoint,
                snapshot_id=snapshot["id"],
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "endpoint_id", "snapshot_id"])
        )


def claim(session):
    """Reserve and commit an attempt before I/O; process death still consumes it."""
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
    if row["attempts"] >= MAX_ATTEMPTS:
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
            attempts=row["attempts"] + 1,
            state="delivering",
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=30),
        )
    )
    return {"delivery_id": row["id"], "endpoint_id": row["endpoint_id"], "lease_token": token}


def envelope(workspace_id, row, snapshot):
    # IDs/revision only; no claims, evidence excerpts, names, contacts or signed URLs.
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": row["id"],
            "type": "list.snapshot_ready",
            "workspace_id": str(workspace_id),
            "list_id": snapshot["list_id"],
            "snapshot_id": snapshot["id"],
            "revision": snapshot["revision"],
            "created_at": row["created_at"].isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def signature(secret: bytes, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret, str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def deliver(session, task, keyring: Keyring, *, send=transport.post):
    """Recheck current opt-in under lock throughout bounded outbound I/O.

    At least once: a crash after the receiver accepts but before commit can retry
    the same event. Receivers deduplicate event_id and verify timestamp/signature.
    """
    require_owner(session)
    from skriller.erasure import privacy_lock

    privacy_lock(session)
    endpoint = (
        session.execute(
            sa.select(endpoints)
            .where(
                endpoints.c.workspace_id == scope(session),
                endpoints.c.id == str(UUID(task["endpoint_id"])),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if endpoint is None:
        return "stale_lease"
    row = (
        session.execute(
            sa.select(deliveries)
            .where(
                deliveries.c.workspace_id == scope(session),
                deliveries.c.id == str(UUID(task["delivery_id"])),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if (
        row is None
        or row["endpoint_id"] != endpoint["id"]
        or row["state"] != "delivering"
        or row["lease_token"] != task["lease_token"]
        or row["lease_expires_at"] <= now
    ):
        return "stale_lease"
    changes: dict[str, Any] = {"lease_token": None, "lease_expires_at": None}
    if not endpoint["enabled"] or endpoint["created_by"] != session.info["actor_id"]:
        changes.update(state="cancelled", last_code="disabled")
    else:
        snapshot = (
            session.execute(
                sa.select(list_snapshots).where(
                    list_snapshots.c.workspace_id == scope(session),
                    list_snapshots.c.id == row["snapshot_id"],
                    list_snapshots.c.list_id == endpoint["list_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if snapshot is None:
            changes.update(state="cancelled", last_code="snapshot_unavailable")
        else:
            try:
                secret = AESGCM(keyring.keys[endpoint["key_version"]]).decrypt(
                    endpoint["nonce"], endpoint["secret_ciphertext"], _aad(scope(session), endpoint)
                )
                body = envelope(scope(session), row, snapshot)
                status = send(
                    endpoint["url"],
                    body,
                    {
                        "Content-Type": "application/json",
                        "User-Agent": "Skriller-Webhooks/1",
                        "X-Skriller-Event-ID": row["id"],
                        "X-Skriller-Signature": signature(
                            secret, int(datetime.now(UTC).timestamp()), body
                        ),
                    },
                )
                if type(status) is not int or not 100 <= status <= 599:
                    raise ValueError("Invalid transport status")
                if 200 <= status < 300:
                    changes.update(state="delivered", delivered_at=now, last_code="accepted")
                elif 300 <= status < 400:
                    changes.update(state="blocked", last_code="redirect_denied")
                elif status in {408, 429} or status >= 500:
                    changes.update(state="pending", last_code="receiver_retry")
                else:
                    changes.update(state="failed", last_code="receiver_rejected")
            except transport.EgressDenied:
                changes.update(state="blocked", last_code="destination_denied")
            except Exception:  # noqa: BLE001 - redact keys, URL, response and transport exceptions
                changes.update(state="pending", last_code="transport_unavailable")
            if changes["state"] == "pending":
                if row["attempts"] >= MAX_ATTEMPTS:
                    changes.update(state="failed", last_code="attempt_limit")
                else:
                    changes["next_attempt_at"] = now + timedelta(
                        seconds=30 * 2 ** (row["attempts"] - 1)
                    )
    session.execute(
        sa.update(deliveries)
        .where(deliveries.c.workspace_id == scope(session), deliveries.c.id == row["id"])
        .values(**changes)
    )
    return changes["state"]
