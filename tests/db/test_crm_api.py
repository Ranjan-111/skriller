"""Normal authenticated CRM API preserves the tested selection/owner fences."""

from uuid import uuid4

import pytest
from test_crm_preparation import MAPPING
from test_crm_queue import setup
from test_youtube_analytics import app_for

from skriller.crm.router import router
from skriller.db import WorkspaceRepository

pytestmark = pytest.mark.integration_db


def test_crm_api_selection_idempotency_cancel_and_owner_isolation(database, tmp_path):
    actor, workspace, a, b, plan, storage, store, destination = setup(database, tmp_path)
    _, _, app, client, _ = app_for(database, owner=actor, workspace=workspace)
    app.include_router(router)
    app.state.crm_store, app.state.evidence_storage = store, storage
    path = f"/v1/workspaces/{workspace}/crm"
    response = client.get(path + "/destinations")
    assert response.status_code == 200, response.text
    assert response.json()[0]["id"] == destination
    assert "fixture-crm-access-token" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = {
        "destination_id": destination,
        "plan_id": plan,
        "entity_id": a,
        "field_map": MAPPING,
        "opt_in": True,
        "idempotency_key": "selected",
    }
    queued = client.post(path + "/deliveries", json=body)
    assert queued.status_code == 202, queued.text
    delivery = queued.json()["id"]
    assert client.post(path + "/deliveries", json=body).json()["id"] == delivery
    assert client.post(path + "/deliveries", json={**body, "entity_id": b}).status_code == 422
    assert (
        client.post(
            path + "/deliveries", json={**body, "idempotency_key": "no-optin", "opt_in": False}
        ).status_code
        == 422
    )
    other = "crm-co-owner-" + str(uuid4())
    member = "crm-member-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
        WorkspaceRepository.add_member(session, member, "member")
    auth = {"Authorization": "Bearer " + other}
    assert client.get(path + "/deliveries", headers=auth).json() == []
    assert client.get(path + "/destinations", headers=auth).json() == []
    assert client.post(path + f"/deliveries/{delivery}/cancel", headers=auth).status_code == 409
    assert (
        client.post(path + f"/destinations/{destination}/revoke", headers=auth).status_code == 409
    )
    assert (
        client.get(
            path + "/destinations", headers={"Authorization": "Bearer " + member}
        ).status_code
        == 403
    )
    cancelled = client.post(path + f"/deliveries/{delivery}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert client.get(path + "/deliveries").json()[0]["state"] == "cancelled"
    revoked = client.post(path + f"/destinations/{destination}/revoke")
    assert revoked.status_code == 200 and revoked.json()["enabled"] is False
    assert (
        client.post(
            path + "/deliveries", json={**body, "idempotency_key": "after-revoke"}
        ).status_code
        == 409
    )


def test_crm_request_validation_and_inaccessible_selection_are_redacted(database, tmp_path):
    actor, workspace, a, _, plan, storage, store, destination = setup(database, tmp_path)
    _, _, app, client, _ = app_for(database, owner=actor, workspace=workspace)
    app.include_router(router)
    app.state.crm_store, app.state.evidence_storage = store, storage
    path = f"/v1/workspaces/{workspace}/crm/deliveries"
    body = {
        "destination_id": destination,
        "plan_id": plan,
        "entity_id": a,
        "field_map": MAPPING,
        "opt_in": True,
        "idempotency_key": "valid",
    }
    bad = client.post(path, json={**body, "extra": "SENTINEL_SECRET"})
    assert bad.status_code == 422 and "SENTINEL_SECRET" not in bad.text
    missing = client.post(path, json={**body, "entity_id": str(uuid4())})
    assert missing.status_code == 422
    assert "fixture-crm-access-token" not in missing.text
