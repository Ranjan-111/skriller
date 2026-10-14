from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_planning_bootstrap import SETTINGS, Fixture, run, setup
from test_research_workflow import prepare

from skriller.api import create_app
from skriller.auth import Identity, require_identity

pytestmark = pytest.mark.integration_db


def client_for(database, payload):
    app = create_app(SETTINGS)
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(payload["actor_id"])
    return app, TestClient(app)


def test_search_only_seed_is_not_labelled_ai_interpretation(database, monkeypatch):
    actor = f"plan-view-{uuid4()}"
    app, client, accepted = prepare(database, monkeypatch, actor)
    endpoint = f"/v1/jobs/{accepted['job_id']}/plan"
    result = client.get(endpoint)
    assert result.status_code == 200
    assert result.json()["status"] == "search_objective"
    assert result.json()["interpretation"]["must_have"] == []
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.get(endpoint).status_code == 404


def test_plan_view_shows_actual_immutable_successor(database):
    payload = setup(database)
    _, client = client_for(database, payload)
    endpoint = f"/v1/jobs/{payload['job_id']}/plan"
    before = client.get(endpoint).json()
    assert before["status"] == "planning" and before["interpretation"]["revision"] == 1
    outcome = run(database, payload, Fixture())
    after = client.get(endpoint).json()
    assert after["status"] == "ready" and after["plan_id"] == outcome["plan_id"]
    assert after["interpretation"]["revision"] == 2
    assert after["interpretation"]["limits"] == before["interpretation"]["limits"]


def test_plan_view_exposes_clarification_and_rejected_state_without_raw_errors(database):
    payload = setup(database, "Find founders in Paris")
    _, client = client_for(database, payload)
    run(
        database,
        payload,
        Fixture(
            {
                "entity_type": "person",
                "entity_quote": "founders",
                "rules": [["must_have", "location", "contains", "Paris", "in Paris"]],
            }
        ),
    )
    data = client.get(f"/v1/jobs/{payload['job_id']}/plan").json()
    assert data["status"] == "clarification_required"
    assert data["interpretation"]["clarification"]
    rejected = setup(database)
    _, client = client_for(database, rejected)
    run(database, rejected, Fixture({"entity_type": "person", "entity_quote": "invented"}))
    data = client.get(f"/v1/jobs/{rejected['job_id']}/plan").json()
    assert data["status"] == "rejected" and data["interpretation"]["revision"] == 1
