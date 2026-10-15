"""Durable local qualification and live freshness through the real results API."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_identity import fact

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.contracts import Criterion, Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.schema import attempts, entities, evidence, qualifications, stage_checkpoints
from skriller.erasure import erase
from skriller.jobs.budget import current_usage, locked_job
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker, StageHandler
from skriller.qualification.identity import group_members, identity_reviews
from skriller.research.collection import finish_collection_pipeline
from skriller.research.qualification import checkpoint_qualification
from skriller.research.service import result_rows
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


def test_conflicting_observations_keep_distinct_current_source_citations(database):
    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        candidate = result_rows(session, job_id)[0]
        observations = []
        citation_ids = []
        for value, url in (
            ("Founder", "https://example.org/team"),
            ("Advisor", "https://example.net/bio"),
        ):
            saved = ResearchRepository.add_evidence(
                session,
                source_url=url,
                source_platform="web",
                collected_at=datetime.now(UTC),
                excerpt=value,
            )
            claim = ResearchRepository.claim(
                session,
                candidate["id"],
                "current_role",
                value,
                mode="observed",
                status="accepted",
                evidence_ids=[saved["id"]],
            )
            observations.append(
                {
                    "claim_id": claim["id"],
                    "field": "current_role",
                    "value": value,
                    "quote": value,
                    "status": claim["status"],
                }
            )
            citation_ids.append(saved["id"])
        entity = ResearchRepository.get_entity(session, candidate["id"])
        session.execute(
            sa.update(entities)
            .where(entities.c.id == candidate["id"], entities.c.workspace_id == workspace)
            .values(
                attributes={
                    **entity["attributes"],
                    "extraction": {
                        "status": "observed",
                        "failure_code": None,
                        "observations": observations,
                        "rejected_claims": 0,
                        "coverage_complete": True,
                        "omitted_chunks": 0,
                    },
                }
            )
        )
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    client = TestClient(app)
    response = client.get(f"/v1/jobs/{job_id}/results?workspace_id={workspace}")
    assert response.status_code == 200, response.text
    observation_rows = next(
        row for row in response.json()["results"] if row["id"] == candidate["id"]
    )["extraction"]["observations"]
    assert {row["status"] for row in observation_rows} == {"conflict"}
    assert {identifier for row in observation_rows for identifier in row["evidence_ids"]} == set(
        citation_ids
    )
    for identifier in citation_ids:
        citation = client.get(f"/v1/jobs/{job_id}/evidence/{identifier}?workspace_id={workspace}")
        assert citation.status_code == 200 and citation.json()["collected_at"]


def test_qualification_checkpoint_proposes_current_candidate_identity_without_merging(database):
    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        rows = result_rows(session, job_id)
        selected = [row["id"] for row in rows if row["title"] in {"Confirmed", "Unknown size"}]
        for identifier in selected:
            fact(session, identifier, "native_id.linkedin", "company:synthetic-company-id")
        job = locked_job(session, job_id)
        checkpoint_qualification(session, job, rows)
        reviews = session.execute(sa.select(identity_reviews)).mappings().all()
        assert len(reviews) == 1 and reviews[0]["state"] == "suggestion"
        assert {reviews[0]["source_id"], reviews[0]["target_id"]} == set(selected)
        assert group_members(session, selected[0]) == (selected[0],)


def fixture(database, deadline_seconds=1200):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Qualification pipeline")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Synthetic source facts")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            limits=Limits(deadline_seconds=deadline_seconds),
            sources=["web"],
            must_have=[
                Criterion(field="location", operator="eq", value="India"),
                Criterion(field="employee_count", operator="gte", value=10),
            ],
            preferences=[Criterion(field="industry", operator="eq", value="Software")],
            exclusions=[Criterion(field="company_type", operator="eq", value="Agency")],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        attempt = JobRepository.attempt(session, job["id"], "discover:fixture", "discovering")
    payload = {
        "actor_id": actor,
        "workspace_id": workspace,
        "job_id": job["id"],
        "attempt_id": attempt["id"],
    }

    def persist(session, _):
        identifiers = []
        for name, size, kind, organization in (
            ("Unknown size", None, "company", "Product"),
            ("Confirmed", "25", "company", "Product"),
            ("Excluded agency", "25", "company", "Agency"),
            ("Unknown identity", "25", "other", "Product"),
        ):
            entity = ResearchRepository.entity(
                session,
                kind,
                name,
                attributes={
                    "url": "https://example.org/" + str(uuid4()),
                    "source": "web",
                    "snippet": "Synthetic indexed reference",
                    "provider": "exa_keyless",
                    "evidence_kind": "search_snippet",
                    "qualification": "unverified",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "provenance": [],
                },
            )
            fact(session, entity["id"], "location", "India")
            fact(session, entity["id"], "company_type", organization)
            fact(session, entity["id"], "industry", "Software")
            if size:
                ev = ResearchRepository.add_evidence(
                    session,
                    source_url=entity["attributes"]["url"],
                    source_platform="web",
                    collected_at=datetime.now(UTC),
                    excerpt="25 employees",
                )
                ResearchRepository.claim(
                    session,
                    entity["id"],
                    "employee_count",
                    25,
                    mode="observed",
                    status="accepted",
                    evidence_ids=[ev["id"]],
                )
            identifiers.append(entity["id"])
        return identifiers

    worker = CheckpointWorker(
        database,
        {
            "discovering": StageHandler(
                lambda _: ("trusted-fixtures", Decimal(0), {"search_calls": 0}),
                persist,
                Decimal(0),
                {"search_calls": 0},
            )
        },
    )
    assert worker.execute(payload)["status"] == "checkpointed"
    return actor, workspace, job["id"]


def test_atomic_qualification_ranking_api_and_repeat_checkpoint(database):
    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        job = locked_job(session, job_id)
        updated = checkpoint_qualification(session, job, result_rows(session, job_id))
        assert updated["stage"] == "qualifying"
        assert (
            checkpoint_qualification(session, updated, result_rows(session, job_id))["version"]
            == updated["version"]
        )
        assert (
            session.execute(sa.select(sa.func.count()).select_from(qualifications)).scalar_one()
            == 16
        )
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(stage_checkpoints)
                .where(stage_checkpoints.c.stage == "qualifying")
            ).scalar_one()
            == 1
        )
        finish_collection_pipeline(session, updated)
        assert current_usage(session, job_id)[1]["llm_calls"] == 0
        rows = result_rows(session, job_id)
        assert rows[0]["title"] == "Confirmed" and rows[0]["fit"]["status"] == "confirmed"
        by_name = {row["title"]: row for row in rows}
        assert by_name["Unknown size"]["fit"]["status"] == "near_match"
        assert by_name["Unknown size"]["fit"]["essential"][1]["outcome"] == "unknown"
        assert by_name["Unknown identity"]["fit"]["status"] == "near_match"
        assert rows[-1]["title"] == "Excluded agency" and rows[-1]["fit"]["status"] == "excluded"
        assert all(row["qualification"] == "unverified" for row in rows)
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    response = TestClient(app).get(f"/v1/jobs/{job_id}/results?workspace_id={workspace}")
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["fit"]["status"] == "confirmed"
    groups = response.json()["groups"]
    assert len(groups["confirmed"]) == 1 and len(groups["near_match"]) == 2
    assert len(groups["excluded"]) == 1 and groups["unverified"] == []
    evidence_id = response.json()["results"][0]["fit"]["essential"][1]["evidence_ids"][0]
    evidence_path = f"/v1/jobs/{job_id}/evidence/{evidence_id}?workspace_id={workspace}"
    citation = TestClient(app).get(evidence_path)
    assert citation.status_code == 200, citation.text
    assert citation.json()["excerpt"] == "25 employees"
    assert citation.json()["content_hash_status"] == "stored_metadata_not_revalidated"
    assert citation.headers["cache-control"] == "private, no-store"
    assert "object_key" not in citation.text
    assert (
        TestClient(app)
        .get(f"/v1/jobs/{job_id}/evidence/{uuid4()}?workspace_id={workspace}")
        .status_code
        == 404
    )
    with database.tenant(actor, workspace) as session:
        unrelated = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org/unrelated",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="Unrelated evidence",
        )
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == evidence_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (
        TestClient(app)
        .get(f"/v1/jobs/{job_id}/evidence/{unrelated['id']}?workspace_id={workspace}")
        .status_code
        == 404
    )
    assert TestClient(app).get(evidence_path).status_code == 404
    app.dependency_overrides[require_identity] = lambda: Identity("foreign-" + str(uuid4()))
    assert TestClient(app).get(evidence_path).status_code == 404
    assert (
        TestClient(app).get(f"/v1/jobs/{job_id}/results?workspace_id={workspace}").status_code
        == 404
    )


def test_current_fit_downgrades_after_expiry_and_hides_erased_identity(database, tmp_path):
    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        finish_collection_pipeline(session, locked_job(session, job_id))
        confirmed = result_rows(session, job_id)[0]
        evidence_id = confirmed["fit"]["essential"][1]["evidence_ids"][0]
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == evidence_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with database.tenant(actor, workspace) as session:
        rows = result_rows(session, job_id)
        assert (
            next(row for row in rows if row["id"] == confirmed["id"])["fit"]["status"]
            == "near_match"
        )
        erase(
            session,
            EvidenceStorage(LocalBlobBackend(tmp_path)),
            confirmed["id"],
            request_key="erase-fit",
        )
    with database.tenant(actor, workspace) as session:
        assert confirmed["id"] not in {row["id"] for row in result_rows(session, job_id)}


def test_deadline_during_evaluation_rolls_back_only_derived_checkpoint(database, monkeypatch):
    import skriller.research.qualification as pipeline

    actor, workspace, job_id = fixture(database, deadline_seconds=2)
    original = pipeline.qualify_entity

    def expire(session, plan, entity):
        fit = original(session, plan, entity)
        session.execute(sa.text("SELECT pg_sleep(2.1)"))
        monkeypatch.setattr(pipeline, "qualify_entity", original)
        return fit

    monkeypatch.setattr(pipeline, "qualify_entity", expire)
    with database.tenant(actor, workspace) as session:
        assert (
            checkpoint_qualification(
                session, locked_job(session, job_id), result_rows(session, job_id)
            )
            is None
        )
        assert (
            session.execute(sa.select(sa.func.count()).select_from(qualifications)).scalar_one()
            == 0
        )
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(attempts)
                .where(attempts.c.stage == "qualifying")
            ).scalar_one()
            == 0
        )
        assert len(result_rows(session, job_id)) == 4
        assert JobRepository.get(session, job_id)["state"] == "paused"


def test_cancelled_run_has_no_qualification_checkpoint(database):
    from skriller.jobs.control import cancel

    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        job = cancel(session, job_id)
        assert checkpoint_qualification(session, job, result_rows(session, job_id)) is None
        assert (
            session.execute(sa.select(sa.func.count()).select_from(qualifications)).scalar_one()
            == 0
        )
