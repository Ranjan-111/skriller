"""Owner opt-in, explicit resume and no implicit external execution over HTTP."""

import pytest
from fastapi.testclient import TestClient
from test_saved_lists_api import api, create

from skriller.db import ConversationRepository
from skriller.schedules_router import router

pytestmark = pytest.mark.integration_db


def test_schedule_http_opt_in_pause_resume_and_duplicate_request(database):
    owner, workspace, entity, plan, list_client = api(database)
    with database.tenant(owner, workspace) as session:
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
    path = create(list_client, workspace, entity, plan)
    app = list_client.app
    app.include_router(router)
    client = TestClient(app, headers={"Authorization": f"Bearer {owner}"})
    url = f"/v1/workspaces/{workspace}/research-schedules"
    body = {"list_id": path.rsplit("/", 1)[1], "opt_in": True, "cadence_hours": 24, "max_runs": 2}
    assert client.post(url, json={**body, "opt_in": False}).status_code == 422
    assert client.post(url, json={**body, "cadence_hours": 0}).status_code == 422
    response = client.post(url, json=body)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    schedule = response.json()
    assert schedule["enabled"] and schedule["run_count"] == 0 and schedule["last_job_id"] is None
    assert client.post(url, json=body).status_code == 409
    assert client.get(url).json()[0]["id"] == schedule["id"]
    assert client.delete(url + f"/{schedule['id']}").status_code == 204
    assert client.get(url).json()[0]["enabled"] is False
    assert client.post(url + f"/{schedule['id']}/resume", json={"opt_in": False}).status_code == 422
    resumed = client.post(url + f"/{schedule['id']}/resume", json={"opt_in": True})
    assert resumed.status_code == 200 and resumed.json()["enabled"]
    assert resumed.json()["run_count"] == 0
    assert client.get(url + f"/{schedule['id']}/runs").json() == []
    client.headers.clear()
    assert client.get(url).status_code == 401
