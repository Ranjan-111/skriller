"""Real tenant database: opt-in, restart/timeout recovery and private event boundary."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_saved_lists import role, setup

from skriller.connections.keys import Keyring
from skriller.db import ConversationRepository, WorkspaceAccessDenied, WorkspaceRepository
from skriller.lists import create_list, refresh_list
from skriller.lists import snapshot as read_snapshot
from skriller.qualification.contacts import record_role_refresh
from skriller.research.changes import meaningful_changes
from skriller.security.urls import Destination
from skriller.webhooks import transport
from skriller.webhooks.service import (
    claim,
    create_endpoint,
    deliver,
    disable_endpoint,
    enqueue_snapshot,
)
from skriller.webhooks.tables import deliveries, endpoints

pytestmark = pytest.mark.integration_db


def configure(database, monkeypatch):
    monkeypatch.setattr(
        transport,
        "resolve_public_destination",
        lambda url: Destination(url, "receiver.example", 443, ("93.184.216.34",)),
    )
    actor, workspace, entity, plan = setup(database)
    ring = Keyring("v1", {"v1": b"k" * 32})
    with database.tenant(actor, workspace) as session:
        old_role = role(session, entity, "Engineer", "2025-01-01")
        middle_role = role(session, entity, "Director", "2025-06-01")
        from skriller.db.schema import claims

        session.execute(
            sa.update(claims)
            .where(
                claims.c.id.in_(
                    [
                        old_role.role_claim_id,
                        middle_role.role_claim_id,
                        old_role.date_claim_id,
                        middle_role.date_claim_id,
                    ]
                )
            )
            .values(status="accepted")
        )
        assert record_role_refresh(session, old_role, middle_role) == "superseded"
        revision = ConversationRepository.get_plan(session, plan)
        ConversationRepository.add_message(
            session, revision["conversation_id"], "user", "Find software companies"
        )
        revised = ConversationRepository.revise_plan(
            session,
            revision["conversation_id"],
            {**revision["interpretation"], "revision": revision["revision"] + 1},
            parent_id=revision["id"],
        )
        plan = revised["id"]
        saved = create_list(session, "Private list name", plan, (entity,))
        assert session.execute(sa.select(sa.func.count()).select_from(deliveries)).scalar_one() == 0
        endpoint = create_endpoint(
            session, saved["id"], "https://receiver.example/hook", opt_in=True, keyring=ring
        )
        new_role = role(session, entity, "VP", "2026-01-01")
        session.execute(
            sa.update(claims)
            .where(
                claims.c.id.in_(
                    [
                        old_role.role_claim_id,
                        old_role.date_claim_id,
                        middle_role.role_claim_id,
                        middle_role.date_claim_id,
                        new_role.role_claim_id,
                        new_role.date_claim_id,
                    ]
                )
            )
            .values(status="accepted")
        )
        assert record_role_refresh(session, middle_role, new_role) == "superseded"
        refreshed = refresh_list(session, saved["id"], (entity,), expected_revision=1)
        first = read_snapshot(session, saved["id"], 1)
        assert meaningful_changes(first["payload"], refreshed["payload"])
        enqueue_snapshot(session, refreshed)  # duplicate transaction hook is idempotent
    return actor, workspace, saved, endpoint, ring


@pytest.fixture
def configured(database, monkeypatch):
    return configure(database, monkeypatch)


def record(session):
    return session.execute(sa.select(deliveries)).mappings().one()


def due(session):
    session.execute(
        sa.update(deliveries).values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
    )


def test_timeout_retries_same_signed_event_without_private_data(database, configured):
    actor, workspace, _, endpoint, ring = configured
    calls = []

    def send(url, body, headers):
        calls.append((url, body, headers))
        if len(calls) == 1:
            raise TimeoutError("SECRET transport exception must not be stored")
        return 204

    with database.tenant(actor, workspace) as session:
        task = claim(session)
        assert record(session)["attempts"] == 1
        stored = session.execute(sa.select(endpoints)).mappings().one()
        assert endpoint["signing_secret"].encode() not in stored["secret_ciphertext"]
    with database.tenant(actor, workspace) as session:
        assert claim(session) is None  # durable lease excludes concurrent worker
        assert deliver(session, task, ring, send=send) == "pending"
        assert record(session)["last_code"] == "transport_unavailable"
        due(session)
    with database.tenant(actor, workspace) as session:
        retry = claim(session)
        assert retry["delivery_id"] == task["delivery_id"]
    with database.tenant(actor, workspace) as session:
        assert deliver(session, retry, ring, send=send) == "delivered"
        assert record(session)["attempts"] == 2
        assert claim(session) is None
    assert calls[0][1] == calls[1][1]
    data = json.loads(calls[1][1])
    assert set(data) == {
        "schema_version",
        "event_id",
        "type",
        "workspace_id",
        "list_id",
        "snapshot_id",
        "revision",
        "created_at",
    }
    assert data["event_id"] == task["delivery_id"]
    assert b"Private list name" not in calls[1][1]
    stamped, signed = calls[1][2]["X-Skriller-Signature"].split(",")
    timestamp = stamped.removeprefix("t=")
    expected = hmac.new(
        endpoint["signing_secret"].encode(), timestamp.encode() + b"." + calls[1][1], hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(signed, "v1=" + expected)


def test_disable_between_claim_and_send_cancels_and_future_snapshots_do_not_enqueue(
    database, configured
):
    actor, workspace, saved, endpoint, ring = configured
    with database.tenant(actor, workspace) as session:
        task = claim(session)
    with database.tenant(actor, workspace) as session:
        disable_endpoint(session, endpoint["id"])
        refresh_list(session, saved["id"], (), expected_revision=2)
    with database.tenant(actor, workspace) as session:
        assert (
            deliver(session, task, ring, send=lambda *_: pytest.fail("disabled send"))
            == "stale_lease"
        )
        assert record(session)["state"] == "cancelled"
        assert record(session)["attempts"] == 1


def test_unchanged_refresh_does_not_queue_an_opted_in_notice(database, configured):
    actor, workspace, saved, _endpoint, _ring = configured
    with database.tenant(actor, workspace) as session:
        refresh_list(session, saved["id"], (setup_entity(session, saved),), expected_revision=2)
        assert session.execute(sa.select(sa.func.count()).select_from(deliveries)).scalar_one() == 1


def setup_entity(session, saved):
    from skriller.lists import list_snapshots

    payload = session.execute(
        sa.select(list_snapshots.c.payload).where(
            list_snapshots.c.workspace_id == session.info["workspace_id"],
            list_snapshots.c.list_id == saved["id"],
            list_snapshots.c.revision == 2,
        )
    ).scalar_one()
    return payload["members"][0]["entity_id"]


def test_crashed_workers_consume_reserved_attempt_and_stop_after_five(database, configured):
    actor, workspace, _, _, _ = configured
    for attempt in range(1, 6):
        with database.tenant(actor, workspace) as session:
            assert claim(session) is not None
            assert record(session)["attempts"] == attempt
        # Process died before I/O/finalization; emulate lease expiry after restart.
        with database.tenant(actor, workspace) as session:
            session.execute(
                sa.update(deliveries).values(
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            )
    with database.tenant(actor, workspace) as session:
        assert claim(session) is None
        assert record(session)["state"] == "failed"
        assert record(session)["last_code"] == "attempt_limit"


@pytest.mark.parametrize(
    ("status", "expected"), [(302, "blocked"), (400, "failed"), (429, "pending"), (503, "pending")]
)
def test_receiver_status_is_bounded_without_redirects(database, configured, status, expected):
    actor, workspace, _, _, ring = configured
    with database.tenant(actor, workspace) as session:
        task = claim(session)
    calls = []

    def send(*args):
        calls.append(args)
        return status

    with database.tenant(actor, workspace) as session:
        assert deliver(session, task, ring, send=send) == expected
    assert len(calls) == 1


def test_members_and_other_workspaces_cannot_read_or_trigger(database, configured):
    actor, workspace, _, endpoint, _ring = configured
    member = f"member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    with database.tenant(member, workspace) as session:
        assert session.execute(sa.select(endpoints)).all() == []
        assert session.execute(sa.select(deliveries)).all() == []
        with pytest.raises(WorkspaceAccessDenied):
            claim(session)
    other = database.create_workspace(actor, "Other webhook workspace")["id"]
    with database.tenant(actor, other) as session:
        assert session.execute(sa.select(deliveries)).all() == []
        with pytest.raises(LookupError):
            disable_endpoint(session, endpoint["id"])


def test_dns_change_blocks_before_sender_socket(database, configured, monkeypatch):
    actor, workspace, _, _, ring = configured
    with database.tenant(actor, workspace) as session:
        task = claim(session)

    def deny(_):
        raise transport.EgressDenied("private destination")

    monkeypatch.setattr(transport, "validate_endpoint", deny)
    with database.tenant(actor, workspace) as session:
        assert deliver(session, task, ring) == "blocked"
        assert record(session)["last_code"] == "destination_denied"
