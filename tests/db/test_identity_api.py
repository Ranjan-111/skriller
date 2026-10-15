"""Real tenant transactions for owner identity review and reversible history."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_identity import fact, setup

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.db import WorkspaceRepository
from skriller.qualification.identity import group_claims, group_members, identity_events
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def client_for(database, actor):
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    return TestClient(app)


def test_review_api_repeats_safely_and_reversal_preserves_original_claims(database):
    actor, workspace, first, second = setup(database, kind="company")
    with database.tenant(actor, workspace) as session:
        for entity in (first, second):
            fact(session, entity, "domain", "company.example.org")
            fact(session, entity, "legal_name", "Synthetic Company")
            fact(session, entity, "country", "India")
    client = client_for(database, actor)
    path = f"/v1/workspaces/{workspace}/identity-reviews"
    response = client.post(path, json={"source_id": first, "target_id": second})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    review = response.json()
    assert review["state"] == "suggestion" and "created_by" not in review
    assert client.post(path, json={"source_id": second, "target_id": first}).json() == review
    approve = f"{path}/{review['id']}/approve"
    assert client.post(approve).json()["state"] == "linked"
    assert client.post(approve).json()["state"] == "linked"
    with database.tenant(actor, workspace) as session:
        assert set(group_members(session, first)) == {first, second}
        assert {row["entity_id"] for row in group_claims(session, first)} == {first, second}
    reverse = f"{path}/{review['id']}/reverse"
    assert client.post(reverse).json()["state"] == "reversed"
    assert client.post(reverse).json()["state"] == "reversed"
    assert client.post(approve).status_code == 409
    assert client.get(path).json()[0]["state"] == "reversed"
    with database.tenant(actor, workspace) as session:
        assert group_members(session, first) == (first,)
        assert {row["entity_id"] for row in group_claims(session, first)} == {first}
        assert (
            session.execute(sa.select(sa.func.count()).select_from(identity_events)).scalar_one()
            == 3
        )


def test_owner_review_cannot_override_insufficient_identity(database):
    actor, workspace, first, second = setup(database)
    client = client_for(database, actor)
    path = f"/v1/workspaces/{workspace}/identity-reviews"
    review = client.post(path, json={"source_id": first, "target_id": second}).json()
    outcome = client.post(f"{path}/{review['id']}/approve")
    assert outcome.status_code == 200
    assert outcome.json()["state"] == "suggestion"
    assert outcome.json()["review_outcome"] == "insufficient_identity"


def test_identity_api_owner_member_foreign_and_input_boundaries(database):
    actor, workspace, first, second = setup(database)
    member = f"identity-member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    path = f"/v1/workspaces/{workspace}/identity-reviews"
    body = {"source_id": first, "target_id": second}
    owner = client_for(database, actor)
    review = owner.post(path, json=body).json()
    for subject in (member, f"identity-foreign-{uuid4()}"):
        client = client_for(database, subject)
        assert client.post(path, json=body).status_code == 403
        assert client.post(f"{path}/{review['id']}/approve").status_code == 403
        assert client.get(path).status_code == (200 if subject == member else 404)
    assert owner.post(path, json=body | {"reason": "trust me"}).status_code == 422
    assert owner.post(path, json=body | {"target_id": first}).status_code == 409
    assert owner.post(path, json=body | {"target_id": str(uuid4())}).status_code == 404
    assert owner.post(f"{path}/{uuid4()}/approve").status_code == 404
    assert owner.post(f"{path}/{review['id']}/force").status_code == 422
    app = create_app(Settings())
    app.state.database = database
    assert TestClient(app).get(path).status_code == 401


def test_review_context_shows_current_proof_with_permission_and_tenant_boundaries(database):
    actor, workspace, first, second = setup(database, kind="company")
    member = f"context-member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
        for entity in (first, second):
            fact(session, entity, "domain", "company.example.org")
            fact(session, entity, "legal_name", "Synthetic Company")
            fact(session, entity, "country", "India")
        fact(session, first, "native_id.linkedin", "company:expired-secret", expired=True)
    owner = client_for(database, actor)
    path = f"/v1/workspaces/{workspace}/identity-reviews"
    review = owner.post(path, json={"source_id": first, "target_id": second}).json()
    detail_path = f"{path}/{review['id']}"
    response = owner.get(detail_path)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    detail = response.json()
    assert detail["eligible"] and detail["can_review"]
    for subject in (detail["source"], detail["target"]):
        assert subject["available"] and subject["context_complete"]
        assert {row["field"] for row in subject["identity_facts"]} == {
            "domain",
            "legal_name",
            "country",
        }
        assert all(row["evidence"][0]["excerpt"] for row in subject["identity_facts"])
    assert "expired-secret" not in response.text and "object_key" not in response.text
    assert client_for(database, member).get(detail_path).json()["can_review"] is False
    assert client_for(database, f"foreign-{uuid4()}").get(detail_path).status_code == 404
    assert owner.get(f"{path}/{uuid4()}").status_code == 404
