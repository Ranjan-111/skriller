"""PostgreSQL CRM consent, rotation, disconnect and single-use fences."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_youtube_analytics import app_for

from skriller.connections.keys import Keyring
from skriller.crm.consents import ConsentStore, consents, refresh_destination
from skriller.crm.router import configuration, router
from skriller.crm.salesforce import SalesforceUnavailable
from skriller.crm.store import DestinationStore, destinations
from skriller.db import WorkspaceRepository

pytestmark = pytest.mark.integration_db


class Provider:
    calls = 0
    refreshes = 0
    hook = None

    def exchange(self, config, code, verifier):
        assert code == "fixture-code" and len(verifier) >= 43
        self.calls += 1
        return {
            "access_token": "CRM_ACCESS_SENTINEL",
            "refresh_token": "CRM_REFRESH_SENTINEL",
            "token_type": "Bearer",
            "instance_url": "https://fixture.my.salesforce.com",
        }

    def refresh(self, config, token):
        assert token == "CRM_REFRESH_SENTINEL"
        self.refreshes += 1
        if self.hook:
            self.hook()
        return {
            "access_token": "CRM_ACCESS_ROTATED",
            "refresh_token": "CRM_REFRESH_ROTATED",
            "token_type": "Bearer",
            "instance_url": "https://fixture.my.salesforce.com",
        }


def setup(database, *, owner=None, workspace=None):
    actor, workspace, app, client, _ = app_for(database, owner=owner, workspace=workspace)
    app.include_router(router)
    app.state.crm_store = DestinationStore(Keyring("fixture", {"fixture": b"a" * 32}))
    app.state.crm_oauth_provider = Provider()
    app.state.settings = app.state.settings.model_copy(
        update={
            "salesforce_oauth_client_id": "fixture-client",
            "salesforce_oauth_client_secret": __import__("pydantic").SecretStr("CLIENT_SECRET"),
            "salesforce_oauth_redirect_uri": "http://localhost:3000/connections/salesforce/callback",
        }
    )
    return actor, workspace, app, client, f"/v1/workspaces/{workspace}/crm"


def consent(client, path):
    response = client.post(path + "/oauth/start", json={"opt_in": True})
    assert response.status_code == 201, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["scope"] == ["api refresh_token"] and query["code_challenge_method"] == ["S256"]
    assert "client_secret" not in query
    return {
        "consent_id": response.json()["consent_id"],
        "state": query["state"][0],
        "code": "fixture-code",
    }


def test_crm_oauth_single_use_and_rotation_preserves_destination_generation(database):
    actor, workspace, app, client, path = setup(database)
    body = consent(client, path)
    wrong = client.post(path + "/oauth/complete", json={**body, "state": "x" * 43})
    assert wrong.status_code == 409
    response = client.post(path + "/oauth/complete", json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert "SENTINEL" not in response.text
    assert client.post(path + "/oauth/complete", json=body).status_code == 409
    assert app.state.crm_oauth_provider.calls == 1
    other = "oauth-co-owner-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
        original = app.state.crm_store.get(session, identifier)
        # Due condition without breaking the expiry-authenticated access payload:
        # use a deliberately freshly re-sealed short-lived token.
        row = dict(original)
        import os

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        row["expires_at"] = session.execute(sa.select(sa.func.now())).scalar_one() + timedelta(
            seconds=40
        )
        nonce = os.urandom(12)
        cipher = AESGCM(b"a" * 32).encrypt(
            nonce, b"CRM_ACCESS_SENTINEL", app.state.crm_store._aad(row)
        )
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == identifier)
            .values(expires_at=row["expires_at"], nonce=nonce, ciphertext=cipher)
        )
    refreshed = client.post(path + f"/destinations/{identifier}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["generation"] == original["generation"]
    assert app.state.crm_oauth_provider.refreshes == 1
    assert client.post(path + f"/destinations/{identifier}/refresh").status_code == 200
    assert app.state.crm_oauth_provider.refreshes == 1
    with database.tenant(actor, workspace) as session:
        _, token = app.state.crm_store.credentials(
            session, identifier, generation=original["generation"]
        )
        assert token == "CRM_ACCESS_ROTATED"
    with database.tenant(other, workspace) as session:
        assert session.execute(sa.select(consents)).mappings().all() == []
    revoked = client.post(path + f"/destinations/{identifier}/revoke")
    assert revoked.status_code == 200
    with database.tenant(actor, workspace) as session:
        row = ConsentStore(app.state.crm_store).get(session, body["consent_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
    assert client.post(path + f"/destinations/{identifier}/refresh").status_code == 409


def test_revocation_during_refresh_cannot_reactivate_destination(database):
    actor, workspace, app, client, path = setup(database)
    body = consent(client, path)
    identifier = client.post(path + "/oauth/complete", json=body).json()["id"]
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == identifier)
            .values(expires_at=sa.func.now())
        )

    def revoke():
        with database.tenant(actor, workspace) as session:
            app.state.crm_store.revoke(session, identifier)

    app.state.crm_oauth_provider.hook = revoke
    with pytest.raises(SalesforceUnavailable):
        refresh_destination(
            database,
            ConsentStore(app.state.crm_store),
            configuration(app.state.settings),
            app.state.crm_oauth_provider,
            actor,
            workspace,
            identifier,
        )
    with database.tenant(actor, workspace) as session:
        destination = app.state.crm_store.get(session, identifier)
        assert not destination["enabled"] and destination["ciphertext"] == b""


def test_other_owner_expiry_cleanup_wipes_oauth_and_disables_destination(database):
    actor, workspace, app, client, path = setup(database)
    body = consent(client, path)
    identifier = client.post(path + "/oauth/complete", json=body).json()["id"]
    other = "expiry-owner-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
        session.execute(
            sa.update(consents)
            .where(consents.c.id == body["consent_id"])
            .values(expires_at=sa.func.now() - sa.text("interval '1 second'"))
        )
    with database.tenant(other, workspace) as session:
        session.execute(sa.text("SELECT expire_crm_oauth_consents()"))
    with database.tenant(actor, workspace) as session:
        row = ConsentStore(app.state.crm_store).get(session, body["consent_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
        assert not app.state.crm_store.get(session, identifier)["enabled"]


def test_uncertain_refresh_is_consumed_and_requires_reconsent(database):
    actor, workspace, app, client, path = setup(database)
    body = consent(client, path)
    identifier = client.post(path + "/oauth/complete", json=body).json()["id"]
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == identifier)
            .values(expires_at=sa.func.now())
        )

    def failure():
        raise RuntimeError("SENTINEL_REFRESH_ERROR")

    app.state.crm_oauth_provider.hook = failure
    response = client.post(path + f"/destinations/{identifier}/refresh")
    assert response.status_code == 409 and "SENTINEL" not in response.text
    assert client.post(path + f"/destinations/{identifier}/refresh").status_code == 409
    assert app.state.crm_oauth_provider.refreshes == 1
    with database.tenant(actor, workspace) as session:
        row = ConsentStore(app.state.crm_store).get(session, body["consent_id"])
        assert row["state"] == "revoked" and row["ciphertext"] == b""
        assert not app.state.crm_store.get(session, identifier)["enabled"]


def test_selection_automatically_refreshes_expired_oauth_access(database, tmp_path):
    from test_crm_preparation import MAPPING, crm_fixture

    actor, workspace, entity, _, plan, storage = crm_fixture(database, tmp_path)
    _, _, app, client, path = setup(database, owner=actor, workspace=workspace)
    app.state.evidence_storage = storage
    consent_body = consent(client, path)
    identifier = client.post(path + "/oauth/complete", json=consent_body).json()["id"]
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == identifier)
            .values(expires_at=sa.func.now())
        )
    body = {
        "destination_id": identifier,
        "plan_id": plan,
        "entity_id": entity,
        "field_map": MAPPING,
        "opt_in": False,
        "idempotency_key": "selection",
    }
    assert client.post(path + "/deliveries", json=body).status_code == 422
    assert app.state.crm_oauth_provider.refreshes == 0
    response = client.post(path + "/deliveries", json={**body, "opt_in": True})
    assert response.status_code == 202, response.text
    assert app.state.crm_oauth_provider.refreshes == 1
    assert response.json()["state"] == "pending"
