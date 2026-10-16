"""Real PostgreSQL connection isolation, encrypted envelopes and revocation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.connections.keys import Keyring
from skriller.connections.store import (
    ConnectionStore,
    ConnectionUnavailable,
    SecretPayload,
    redact_output,
)
from skriller.connections.tables import connection_audit, connections, secrets
from skriller.contracts import ExecutionContext, SearchPlan
from skriller.db import ConversationRepository, WorkspaceAccessDenied, WorkspaceRepository
from skriller.jobs.outbox import submit


@pytest.fixture
def store():
    return ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))


def setup(database, *, actor=None, workspace=None, connection_ref=None):
    actor = actor or f"connection-{uuid4()}"
    workspace = workspace or database.create_workspace(actor, "Connection fixture")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="person",
            sources=["linkedin"],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
    context = ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job["id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        connection_ref=connection_ref,
        attempt_budget=1,
    )
    return actor, workspace, context


def create(session, store):
    return store.create(
        session,
        "linkedin",
        "session",
        SecretPayload(credentials={"session_cookie": "fixture-session-token"}),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def test_encrypted_roundtrip_opaque_metadata_audit_and_redaction(database, store):
    actor, workspace, context = setup(database)
    with database.tenant(actor, workspace) as session:
        reference = create(session, store)
        context = context.model_copy(update={"connection_ref": reference.id})
        material = store.load_for_runner(session, context, "linkedin_read")
        assert material.injection() == {"LINKEDIN_SESSION_COOKIE": "fixture-session-token"}
        assert "fixture-session-token" not in repr(material)
        assert "fixture-session-token" not in repr(reference)
        row = (
            session.execute(sa.select(secrets).where(secrets.c.connection_id == str(reference.id)))
            .mappings()
            .one()
        )
        assert b"fixture-session-token" not in row["ciphertext"]
        assert row["key_version"] == "v1" and len(row["nonce"]) == 12
        audit = (
            session.execute(
                sa.select(connection_audit).where(
                    connection_audit.c.connection_id == str(reference.id)
                )
            )
            .mappings()
            .all()
        )
        assert {row["action"] for row in audit} == {"created", "loaded"}
        assert "fixture-session-token" not in repr(audit)
        output = redact_output(
            "https://user:pass@example.org/?token=fixture-session-token\nCookie: fixture-session-token\nBearer fixture-session-token",
            material,
        )
        assert "fixture-session-token" not in output and "user:pass" not in output
        assert "REDACTED" in output


def test_x_connection_requires_oauth_access_token_not_session_cookie(database, store):
    actor, workspace, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ValueError, match="X reads require an OAuth access token"):
            store.create(
                session,
                "x",
                "session",
                SecretPayload(credentials={"session_cookie": "synthetic-cookie"}),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        reference = store.create(
            session,
            "x",
            "oauth",
            SecretPayload(credentials={"access_token": "synthetic-oauth-token"}),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            scopes=("read", "discover"),
        )
        assert reference.source == "x" and reference.auth_kind == "oauth"


def test_cross_workspace_wrong_runner_and_actor_denied(database, store):
    actor, workspace, context = setup(database)
    foreign_actor, foreign_workspace, foreign_context = setup(database)
    with database.tenant(actor, workspace) as session:
        reference = create(session, store)
        context = context.model_copy(update={"connection_ref": reference.id})
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(session, context, "reddit_read")
        with pytest.raises(WorkspaceAccessDenied):
            store.load_for_runner(
                session,
                foreign_context.model_copy(update={"connection_ref": reference.id}),
                "linkedin_read",
            )
    with database.tenant(foreign_actor, foreign_workspace) as session:
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(
                session,
                foreign_context.model_copy(update={"connection_ref": reference.id}),
                "linkedin_read",
            )
        assert (
            session.execute(
                sa.select(secrets).where(secrets.c.connection_id == str(reference.id))
            ).first()
            is None
        )


def test_member_can_use_workspace_connection_but_cannot_mutate(database, store):
    actor, workspace, _ = setup(database)
    member = f"member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
        reference = create(session, store)
    _, _, context = setup(database, actor=member, workspace=workspace, connection_ref=reference.id)
    with database.tenant(member, workspace) as session:
        assert (
            store.load_for_runner(session, context, "linkedin_read").injection()[
                "LINKEDIN_SESSION_COOKIE"
            ]
            == "fixture-session-token"
        )
        with pytest.raises(WorkspaceAccessDenied):
            store.revoke(session, reference.id)
        with pytest.raises(WorkspaceAccessDenied):
            create(session, store)
        # Database mutation policy protects direct SQL too.
        assert (
            session.execute(
                sa.update(connections)
                .where(connections.c.id == str(reference.id))
                .values(state="revoked")
            ).rowcount
            == 0
        )


def test_wrong_key_tamper_and_swapped_cipher_envelopes_fail_closed(database, store):
    actor, workspace, context = setup(database)
    wrong = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, workspace) as session:
        reference = create(session, store)
        context = context.model_copy(update={"connection_ref": reference.id})
        with pytest.raises(ConnectionUnavailable, match="needs configuration"):
            wrong.load_for_runner(session, context, "linkedin_read")
        first = (
            session.execute(sa.select(secrets).where(secrets.c.connection_id == str(reference.id)))
            .mappings()
            .one()
        )
        second = create(session, store)
        session.execute(
            sa.update(secrets)
            .where(secrets.c.connection_id == str(second.id))
            .values(nonce=first["nonce"], ciphertext=first["ciphertext"])
        )
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(
                session, context.model_copy(update={"connection_ref": second.id}), "linkedin_read"
            )
        altered = bytearray(first["ciphertext"])
        altered[-1] ^= 1
        session.execute(
            sa.update(secrets)
            .where(secrets.c.connection_id == str(reference.id))
            .values(ciphertext=bytes(altered))
        )
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(session, context, "linkedin_read")


def test_revocation_destroys_secrets_and_denies_queued_reuse(database, store):
    actor, workspace, context = setup(database)
    with database.tenant(actor, workspace) as session:
        reference = create(session, store)
        context = context.model_copy(update={"connection_ref": reference.id})
        assert store.revoke(session, reference.id).state == "revoked"
        assert store.revoke(session, reference.id).state == "revoked"
        assert (
            session.execute(
                sa.select(secrets).where(secrets.c.connection_id == str(reference.id))
            ).first()
            is None
        )
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(session, context, "linkedin_read")
        audit = (
            session.execute(
                sa.select(connection_audit).where(
                    connection_audit.c.connection_id == str(reference.id)
                )
            )
            .mappings()
            .all()
        )
        assert len([row for row in audit if row["action"] == "revoked"]) == 1


def test_missing_key_typed_expiry_purge_and_versioned_keys(database, store):
    actor, workspace, context = setup(database)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ConnectionUnavailable) as exc:
            create(session, ConnectionStore(None))
        assert exc.value.state == "needs_connection"
        reference = create(session, store)
        rotated = ConnectionStore(
            Keyring("v2", {**store.keyring.keys, "v2": AESGCM.generate_key(bit_length=256)})
        )
        context = context.model_copy(update={"connection_ref": reference.id})
        assert (
            rotated.load_for_runner(session, context, "linkedin_read").connection_ref
            == reference.id
        )
        session.execute(
            sa.update(connections)
            .where(connections.c.id == str(reference.id))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        assert store.metadata(session, reference.id).state == "expired"
        with pytest.raises(ConnectionUnavailable):
            store.load_for_runner(session, context, "linkedin_read")
        assert store.purge_expired(session) == 1
        assert (
            session.execute(
                sa.select(secrets).where(secrets.c.connection_id == str(reference.id))
            ).first()
            is None
        )
