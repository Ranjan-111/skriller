"""Real PostgreSQL grant lifecycle; controlled Google consent provider only."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from skriller.analytics.google import SCOPES, AnalyticsUnavailable
from skriller.analytics.router import router
from skriller.analytics.service import AnalyticsStore
from skriller.analytics.tables import grants
from skriller.connections.keys import Keyring
from skriller.db import WorkspaceRepository
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
CHANNEL = "UC" + "a" * 22


class Provider:
    def __init__(self, *, scopes=SCOPES, hook=None):
        self.calls, self.scopes, self.hook = 0, scopes, hook

    def exchange(self, config, code, verifier):
        self.calls += 1
        assert code == "fixture-code" and len(verifier) >= 43
        if self.hook:
            self.hook()
        return {
            "access_token": "SENTINEL_ACCESS",
            "refresh_token": "SENTINEL_REFRESH",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(self.scopes),
        }, CHANNEL

    def refresh(self, config, refresh_token):
        assert refresh_token == "SENTINEL_REFRESH"
        self.calls += 1
        if self.hook:
            self.hook()
        return {
            "access_token": "NEW_ACCESS",
            "refresh_token": refresh_token,
            "expires_in": 3600,
            "scope": " ".join(self.scopes),
            "token_type": "Bearer",
        }


def app_for(database, provider=None, *, owner=None, workspace=None):
    owner = owner or "analytics-" + str(uuid4())
    workspace = workspace or database.create_workspace(owner, "Owner analytics")["id"]
    app = FastAPI()
    app.include_router(router)
    app.state.database = database
    app.state.settings = Settings(
        _env_file=None,
        environment="test",
        firebase_project_id="analytics-fixture",
        youtube_analytics_oauth_client_id="fixture-client",
        youtube_analytics_oauth_client_secret="CLIENT_SECRET",
        youtube_analytics_oauth_redirect_uri="http://localhost:3000/connections/youtube-analytics/callback",
    )
    app.state.analytics_store = AnalyticsStore(Keyring("v1", {"v1": b"a" * 32}))
    app.state.analytics_provider = provider or Provider()
    app.state.identity_verifier = lambda token, project: {
        "sub": token,
        "aud": project,
        "iss": f"https://securetoken.google.com/{project}",
    }
    client = TestClient(app, headers={"Authorization": "Bearer " + owner})
    return owner, workspace, app, client, f"/v1/workspaces/{workspace}/youtube-analytics"


def consent(client, path):
    response = client.post(path + "/oauth/start", json={"opt_in": True})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    query = parse_qs(urlsplit(data["authorization_url"]).query)
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert query["code_challenge_method"] == ["S256"]
    assert "CLIENT_SECRET" not in data["authorization_url"]
    return {"grant_id": data["grant_id"], "code": "fixture-code", "state": query["state"][0]}


def test_consent_tokens_encrypted_and_replay_or_revocation_cannot_read(database):
    owner, workspace, app, client, path = app_for(database)
    body = consent(client, path)
    completed = client.post(path + "/oauth/complete", json=body)
    assert completed.status_code == 201, completed.text
    assert completed.json()["channel_id"] == CHANNEL
    assert "SENTINEL" not in completed.text
    with database.tenant(owner, workspace) as session:
        row, token = app.state.analytics_store.access(session, body["grant_id"])
        assert token == "SENTINEL_ACCESS"
        assert b"SENTINEL" not in row["ciphertext"]
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    assert app.state.analytics_provider.calls == 1
    revoked = client.post(path + f"/grants/{body['grant_id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    with database.tenant(owner, workspace) as session:
        with pytest.raises(AnalyticsUnavailable):
            app.state.analytics_store.access(session, body["grant_id"])
        assert app.state.analytics_store.get(session, body["grant_id"])["ciphertext"] == b""
    listed = client.get(path + "/grants")
    assert listed.status_code == 200 and "SENTINEL" not in listed.text


def test_grant_belongs_to_initiating_owner_not_coowner_or_foreign_workspace(database):
    owner, workspace, app, client, path = app_for(database)
    body = consent(client, path)
    other = "coowner-" + str(uuid4())
    member = "member-" + str(uuid4())
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, other, role="owner")
        WorkspaceRepository.add_member(session, member)
    client.headers["Authorization"] = "Bearer " + other
    assert client.get(path + "/grants").json() == []
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    with database.tenant(other, workspace) as session:
        assert session.execute(sa.select(grants)).mappings().all() == []
    client.headers["Authorization"] = "Bearer " + member
    assert client.post(path + "/oauth/start", json={"opt_in": True}).status_code == 403
    assert client.post(path + "/oauth/complete", json=body).status_code == 403
    client.headers["Authorization"] = "Bearer " + owner
    foreign = database.create_workspace(owner, "Unrelated owner workspace")["id"]
    assert (
        client.post(path.replace(workspace, foreign) + "/oauth/complete", json=body).status_code
        == 409
    )
    assert app.state.analytics_provider.calls == 0
    assert client.post(path + "/oauth/complete", json=body).status_code == 201


def test_missing_scope_consumes_consent_and_never_activates_grant(database):
    provider = Provider(scopes=SCOPES[:1])
    owner, workspace, app, client, path = app_for(database, provider)
    body = consent(client, path)
    result = client.post(path + "/oauth/complete", json=body)
    assert result.status_code == 409 and "SENTINEL" not in result.text
    with database.tenant(owner, workspace) as session:
        row = app.state.analytics_store.get(session, body["grant_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    assert provider.calls == 1


def test_revoke_during_google_exchange_discards_late_tokens(database):
    owner, workspace, app, client, path = app_for(database)
    body = consent(client, path)

    def revoke():
        with database.tenant(owner, workspace) as session:
            app.state.analytics_store.revoke(session, body["grant_id"])

    app.state.analytics_provider = Provider(hook=revoke)
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    with database.tenant(owner, workspace) as session:
        assert app.state.analytics_store.get(session, body["grant_id"])["ciphertext"] == b""


def test_wrong_state_expiry_opt_in_and_secret_validation_fail_before_provider(database):
    owner, workspace, app, client, path = app_for(database)
    assert client.post(path + "/oauth/start", json={"opt_in": False}).status_code == 422
    body = consent(client, path)
    assert (
        client.post(path + "/oauth/complete", json={**body, "state": "x" * 43}).status_code == 409
    )
    invalid = client.post(path + "/oauth/complete", json={**body, "code": {"secret": "SENTINEL"}})
    assert invalid.status_code == 422 and "SENTINEL" not in invalid.text
    with database.tenant(owner, workspace) as session:
        session.execute(
            sa.update(grants)
            .where(grants.c.id == body["grant_id"])
            .values(expires_at=sa.func.now() - timedelta(seconds=1))
        )
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    assert app.state.analytics_provider.calls == 0


def test_refresh_fences_revoke_and_preserves_absolute_grant_retention(database):
    owner, workspace, app, client, path = app_for(database)
    body = consent(client, path)
    assert client.post(path + "/oauth/complete", json=body).status_code == 201
    with database.tenant(owner, workspace) as session:
        original_expiry = app.state.analytics_store.get(session, body["grant_id"])["expires_at"]
    refreshed = client.post(path + f"/grants/{body['grant_id']}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    with database.tenant(owner, workspace) as session:
        row, token = app.state.analytics_store.access(session, body["grant_id"])
        assert token == "NEW_ACCESS" and row["expires_at"] == original_expiry

    def revoke():
        with database.tenant(owner, workspace) as session:
            app.state.analytics_store.revoke(session, body["grant_id"])

    app.state.analytics_provider = Provider(hook=revoke)
    assert client.post(path + f"/grants/{body['grant_id']}/refresh").status_code == 409
    with database.tenant(owner, workspace) as session:
        assert app.state.analytics_store.get(session, body["grant_id"])["ciphertext"] == b""


def test_expired_grant_listing_erases_ciphertext_without_key_or_google_call(database):
    owner, workspace, app, client, path = app_for(database)
    body = consent(client, path)
    assert client.post(path + "/oauth/complete", json=body).status_code == 201
    with database.tenant(owner, workspace) as session:
        session.execute(
            sa.update(grants)
            .where(grants.c.id == body["grant_id"])
            .values(expires_at=sa.func.now() - timedelta(seconds=1))
        )
    assert client.get(path + "/grants").json()[0]["state"] == "revoked"
    with database.tenant(owner, workspace) as session:
        assert app.state.analytics_store.get(session, body["grant_id"])["ciphertext"] == b""


def test_expiry_cleanup_covers_coowner_grants_without_revealing_or_touching_active_secrets(
    database,
):
    from skriller.analytics.router import configuration

    owner, workspace, app, client, path = app_for(database)
    coowner, member = "coowner-" + str(uuid4()), "member-" + str(uuid4())
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, coowner, role="owner")
        WorkspaceRepository.add_member(session, member)
    config = configuration(type("Request", (), {"app": app})())
    foreign_workspace = database.create_workspace(coowner, "Other expiry scope")["id"]
    with database.tenant(coowner, foreign_workspace) as session:
        foreign = app.state.analytics_store.start(session, config, opt_in=True)
        session.execute(
            sa.update(grants)
            .where(grants.c.id == foreign["grant_id"])
            .values(expires_at=sa.func.now() - timedelta(seconds=1))
        )
    with database.tenant(coowner, workspace) as session:
        expired = app.state.analytics_store.start(session, config, opt_in=True)
        active = app.state.analytics_store.start(session, config, opt_in=True)
        session.execute(
            sa.update(grants)
            .where(grants.c.id == expired["grant_id"])
            .values(expires_at=sa.func.now() - timedelta(seconds=1))
        )
    assert client.get(path + "/grants").json() == []
    with database.tenant(coowner, workspace) as session:
        assert app.state.analytics_store.get(session, expired["grant_id"])["ciphertext"] == b""
        assert app.state.analytics_store.get(session, active["grant_id"])["ciphertext"] != b""
    with database.tenant(coowner, foreign_workspace) as session:
        assert app.state.analytics_store.get(session, foreign["grant_id"])["ciphertext"] != b""
    with pytest.raises(sa.exc.DBAPIError), database.tenant(member, workspace) as session:
        session.execute(sa.text("SELECT expire_youtube_analytics_grants()"))
