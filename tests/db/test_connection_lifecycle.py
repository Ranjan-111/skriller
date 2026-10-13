from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore
from skriller.connections.tables import connection_audit, connections, secrets
from skriller.db import WorkspaceRepository
from skriller.settings import Settings


def client_for(database, actor, *, key=True):
    app = create_app(Settings(source_encryption_key_file=None))
    app.state.database = database
    app.state.connection_store = (
        ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
        if key
        else ConnectionStore(None)
    )
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    return app, TestClient(app)


def body(secret="fixture-private-credential"):
    return {
        "source": "linkedin",
        "auth_kind": "session",
        "payload": {"credentials": {"session_cookie": secret}},
        "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "scopes": ["read"],
    }


def test_owner_connect_reconnect_revokes_old_ref_and_only_metadata_returned(database):
    actor = f"lifecycle-{uuid4()}"
    workspace = database.create_workspace(actor, "Lifecycle fixture")["id"]
    app, client = client_for(database, actor)
    base = f"/v1/workspaces/{workspace}/connections"
    created = client.post(base, json=body())
    assert created.status_code == 201, created.text
    assert "fixture-private-credential" not in created.text
    assert "payload" not in created.json() and "credentials" not in created.json()
    assert created.json()["access_validation"] == "not_performed"
    old = created.json()["id"]
    replacement_body = {
        key: value
        for key, value in body("fixture-new-private-credential").items()
        if key != "source"
    }
    reconnected = client.post(f"{base}/{old}/reconnect", json=replacement_body)
    assert reconnected.status_code == 201, reconnected.text
    assert reconnected.json()["id"] != old
    assert "fixture-new-private-credential" not in reconnected.text
    rows = client.get(base).json()
    assert {row["state"] for row in rows} == {"active", "revoked"}
    with database.tenant(actor, workspace) as session:
        assert app.state.connection_store.metadata(session, UUID(old)).state == "revoked"
        assert (
            session.execute(sa.select(secrets).where(secrets.c.connection_id == old)).first()
            is None
        )
        audit = (
            session.execute(
                sa.select(connection_audit).where(connection_audit.c.connection_id == old)
            )
            .mappings()
            .all()
        )
        assert {row["action"] for row in audit} == {"created", "revoked"}
    new_id = reconnected.json()["id"]
    assert client.post(f"{base}/{new_id}/revoke").json()["state"] == "revoked"
    assert client.post(f"{base}/{new_id}/revoke").json()["state"] == "revoked"
    assert "fixture-private-credential" not in client.get(base).text


def test_expired_metadata_and_owned_purge_are_idempotent(database):
    actor = f"lifecycle-{uuid4()}"
    workspace = database.create_workspace(actor, "Lifecycle fixture")["id"]
    _, client = client_for(database, actor)
    base = f"/v1/workspaces/{workspace}/connections"
    identifier = client.post(base, json=body()).json()["id"]
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(connections)
            .where(connections.c.id == identifier)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert client.get(base).json()[0]["state"] == "expired"
    assert client.post(f"{base}/purge-expired").json() == {"purged": 1}
    assert client.post(f"{base}/purge-expired").json() == {"purged": 0}
    with database.tenant(actor, workspace) as session:
        assert (
            session.execute(sa.select(secrets).where(secrets.c.connection_id == identifier)).first()
            is None
        )


def test_members_read_metadata_but_cannot_write_and_foreign_workspace_denied(database):
    owner = f"lifecycle-{uuid4()}"
    member = f"member-{uuid4()}"
    workspace = database.create_workspace(owner, "Lifecycle fixture")["id"]
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    app, client = client_for(database, owner)
    base = f"/v1/workspaces/{workspace}/connections"
    identifier = client.post(base, json=body()).json()["id"]
    app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.get(base).status_code == 200
    assert client.post(base, json=body()).status_code == 403
    assert client.post(f"{base}/{identifier}/revoke").status_code == 403
    reconnect_body = {key: value for key, value in body().items() if key != "source"}
    assert client.post(f"{base}/{identifier}/reconnect", json=reconnect_body).status_code == 403
    assert client.post(f"{base}/purge-expired").status_code == 403
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.get(base).status_code == 404
    assert client.post(base, json=body()).status_code == 403
    app.dependency_overrides.clear()
    assert client.get(base).status_code == 401


