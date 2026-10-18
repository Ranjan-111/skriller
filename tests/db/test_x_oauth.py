"""Actual PostgreSQL X consent encryption, replay and rotation fences."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from test_youtube_analytics import app_for

from skriller.connections.keys import Keyring
from skriller.connections.tables import secrets
from skriller.connections.x_oauth import XConsentStore, consents
from skriller.connections.x_router import router
from skriller.connectors.x_oauth import SCOPES
from skriller.contracts import ExecutionContext, SearchPlan
from skriller.db import ConversationRepository, WorkspaceRepository
from skriller.db.schema import memberships
from skriller.jobs.outbox import submit
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


class Provider:
    calls = 0
    refreshes = 0
    hook = None

    def exchange(self, config, code, verifier):
        self.calls += 1
        assert code == "fixture-code" and len(verifier) >= 43
        return {
            "access_token": "X_ACCESS_SENTINEL_123",
            "refresh_token": "X_REFRESH_SENTINEL_123",
            "token_type": "Bearer",
            "scope": SCOPES,
            "expires_in": 7200,
        }

    def refresh(self, config, token):
        assert token == "X_REFRESH_SENTINEL_123"
        self.refreshes += 1
        if self.hook:
            self.hook()
        return {
            "access_token": "X_ACCESS_ROTATED_123",
            "refresh_token": "X_REFRESH_ROTATED_123",
            "token_type": "Bearer",
            "scope": SCOPES,
            "expires_in": 7200,
        }


def setup(database):
    actor, workspace, app, client, _ = app_for(database)
    app.include_router(router)
    app.state.x_consent_store = XConsentStore(Keyring("fixture", {"fixture": b"a" * 32}))
    app.state.x_oauth_provider = Provider()
    app.state.settings = app.state.settings.model_copy(
        update={
            "x_oauth_client_id": "fixture-client",
            "x_oauth_client_secret": SecretStr("CLIENT_SECRET"),
            "x_oauth_redirect_uri": "http://localhost:3000/connections/x/callback",
        }
    )
    return actor, workspace, app, client, f"/v1/workspaces/{workspace}/x/oauth"


def start(client, path):
    result = client.post(path + "/start", json={"opt_in": True})
    assert result.status_code == 201, result.text
    value = result.json()
    state = parse_qs(urlsplit(value["authorization_url"]).query)["state"][0]
    return {"consent_id": value["consent_id"], "state": state, "code": "fixture-code"}


def test_x_encrypted_consent_single_use_and_fresh_connection_rotation(database):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    assert client.post(path + "/complete", json={**body, "state": "x" * 43}).status_code == 409
    response = client.post(path + "/complete", json=body)
    assert response.status_code == 201, response.text
    previous = response.json()["id"]
    assert "SENTINEL" not in response.text
    assert client.post(path + "/complete", json=body).status_code == 409
    assert app.state.x_oauth_provider.calls == 1
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "X consent read fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="discussion",
            sources=["x"],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], uuid4().hex)
        context = ExecutionContext(
            workspace_id=UUID(workspace),
            job_id=UUID(job["id"]),
            actor_id=actor,
            plan_revision=1,
            deadline=datetime.now(UTC) + timedelta(minutes=1),
            connection_ref=UUID(previous),
            attempt_budget=1,
        )
        material = app.state.x_consent_store.connections.load_for_runner(session, context, "x_read")
        assert material.injection() == {"X_ACCESS_TOKEN": "X_ACCESS_SENTINEL_123"}
        row = app.state.x_consent_store.get(session, body["consent_id"])
        assert b"SENTINEL" not in row["ciphertext"]
        assert app.state.x_consent_store.open(row) == {"refresh_token": "X_REFRESH_SENTINEL_123"}
        assert (
            session.execute(
                sa.select(secrets.c.ciphertext).where(secrets.c.connection_id == previous)
            ).scalar_one()
            != b"X_ACCESS_SENTINEL_123"
        )
    rotated = client.post(path + f"/{body['consent_id']}/refresh")
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["id"] != previous
    with database.tenant(actor, workspace) as session:
        assert not app.state.x_consent_store.connections.runner_current(session, context, material)
        fresh_context = context.model_copy(update={"connection_ref": UUID(rotated.json()["id"])})
        fresh = app.state.x_consent_store.connections.load_for_runner(
            session, fresh_context, "x_read"
        )
        assert fresh.injection() == {"X_ACCESS_TOKEN": "X_ACCESS_ROTATED_123"}
        assert (
            app.state.x_consent_store.connections.metadata(session, UUID(previous)).state
            == "revoked"
        )
        assert not session.execute(
            sa.select(secrets.c.id).where(secrets.c.connection_id == previous)
        ).all()
        row = app.state.x_consent_store.get(session, body["consent_id"])
        assert app.state.x_consent_store.open(row) == {"refresh_token": "X_REFRESH_ROTATED_123"}
    listed = client.get(path)
    assert listed.status_code == 200 and "SENTINEL" not in listed.text
    assert listed.json()[0]["connection_id"] == rotated.json()["id"]


def test_x_consent_is_owner_and_tenant_bound_and_provider_not_called(database):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    other = "x-other-" + uuid4().hex
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
    response = client.post(
        path + "/complete", json=body, headers={"Authorization": "Bearer " + other}
    )
    assert response.status_code == 409 and app.state.x_oauth_provider.calls == 0
    assert client.post(path + "/start", json={"opt_in": False}).status_code == 409
    malformed = client.post(
        path + "/complete", json={**body, "code": "SECRET", "unknown": "SECRET"}
    )
    assert malformed.status_code == 422 and "SECRET" not in malformed.text
    foreign = database.create_workspace(other, "Foreign")["id"]
    assert client.post(f"/v1/workspaces/{foreign}/x/oauth/complete", json=body).status_code == 403


@pytest.mark.parametrize("during_refresh", ["failure", "revocation"])
def test_x_interrupted_refresh_does_not_replay_or_resurrect(database, during_refresh):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    previous = client.post(path + "/complete", json=body).json()["id"]

    def hook():
        if during_refresh == "failure":
            raise RuntimeError("SENTINEL_PRIVATE")
        with database.tenant(actor, workspace) as session:
            app.state.x_consent_store.revoke(session, body["consent_id"])

    app.state.x_oauth_provider.hook = hook
    response = client.post(path + f"/{body['consent_id']}/refresh")
    assert response.status_code == 409 and "SENTINEL" not in response.text
    assert client.post(path + f"/{body['consent_id']}/refresh").status_code == 409
    assert app.state.x_oauth_provider.refreshes == 1
    with database.tenant(actor, workspace) as session:
        row = app.state.x_consent_store.get(session, body["consent_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
        assert (
            app.state.x_consent_store.connections.metadata(session, UUID(previous)).state
            == "revoked"
        )


def test_x_other_owner_expiry_wipes_refresh_and_access_tokens(database):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    previous = client.post(path + "/complete", json=body).json()["id"]
    other = "x-expiry-owner-" + uuid4().hex
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
        session.execute(
            sa.update(consents)
            .where(consents.c.id == body["consent_id"])
            .values(expires_at=sa.func.now())
        )
    with database.tenant(other, workspace) as session:
        session.execute(sa.text("SELECT expire_x_oauth_consents()"))
    with database.tenant(actor, workspace) as session:
        row = app.state.x_consent_store.get(session, body["consent_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
        assert not session.execute(
            sa.select(secrets.c.id).where(secrets.c.connection_id == previous)
        ).all()


def test_x_grant_fence_holds_across_other_owner_rls_rotation_and_owner_demotion(database):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    identifier = client.post(path + "/complete", json=body).json()["id"]
    other = "x-fence-owner-" + uuid4().hex
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")

    def allowed(session):
        return session.execute(
            sa.text("SELECT x_connection_allowed(CAST(:w AS uuid),CAST(:c AS uuid))"),
            {"w": workspace, "c": identifier},
        ).scalar_one()

    with database.tenant(other, workspace) as session:
        assert session.execute(sa.select(consents)).all() == []
        assert allowed(session) is True

    def hook():
        with database.tenant(other, workspace) as session:
            assert allowed(session) is False

    app.state.x_oauth_provider.hook = hook
    rotated = client.post(path + f"/{body['consent_id']}/refresh")
    assert rotated.status_code == 200, rotated.text
    identifier = rotated.json()["id"]
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.update(memberships)
                .where(memberships.c.workspace_id == workspace, memberships.c.actor_id == actor)
                .values(role="member")
            )
        with database.tenant(other, workspace) as session:
            assert allowed(session) is False
            session.execute(sa.text("SELECT expire_x_oauth_consents()"))
        with engine.begin() as connection:
            row = (
                connection.execute(sa.select(consents).where(consents.c.id == body["consent_id"]))
                .mappings()
                .one()
            )
            assert row["state"] == "revoked" and row["ciphertext"] == b""
    finally:
        engine.dispose()
