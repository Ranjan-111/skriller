"""Authentication, owner configuration, one-time secret and sanitized HTTP errors."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_saved_lists import setup

from skriller.connections.keys import Keyring
from skriller.db import WorkspaceRepository
from skriller.lists import create_list
from skriller.security.urls import Destination
from skriller.webhooks import transport
from skriller.webhooks.router import router

pytestmark = pytest.mark.integration_db


def test_webhook_http_owner_boundary_and_once_only_secret(database, tmp_path, monkeypatch):
    monkeypatch.setattr(
        transport,
        "resolve_public_destination",
        lambda url: Destination(url, "receiver.example", 443, ("93.184.216.34",)),
    )
    actor, workspace, entity, plan = setup(database)
    member = f"member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        saved = create_list(session, "Webhook API", plan, (entity,))
        WorkspaceRepository.add_member(session, member)
    path = tmp_path / "key.json"
    Keyring.create_file(path)
    app = FastAPI()
    app.include_router(router)
    app.state.database = database
    app.state.settings = SimpleNamespace(
        firebase_project_id="webhook-fixture", source_encryption_key_file=str(path)
    )
    app.state.identity_verifier = lambda token, project: {
        "sub": token,
        "aud": project,
        "iss": f"https://securetoken.google.com/{project}",
    }
    client = TestClient(app, headers={"Authorization": f"Bearer {actor}"})
    url = f"/v1/workspaces/{workspace}/webhooks"
    body = {"list_id": saved["id"], "url": "https://receiver.example/hook", "opt_in": True}
    result = client.post(url, json=body)
    assert result.status_code == 201, result.text
    assert result.headers["cache-control"] == "private, no-store"
    secret = result.json()["signing_secret"]
    identifier = result.json()["id"]
    listed = client.get(url)
    assert listed.status_code == 200 and secret not in listed.text
    assert "secret_ciphertext" not in listed.text and "nonce" not in listed.text
    assert client.post(url, json={**body, "opt_in": False}).status_code == 422
    assert (
        client.post(
            url, json={**body, "url": "https://receiver.example/?secret=SENTINEL"}
        ).status_code
        == 422
    )
    invalid = client.post(url, json={**body, "url": {"secret": "SENTINEL"}})
    assert invalid.status_code == 422 and "SENTINEL" not in invalid.text
    client.headers["Authorization"] = f"Bearer {member}"
    assert client.get(url).status_code == 403
    assert client.post(url, json=body).status_code == 403
    assert client.delete(url + f"/{identifier}").status_code == 403
    assert client.get(url + f"/{identifier}/deliveries").status_code == 403
    client.headers["Authorization"] = f"Bearer stranger-{uuid4()}"
    assert client.get(url).status_code == 404
    client.headers["Authorization"] = f"Bearer {actor}"
    assert client.delete(url + f"/{identifier}").status_code == 204
    assert client.get(url).json()[0]["enabled"] is False