def test_invalid_credentials_and_chunked_large_body_never_echo_inputs(database, caplog):
    actor = f"lifecycle-{uuid4()}"
    workspace = database.create_workspace(actor, "Lifecycle fixture")["id"]
    _, client = client_for(database, actor)
    base = f"/v1/workspaces/{workspace}/connections"
    invalid = body("fixture-sensitive-invalid-secret")
    invalid["payload"]["credentials"] = {"unsupported-name": "fixture-sensitive-invalid-secret"}
    response = client.post(base, json=invalid)
    assert response.status_code == 422
    assert "fixture-sensitive-invalid-secret" not in response.text
    assert "input" not in response.text and "ctx" not in response.text
    invalid = body("fixture-sensitive-invalid-secret")
    invalid["expires_at"] = "fixture-sensitive-invalid-secret"
    response = client.post(base, json=invalid)
    assert response.status_code == 422 and "fixture-sensitive-invalid-secret" not in response.text
    response = client.post(
        base,
        content=iter([b"x" * 32768, b"x" * 32769]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413, response.text
    assert "fixture-sensitive-invalid-secret" not in caplog.text


def test_missing_key_503_and_failed_reconnect_preserve_old_credentials(database):
    actor = f"lifecycle-{uuid4()}"
    workspace = database.create_workspace(actor, "Lifecycle fixture")["id"]
    app, client = client_for(database, actor, key=False)
    base = f"/v1/workspaces/{workspace}/connections"
    response = client.post(base, json=body())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "needs_connection"
    assert client.get(base).json() == []
    app.state.connection_store = ConnectionStore(
        Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)})
    )
    identifier = client.post(base, json=body()).json()["id"]
    app.state.connection_store = ConnectionStore(None)
    replacement = {key: value for key, value in body().items() if key != "source"}
    assert client.post(f"{base}/{identifier}/reconnect", json=replacement).status_code == 503
    assert client.get(base).json()[0]["state"] == "active"
    # Local deletion is possible even when the encryption key is unavailable.
    assert client.post(f"{base}/{identifier}/revoke").json()["state"] == "revoked"


def test_expiry_reconnect_and_revocation_do_not_modify_unrelated_job_state(database):
    import pytest

    from skriller.connections.store import ConnectionUnavailable
    from skriller.contracts import ExecutionContext, SearchPlan
    from skriller.db import ConversationRepository, JobRepository
    from skriller.jobs.outbox import submit

    actor = f"lifecycle-{uuid4()}"
    workspace = database.create_workspace(actor, "Lifecycle fixture")["id"]
    app, client = client_for(database, actor)
    base = f"/v1/workspaces/{workspace}/connections"
    old_ref = UUID(client.post(base, json=body()).json()["id"])
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Source task fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="person",
            sources=["linkedin", "web"],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        before = dict(JobRepository.get(session, job["id"]))
        session.execute(
            sa.update(connections)
            .where(connections.c.id == str(old_ref))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    context = ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job["id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        connection_ref=old_ref,
        attempt_budget=1,
    )
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ConnectionUnavailable):
            app.state.connection_store.load_for_runner(session, context, "linkedin_read")
        assert dict(JobRepository.get(session, job["id"])) == before
    replacement = {
        key: value for key, value in body("fixture-reconnected-token").items() if key != "source"
    }
    new_ref = UUID(client.post(f"{base}/{old_ref}/reconnect", json=replacement).json()["id"])
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ConnectionUnavailable):
            app.state.connection_store.load_for_runner(session, context, "linkedin_read")
        material = app.state.connection_store.load_for_runner(
            session, context.model_copy(update={"connection_ref": new_ref}), "linkedin_read"
        )
        assert material.injection()["LINKEDIN_SESSION_COOKIE"] == "fixture-reconnected-token"
        assert dict(JobRepository.get(session, job["id"])) == before
