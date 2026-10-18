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
from skriller.connectors.linkedin_read import LinkedInReadResult
from skriller.db import ResearchRepository, WorkspaceRepository
from skriller.db.schema import claims, entities, evidence
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


def native_profile(database):
    actor, workspace, _, _, _, app, client, _ = prepared(database)
    now = datetime.now(UTC)
    text = "Engineer; effective 2021-01-01. Founder; effective 2025-01-01."
    resource = LinkedInReadResult(
        resource_kind="profile",
        source_url="https://www.linkedin.com/in/synthetic/",
        section="main_profile",
        text=text,
        text_truncated=False,
        observed_at=now,
    )
    with database.tenant(actor, workspace) as session:
        saved = ResearchRepository.add_evidence(
            session,
            source_url=resource.source_url,
            source_platform="linkedin",
            collected_at=now,
            excerpt=text,
        )
        attributes = {
            "source": "linkedin",
            "provider": "linkedin_mcp",
            "url": resource.source_url,
            "linkedin_read": {
                "evidence_id": saved["id"],
                "resource": resource.model_dump(mode="json"),
            },
        }
        entity = ResearchRepository.entity(
            session, "other", "Unreviewed profile", attributes=attributes
        )["id"]
        refs = []
        for role, effective in (("Engineer", "2021-01-01"), ("Founder", "2025-01-01")):
            role_claim = ResearchRepository.claim(
                session,
                entity,
                "job_title",
                role,
                mode="observed",
                status="unverified",
                evidence_ids=[saved["id"]],
            )
            date_claim = ResearchRepository.claim(
                session,
                entity,
                "role_effective_date",
                effective,
                mode="observed",
                status="unverified",
                evidence_ids=[saved["id"]],
            )
            refs.append(
                {
                    "role_claim_id": role_claim["id"],
                    "date_claim_id": date_claim["id"],
                    "evidence_id": saved["id"],
                }
            )
    return (
        actor,
        workspace,
        entity,
        saved["id"],
        attributes,
        app,
        client,
        {"entity_id": entity, "previous": refs[0], "replacement": refs[1]},
    )


@pytest.mark.parametrize(
    "change",
    [None, "confirmation", "company", "platform", "resource", "excerpt", "expired", "future"],
)
def test_native_person_confirmation_requires_current_exact_original_profile(database, change):
    actor, workspace, entity, evidence_id, attributes, _app, client, body = native_profile(database)
    with database.tenant(actor, workspace) as session:
        if change == "company":
            session.execute(
                sa.update(entities).where(entities.c.id == entity).values(kind="company")
            )
        elif change == "platform":
            attributes["source"] = "reddit"
        elif change == "resource":
            attributes["linkedin_read"]["resource"]["resource_kind"] = "post"
        elif change == "excerpt":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == evidence_id)
                .values(excerpt="Changed source text")
            )
        elif change == "expired":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == evidence_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        elif change == "future":
            future = datetime.now(UTC) + timedelta(days=1)
            attributes["linkedin_read"]["resource"]["observed_at"] = future.isoformat()
            session.execute(
                sa.update(evidence).where(evidence.c.id == evidence_id).values(collected_at=future)
            )
        session.execute(
            sa.update(entities).where(entities.c.id == entity).values(attributes=attributes)
        )
    path = f"/v1/workspaces/{workspace}/role-refreshes"
    preview = client.post(path + "/preview", json=body)
    if change not in {None, "confirmation"}:
        assert preview.status_code == 409, preview.text
    else:
        assert preview.status_code == 200, preview.text
        assert preview.json()["requires_person_confirmation"] is True
        approved = client.post(
            path,
            json={
                **body,
                "same_subject_confirmed": True,
                "person_subject_confirmed": change is None,
                "expected_review_hash": preview.json()["review_hash"],
            },
        )
        assert approved.status_code == (200 if change is None else 409), approved.text
    with database.tenant(actor, workspace) as session:
        current = ResearchRepository.get_entity(session, entity)
        assert current["kind"] == (
            "person" if change is None else "company" if change == "company" else "other"
        )
        assert current["attributes"]["linkedin_read"]["resource"]["subject_identity"] == "unknown"
        if change is None:
            assert (
                current["attributes"]["_person_subject_review"]["review_hash"]
                == preview.json()["review_hash"]
            )
            assert current["attributes"]["_person_subject_review"]["actor_id"] == actor
        else:
            assert "_person_subject_review" not in current["attributes"]
            assert not any(
                row["status"] == "accepted"
                for row in ResearchRepository.claims_for(session, entity)
            )
