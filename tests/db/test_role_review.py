"""Owner reviews real saved claims; no source, model or browser impersonation."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_contacts import dated, setup

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.db import ResearchRepository, WorkspaceRepository
from skriller.db.schema import claims, evidence
from skriller.qualification.contacts import role_history, role_projection
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def prepared(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Engineer", "2021-01-01")
        new = dated(session, entity, "Founder", "2025-01-01")
    app = create_app(Settings(environment="test"))
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    client = TestClient(app)
    body = {"entity_id": entity, "previous": asdict(old), "replacement": asdict(new)}
    return actor, workspace, entity, old, new, app, client, body


def test_owner_previews_then_reviews_literal_source_dates_without_rewriting_claims(database):
    actor, workspace, entity, old, new, _app, client, body = prepared(database)
    base = f"/v1/workspaces/{workspace}/role-refreshes"
    preview = client.post(base + "/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.json()["previous"]["role"] == "Engineer"
    assert preview.json()["replacement"]["effective_date"] == "2025-01-01"
    approval = {
        **body,
        "same_subject_confirmed": True,
        "expected_review_hash": preview.json()["review_hash"],
    }
    for _ in range(2):
        result = client.post(base, json=approval)
        assert result.status_code == 200, result.text
        states = {row["claim_id"]: row for row in result.json()["roles"]}
        assert states[old.role_claim_id]["freshness"] == "historical"
        assert states[new.role_claim_id]["freshness"] == "current"
        assert states[new.role_claim_id]["event_at"].startswith("2025-01-01")
        assert result.json()["review_origin"] == "workspace_owner"
    with database.tenant(actor, workspace) as session:
        assert len(ResearchRepository.claims_for(session, entity)) == 4
        audit = (
            session.execute(sa.select(role_history).where(role_history.c.workspace_id == workspace))
            .mappings()
            .all()
        )
        assert len(audit) == 1 and audit[0]["actor_id"] == actor
        assert audit[0]["review_hash"] == preview.json()["review_hash"]
        assert audit[0]["previous_evidence_id"] == old.evidence_id
        assert audit[0]["replacement_evidence_id"] == new.evidence_id


@pytest.mark.parametrize("change", ["expiry", "quote", "inferred", "hash", "confirmation"])
def test_review_rejects_stale_or_changed_evidence_without_mutating_conflicts(database, change):
    actor, workspace, entity, _old, new, _app, client, body = prepared(database)
    base = f"/v1/workspaces/{workspace}/role-refreshes"
    preview = client.post(base + "/preview", json=body).json()
    approval = {
        **body,
        "same_subject_confirmed": True,
        "expected_review_hash": preview["review_hash"],
    }
    with database.tenant(actor, workspace) as session:
        if change == "expiry":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == new.evidence_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        elif change == "quote":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == new.evidence_id)
                .values(excerpt="Founder; effective 2025-01-01. Source changed.")
            )
        elif change == "inferred":
            session.execute(
                sa.update(claims).where(claims.c.id == new.role_claim_id).values(mode="inferred")
            )
    if change == "hash":
        approval["expected_review_hash"] = "0" * 64
    if change == "confirmation":
        approval["same_subject_confirmed"] = False
    assert client.post(base, json=approval).status_code == 409
    with database.tenant(actor, workspace) as session:
        assert {row["status"] for row in ResearchRepository.claims_for(session, entity)} == {
            "conflict"
        }
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(role_history)
                .where(role_history.c.workspace_id == workspace)
            ).scalar_one()
            == 0
        )


def test_role_review_owner_and_original_subject_scoping(database):
    actor, workspace, _entity, _old, _new, app, client, body = prepared(database)
    member = "role-member-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
        other = ResearchRepository.entity(session, "person", "Different subject")["id"]
    base = f"/v1/workspaces/{workspace}/role-refreshes"
    assert client.post(base + "/preview", json={**body, "entity_id": other}).status_code == 409
    app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.post(base + "/preview", json=body).status_code == 403
    app.dependency_overrides[require_identity] = lambda: Identity("foreign-" + str(uuid4()))
    assert client.post(base + "/preview", json=body).status_code == 403


def test_reviewed_pair_does_not_suppress_a_third_unresolved_role_conflict(database):
    actor, workspace, entity, _old, _new, _app, client, body = prepared(database)
    with database.tenant(actor, workspace) as session:
        dated(session, entity, "Advisor", "2024-01-01")
    base = f"/v1/workspaces/{workspace}/role-refreshes"
    preview = client.post(base + "/preview", json=body).json()
    result = client.post(
        base,
        json={
            **body,
            "same_subject_confirmed": True,
            "expected_review_hash": preview["review_hash"],
        },
    )
    assert result.status_code == 200, result.text
    with database.tenant(actor, workspace) as session:
        assert not any(row["freshness"] == "current" for row in role_projection(session, entity))
