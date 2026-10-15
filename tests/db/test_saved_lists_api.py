"""Saved-list HTTP contracts against PostgreSQL's restricted tenant role."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_saved_lists import fact, setup

from skriller.db import ResearchRepository, WorkspaceRepository
from skriller.db.schema import suppressions
from skriller.lists import list_snapshots
from skriller.lists_router import router


def api(database):
    owner, workspace, entity, plan = setup(database)
    app = FastAPI()
    app.include_router(router)
    app.state.database = database
    app.state.settings = SimpleNamespace(firebase_project_id="list-fixture")
    app.state.identity_verifier = lambda token, project: {
        "sub": token,
        "aud": project,
        "iss": f"https://securetoken.google.com/{project}",
    }
    client = TestClient(app, headers={"Authorization": f"Bearer {owner}"})
    return owner, workspace, entity, plan, client


def create(client, workspace, entity, plan):
    response = client.post(
        f"/v1/workspaces/{workspace}/lists",
        json={"name": "API fixture", "plan_id": plan, "entity_ids": [entity]},
    )
    assert response.status_code == 201, response.text
    return f"/v1/workspaces/{workspace}/lists/{response.json()['id']}"


def test_http_snapshots_freeze_evidence_and_refresh_requires_latest_revision(database):
    owner, workspace, entity, plan, client = api(database)
    with database.tenant(owner, workspace) as session:
        claim_id, evidence = fact(session, entity, "company", "Example", excerpt="x" * 5000)
        fact(session, entity, "email", "generic@company.example")
        fact(session, entity, "work_email", "person@company.example")
    path = create(client, workspace, entity, plan)
    before = client.get(path + "/snapshots/1")
    assert before.status_code == 200
    assert before.headers["x-skriller-snapshot-view"] == "frozen"
    assert before.headers["x-skriller-snapshot-revision"] == "1"
    assert before.headers["cache-control"] == "private, no-store"
    values = before.json()["payload"]["members"][0]["values"]
    item = next(value for value in values if value["field"] == "company")
    assert item["evidence"][0]["id"] == evidence
    assert item["claim_ids"] == [claim_id] and item["source_entity_ids"] == [entity]
    assert item["evidence"][0]["source_url"] == "https://example.org/profile"
    assert item["evidence"][0]["collected_at"]
    assert item["evidence"][0]["excerpt"] == "x" * 4096
    assert item["evidence"][0]["excerpt_truncated"] is True
    assert any(value["value"] == "person@company.example" for value in values)
    assert not any(value["value"] == "generic@company.example" for value in values)
    refreshed = client.post(
        path + "/refresh", json={"entity_ids": [entity], "expected_revision": 1}
    )
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["revision"] == 2
    assert refreshed.json()["payload"]["refresh_scope"] == "persisted_reviewed_facts_only"
    latest = client.get(path + "/snapshots/latest")
    assert latest.json() == refreshed.json()
    assert latest.headers["x-skriller-snapshot-view"] == "latest"
    assert latest.headers["etag"] != before.headers["etag"]
    stale = client.post(path + "/refresh", json={"entity_ids": [], "expected_revision": 1})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_snapshot_revision"
    assert client.get(path + "/snapshots/1").json() == before.json()
    with pytest.raises(sa.exc.DBAPIError), database.tenant(owner, workspace) as session:
        session.execute(sa.update(list_snapshots).values(payload={}))


def test_http_members_read_but_owner_is_required_for_mutations(database):
    owner, workspace, entity, plan, client = api(database)
    path = create(client, workspace, entity, plan)
    member = f"list-member-{uuid4()}"
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    client.headers["Authorization"] = f"Bearer {member}"
    assert client.get(f"/v1/workspaces/{workspace}/lists").status_code == 200
    assert client.get(path + "/snapshots/latest").status_code == 200
    assert client.get(path + "/snapshots/1").status_code == 200
    assert (
        client.post(
            f"/v1/workspaces/{workspace}/lists",
            json={"name": "Denied", "plan_id": plan, "entity_ids": []},
        ).status_code
        == 403
    )
    assert (
        client.post(path + "/refresh", json={"entity_ids": [], "expected_revision": 1}).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/workspaces/{workspace}/lists/suppressions",
            json={"kind": "entity", "key": entity, "reason": "Opt out"},
        ).status_code
        == 403
    )


def test_http_foreign_scope_and_missing_auth_do_not_disclose_resources(database):
    owner, workspace, entity, plan, client = api(database)
    path = create(client, workspace, entity, plan)
    other = database.create_workspace(owner, "Other list API fixture")["id"]
    foreign = path.replace(workspace, other)
    assert client.get(foreign + "/snapshots/latest").status_code == 404
    assert client.get(foreign + "/snapshots/1").status_code == 404
    assert (
        client.post(
            foreign + "/refresh", json={"entity_ids": [], "expected_revision": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/workspaces/{other}/lists",
            json={"name": "Foreign", "plan_id": plan, "entity_ids": []},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/workspaces/{other}/lists/suppressions",
            json={"kind": "entity", "key": entity, "reason": "Foreign"},
        ).status_code
        == 404
    )
    client.headers["Authorization"] = f"Bearer outsider-{uuid4()}"
    assert client.get(path + "/snapshots/1").status_code == 404
    assert (
        client.post(path + "/refresh", json={"entity_ids": [], "expected_revision": 1}).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/workspaces/{workspace}/lists/suppressions",
            json={"kind": "entity", "key": entity, "reason": "Foreign"},
        ).status_code
        == 404
    )
    del client.headers["Authorization"]
    assert client.get(path + "/snapshots/latest").status_code == 401
    assert (
        client.post(
            f"/v1/workspaces/{workspace}/lists",
            json={"name": "Denied", "plan_id": plan, "entity_ids": []},
        ).status_code
        == 401
    )


def test_http_suppression_applies_on_refresh_without_rewriting_history(database):
    owner, workspace, entity, plan, client = api(database)
    with database.tenant(owner, workspace) as session:
        fact(session, entity, "company", "Example")
    path = create(client, workspace, entity, plan)
    before = client.get(path + "/snapshots/1").json()
    response = client.post(
        f"/v1/workspaces/{workspace}/lists/suppressions",
        json={"kind": "entity", "key": entity, "reason": "Opt out"},
    )
    assert response.status_code == 201
    assert response.json() == {
        "state": "active",
        "kind": "entity",
        "applies_to": "future_list_refresh",
        "historical_snapshot_action": "unchanged",
    }
    refreshed = client.post(
        path + "/refresh", json={"entity_ids": [entity], "expected_revision": 1}
    )
    assert refreshed.status_code == 201
    assert refreshed.json()["payload"]["members"] == []
    assert refreshed.json()["payload"]["omitted"] == [{"entity_id": entity, "reason": "suppressed"}]
    assert client.get(path + "/snapshots/1").json() == before


@pytest.mark.parametrize(
    "kind,key,canonical",
    [
        (
            "profile",
            "https://example.org/profile?utm_source=fixture",
            "https://example.org/profile",
        ),
        ("email", "Person@Company.Example", "person@company.example"),
        ("domain", "Company.Example", "company.example"),
    ],
)
def test_http_suppression_keys_are_canonical_and_idempotent(database, kind, key, canonical):
    owner, workspace, _, _, client = api(database)
    path = f"/v1/workspaces/{workspace}/lists/suppressions"
    for _ in range(2):
        assert (
            client.post(path, json={"kind": kind, "key": key, "reason": "Opt out"}).status_code
            == 201
        )
    with database.tenant(owner, workspace) as session:
        rows = (
            session.execute(sa.select(suppressions).where(suppressions.c.kind == kind))
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert rows[0]["key"] == canonical


@pytest.mark.parametrize(
    "body",
    [
        {"entity_ids": [], "expected_revision": True},
        {"entity_ids": [], "expected_revision": "1"},
        {"entity_ids": [], "expected_revision": 0},
        {"entity_ids": [], "expected_revision": 1, "caller_values": []},
    ],
)
def test_http_refresh_rejects_untyped_or_caller_supplied_values(database, body):
    _, workspace, entity, plan, client = api(database)
    path = create(client, workspace, entity, plan)
    assert client.post(path + "/refresh", json=body).status_code == 422
    assert client.get(path + "/snapshots/latest").json()["revision"] == 1


def test_http_contact_ownership_is_not_transferred_to_alias(database):
    owner, workspace, entity, plan, client = api(database)
    from skriller.qualification.identity import review_link, suggest

    with database.tenant(owner, workspace) as session:
        alias = ResearchRepository.entity(session, "person", "Alias")["id"]
        fact(session, entity, "work_email", "person@company.example")
        fact(session, entity, "native_id.linkedin", "person:contact-api-fixture")
        fact(session, alias, "native_id.linkedin", "person:contact-api-fixture")
        review_link(session, suggest(session, entity, alias)["id"])
    path = create(client, workspace, alias, plan)
    values = client.get(path + "/snapshots/latest").json()["payload"]["members"][0]["values"]
    assert not any(value["field"] == "work_email" for value in values)


def test_http_unverified_suppression_alias_retains_review_without_values(database):
    owner, workspace, entity, plan, client = api(database)
    with database.tenant(owner, workspace) as session:
        alias = ResearchRepository.entity(session, "person", "Unverified alias")["id"]
        fact(session, entity, "native_id.linkedin", "person:suppression-api-fixture")
        fact(
            session,
            alias,
            "native_id.linkedin",
            "person:suppression-api-fixture",
            status="unverified",
        )
        fact(session, alias, "company", "Example")
    response = client.post(
        f"/v1/workspaces/{workspace}/lists/suppressions",
        json={"kind": "entity", "key": entity, "reason": "Opt out"},
    )
    assert response.status_code == 201
    path = create(client, workspace, alias, plan)
    item = client.get(path + "/snapshots/latest").json()["payload"]["members"][0]
    assert item["identity_status"] == "suppression_unresolved"
    assert item["fit"]["status"] == "near_match"
    assert item["values"] == []


@pytest.mark.parametrize(
    "kind,key",
    [
        ("entity", "not-a-uuid"),
        ("profile", "file:///tmp/contact"),
        ("email", "not-an-email"),
        ("domain", "invalid domain"),
    ],
)
def test_http_invalid_suppression_does_not_persist(database, kind, key):
    owner, workspace, _, _, client = api(database)
    result = client.post(
        f"/v1/workspaces/{workspace}/lists/suppressions",
        json={"kind": kind, "key": key, "reason": "Opt out"},
    )
    assert result.status_code == 422
    with database.tenant(owner, workspace) as session:
        assert (
            session.execute(sa.select(sa.func.count()).select_from(suppressions)).scalar_one() == 0
        )


def test_http_create_rejects_caller_values_and_foreign_members_without_partial_list(database):
    owner, workspace, entity, plan, client = api(database)
    other = database.create_workspace(owner, "Other entities")["id"]
    with database.tenant(owner, other) as session:
        foreign = ResearchRepository.entity(session, "person", "Foreign")["id"]
    path = f"/v1/workspaces/{workspace}/lists"
    body = {"name": "Invalid", "plan_id": plan, "entity_ids": [entity]}
    assert (
        client.post(path, json={**body, "values": [{"email": "invented@example.org"}]}).status_code
        == 422
    )
    assert client.post(path, json={**body, "entity_ids": [foreign]}).status_code == 404
    assert client.post(path, json={**body, "entity_ids": [entity, entity]}).status_code == 422
    assert client.get(path).json() == []
