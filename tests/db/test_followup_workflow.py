"""Follow-up API and worker use current qualification evidence in real PostgreSQL."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_qualification_pipeline import fixture
from test_research_reports import Stub
from test_research_workflow import Provider, isolate_capacity

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.schema import evidence, followup_reports, job_events, jobs
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import current_usage, locked_job
from skriller.jobs.worker import CheckpointWorker
from skriller.lists import create_list, snapshot
from skriller.research.bootstrap import execute_planning
from skriller.research.collection import finish_collection_pipeline
from skriller.research.followups import execute_followup
from skriller.research.planner import PlanningInvalid
from skriller.research.qualification import checkpoint_qualification
from skriller.research.refinements import Refinement, apply_refinement
from skriller.research.service import execute_discovery, result_rows
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


@pytest.mark.parametrize(
    "change,prompt",
    [
        (["relax", "location", "eq", "India", "companies in India"], "companies in India"),
        (["relax", "employee_count", "gte", "10", "remove 100 employees"], "remove 100 employees"),
        (["exclude", "industry", "eq", "Healthcare", "Exclude Software"], "Exclude Software"),
        (["require", "employee_count", "gte", "25", "250 employees"], "250 employees"),
    ],
)
def test_model_delta_rejects_unrequested_relaxation_and_invented_values(change, prompt):
    from skriller.contracts import Criterion

    original = SearchPlan(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        entity_type="company",
        must_have=[
            Criterion(field="location", operator="eq", value="India"),
            Criterion(field="employee_count", operator="gte", value=10),
        ],
    )
    with pytest.raises(PlanningInvalid):
        apply_refinement(original, prompt, Refinement(changes=[change]), 2)


def test_unclear_company_category_is_clarified_without_partial_changes():
    original = SearchPlan(
        workspace_id=uuid4(), conversation_id=uuid4(), revision=1, entity_type="company"
    )
    prompt = "Exclude Product companies"
    revised = apply_refinement(
        original,
        prompt,
        Refinement(changes=[["exclude", "company_name", "eq", "Product", prompt]]),
        2,
    )
    assert revised.clarification
    assert revised.exclusions == original.exclusions
    assert revised.limits == original.limits


@pytest.mark.skipif(
    os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") != "1",
    reason="Explicit opt-in required for the installed local Ollama model",
)
def test_local_ollama_refinement_preserves_budget(database, monkeypatch):
    actor, workspace, source_job_id, _, _, client = setup(database, monkeypatch)
    settings = Settings(enable_ai_planning=True)
    client.app.state.settings = settings
    submitted = client.post(
        f"/v1/jobs/{source_job_id}/refine?workspace_id={workspace}",
        json={"prompt": "Exclude companies whose company type is Product"},
    )
    assert submitted.status_code == 202, submitted.text
    new_id = submitted.json()["job_id"]
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": new_id}
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    outcome = execute_planning(database, payload, settings)
    assert outcome.get("planning_status") == "ready", outcome
    with database.tenant(actor, workspace) as session:
        old = JobRepository.get(session, source_job_id)
        new = JobRepository.get(session, new_id)
        original = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, old["plan_id"])["interpretation"]
        )
        revised = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, new["plan_id"])["interpretation"]
        )
        assert revised.limits == original.limits
        assert any(
            item.field == "company_type" and str(item.value).casefold() == "product"
            for item in revised.exclusions
        )


def setup(database, monkeypatch):
    actor, workspace, source_job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        rows = result_rows(session, source_job_id)
        selected = next(row for row in rows if row["title"] == "Confirmed")
        checkpoint_qualification(session, locked_job(session, source_job_id), rows)
        finish_collection_pipeline(session, locked_job(session, source_job_id))
        evidence_id = (
            selected["fit"]["essential"][1]["evidence_ids"][0] if "fit" in selected else None
        )
        if evidence_id is None:
            selected = next(
                row for row in result_rows(session, source_job_id) if row["title"] == "Confirmed"
            )
            evidence_id = selected["fit"]["essential"][1]["evidence_ids"][0]
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    return actor, workspace, source_job_id, selected["id"], evidence_id, TestClient(app)


def submit(
    client,
    source_job_id,
    workspace,
    entity_id,
    *,
    key="first",
    question="Why does this company fit?",
):
    return client.post(
        f"/v1/jobs/{source_job_id}/followups?workspace_id={workspace}",
        json={"entity_id": entity_id, "question": question},
        headers={"Idempotency-Key": key},
    )


def test_followup_job_cites_only_current_qualification_evidence(database, monkeypatch):
    actor, workspace, source_job_id, entity_id, evidence_id, client = setup(database, monkeypatch)
    created = submit(client, source_job_id, workspace, entity_id)
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    pending = client.get(f"/v1/jobs/{job_id}/report?workspace_id={workspace}")
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    assert pending.json()["observations"] == []
    with database.tenant(actor, workspace) as session:
        request = (
            session.execute(sa.select(followup_reports).where(followup_reports.c.job_id == job_id))
            .mappings()
            .one()
        )
        assert evidence_id in request["evidence_ids"]
        assert request["citation_hashes"] == {}
        assert JobRepository.get(session, job_id)["purpose"] == "followup"
        quote = session.execute(
            sa.select(evidence.c.excerpt).where(evidence.c.id == evidence_id)
        ).scalar_one()
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job_id}
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    assert scheduled["status"] == "scheduled"
    payload["attempt_id"] = scheduled["attempt_id"]
    stub = Stub([{"evidence_id": evidence_id, "quote": quote}])
    outcome = execute_followup(database, payload, LocalStructuredModel(model_instance=stub))
    assert outcome == {"status": "checkpointed", "report_status": "answered"}
    assert stub.calls == 1
    response = client.get(f"/v1/jobs/{job_id}/report?workspace_id={workspace}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "answered"
    assert result["observations"][0]["evidence_id"] == evidence_id
    assert result["observations"][0]["quote"] == quote
    assert (
        result["observations"][0]["qualification"] == "source_statement_not_independently_verified"
    )
    assert result["coverage_complete"] is False and result["inference_status"] == "unavailable"
    with database.tenant(actor, workspace) as session:
        assert session.execute(
            sa.select(followup_reports.c.citation_hashes).where(followup_reports.c.job_id == job_id)
        ).scalar_one()
        assert (
            session.execute(sa.select(jobs.c.state).where(jobs.c.id == job_id)).scalar_one()
            == "completed"
        )
    assert execute_followup(database, payload, LocalStructuredModel(model_instance=stub)) == {
        "status": "checkpointed"
    }
    assert stub.calls == 1


def test_followup_idempotency_wrong_result_and_tenant_hidden(database, monkeypatch):
    _actor, workspace, source_job_id, entity_id, _, client = setup(database, monkeypatch)
    first = submit(client, source_job_id, workspace, entity_id, key="repeat")
    assert first.status_code == 202
    repeated = submit(client, source_job_id, workspace, entity_id, key="repeat")
    assert repeated.status_code == 202 and repeated.json()["job_id"] == first.json()["job_id"]
    assert (
        submit(
            client,
            source_job_id,
            workspace,
            entity_id,
            key="repeat",
            question="Different question?",
        ).status_code
        == 409
    )
    assert submit(client, source_job_id, workspace, str(uuid4()), key="other").status_code == 404
    outsider = str(uuid4())
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(outsider)
    foreign = TestClient(app)
    assert (
        foreign.get(
            f"/v1/jobs/{first.json()['job_id']}/report?workspace_id={workspace}"
        ).status_code
        == 404
    )


def test_expired_qualification_evidence_redacts_completed_report(database, monkeypatch):
    actor, workspace, source_job_id, entity_id, evidence_id, client = setup(database, monkeypatch)
    created = submit(client, source_job_id, workspace, entity_id)
    job_id = created.json()["job_id"]
    with database.tenant(actor, workspace) as session:
        quote = session.execute(
            sa.select(evidence.c.excerpt).where(evidence.c.id == evidence_id)
        ).scalar_one()
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job_id}
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    stub = Stub([{"evidence_id": evidence_id, "quote": quote}])
    assert (
        execute_followup(database, payload, LocalStructuredModel(model_instance=stub))["status"]
        == "checkpointed"
    )
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == evidence_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    result = client.get(f"/v1/jobs/{job_id}/report?workspace_id={workspace}")
    assert result.status_code == 200
    assert result.json()["status"] == "unknown" and result.json()["observations"] == []


def test_user_requested_expansion_uses_new_bounded_registered_discovery_job(database, monkeypatch):
    actor, workspace, source_job_id, _, _, client = setup(database, monkeypatch)
    path = f"/v1/jobs/{source_job_id}/expand?workspace_id={workspace}"
    body = {"prompt": "Find more synthetic companies in India with a public source"}
    response = client.post(path, json=body, headers={"Idempotency-Key": "expand-one"})
    assert response.status_code == 202, response.text
    expanded_id = response.json()["job_id"]
    repeated = client.post(path, json=body, headers={"Idempotency-Key": "expand-one"})
    assert repeated.status_code == 202 and repeated.json()["job_id"] == expanded_id
    different = client.post(
        path, json={"prompt": "Find another target"}, headers={"Idempotency-Key": "expand-one"}
    )
    assert different.status_code == 409
    with database.tenant(actor, workspace) as session:
        expanded = JobRepository.get(session, expanded_id)
        source = JobRepository.get(session, source_job_id)
        assert expanded["purpose"] == "research" and expanded["plan_id"] != source["plan_id"]
        assert source["state"] == "completed"
        event = session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.job_id == expanded_id, job_events.c.event_key == "source_expansion"
            )
        ).scalar_one()
        assert event["source_job_id"] == source_job_id and "prompt" not in event
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": expanded_id}
    isolate_capacity(monkeypatch, expanded_id)
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    assert scheduled["status"] == "scheduled"
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, expanded_id)["state"] == "queued"
    payload["attempt_id"] = scheduled["attempt_id"]
    outcome = execute_discovery(database, payload, Provider())
    assert outcome["status"] in {"checkpointed", "completed"}
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, source_job_id)["state"] == "completed"


def test_refinement_creates_new_immutable_plan_without_increasing_budget(database, monkeypatch):
    actor, workspace, source_job_id, _, _, client = setup(database, monkeypatch)
    path = f"/v1/jobs/{source_job_id}/refine?workspace_id={workspace}"
    with database.tenant(actor, workspace) as session:
        source = JobRepository.get(session, source_job_id)
        original = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, source["plan_id"])["interpretation"]
        )
    response = client.post(
        path, json={"prompt": "Exclude consultancies"}, headers={"Idempotency-Key": "refine-one"}
    )
    assert response.status_code == 202, response.text
    refined_id = response.json()["job_id"]
    assert (
        client.post(
            path,
            json={"prompt": "Exclude consultancies"},
            headers={"Idempotency-Key": "refine-one"},
        ).json()["job_id"]
        == refined_id
    )
    assert (
        client.post(
            path,
            json={"prompt": "Exclude consultancies"},
            headers={"Idempotency-Key": "refine-two"},
        ).status_code
        == 409
    )
    assert client.post(path, json={"prompt": "Find more regardless of budget"}).status_code == 422
    with database.tenant(actor, workspace) as session:
        previous = JobRepository.get(session, source_job_id)
        refined = JobRepository.get(session, refined_id)
        old_plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, previous["plan_id"])["interpretation"]
        )
        new_plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, refined["plan_id"])["interpretation"]
        )
        assert old_plan == original
        assert new_plan.revision == original.revision + 1
        assert (
            new_plan.exclusions[-1].field == "company_type"
            and new_plan.exclusions[-1].value == "consultancy"
        )
        assert len(new_plan.exclusions) == len(old_plan.exclusions) + 1
        assert new_plan.limits == old_plan.limits
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": refined_id}
    isolate_capacity(monkeypatch, refined_id)
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    assert scheduled["status"] == "scheduled"
    payload["attempt_id"] = scheduled["attempt_id"]
    assert execute_discovery(database, payload, Provider())["status"] in {
        "checkpointed",
        "completed",
    }
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, source_job_id)["state"] == "completed"


def test_explicit_must_have_relaxation_preserves_old_plan(database, monkeypatch):
    actor, workspace, source_job_id, _, _, client = setup(database, monkeypatch)
    path = f"/v1/jobs/{source_job_id}/refine?workspace_id={workspace}"
    response = client.post(path, json={"prompt": "Relax must-have location India"})
    assert response.status_code == 202, response.text
    with database.tenant(actor, workspace) as session:
        source = JobRepository.get(session, source_job_id)
        new = JobRepository.get(session, response.json()["job_id"])
        old_plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, source["plan_id"])["interpretation"]
        )
        new_plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, new["plan_id"])["interpretation"]
        )
        assert any(
            item.field == "location" and item.value == "India" for item in old_plan.must_have
        )
        assert not any(
            item.field == "location" and item.value == "India" for item in new_plan.must_have
        )
        assert new_plan.exclusions == old_plan.exclusions
        assert new_plan.limits == old_plan.limits


def test_refinement_reuses_and_reevaluates_evidence_without_changing_saved_list(
    database, monkeypatch
):
    actor, workspace, source_job_id, entity_id, _, client = setup(database, monkeypatch)
    with database.tenant(actor, workspace) as session:
        source = JobRepository.get(session, source_job_id)
        saved = create_list(session, "Original meaning", source["plan_id"], (entity_id,))
        frozen = snapshot(session, saved["id"], 1)
        original_rows = result_rows(session, source_job_id)
    response = client.post(
        f"/v1/jobs/{source_job_id}/refine?workspace_id={workspace}",
        json={"prompt": "Relax must-have employee_count 10"},
    )
    assert response.status_code == 202, response.text
    new_id = response.json()["job_id"]
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": new_id}
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    payload["attempt_id"] = scheduled["attempt_id"]
    provider = Provider()
    assert (
        execute_discovery(
            database, payload, provider, collection_proxy_url="http://127.0.0.1:8787"
        )["status"]
        == "checkpointed"
    )
    assert provider.calls == 0
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, new_id)["state"] == "completed"
        updated = {row["title"]: row for row in result_rows(session, new_id)}
        assert updated["Unknown size"]["fit"]["status"] == "confirmed"
        assert {row["id"] for row in updated.values()} == {row["id"] for row in original_rows}
        assert result_rows(session, source_job_id) == original_rows
        assert snapshot(session, saved["id"], 1) == frozen
        assert current_usage(session, new_id)[1]["search_calls"] == 0


def test_model_refinement_clarification_keeps_original_limits_and_scoped_evidence(
    database, monkeypatch
):
    actor, workspace, source_job_id, entity_id, _, client = setup(database, monkeypatch)
    settings = Settings(enable_ai_planning=True)
    client.app.state.settings = settings
    response = client.post(
        f"/v1/jobs/{source_job_id}/refine?workspace_id={workspace}",
        json={"prompt": "Please exclude Product companies"},
        headers={"Idempotency-Key": "model-delta"},
    )
    assert response.status_code == 202, response.text

    class Delta:
        def __init__(self, data):
            self.data = data

        async def ainvoke(self, messages, config):
            assert "Current criteria (data)" in messages[1].content
            return AIMessage(
                content=json.dumps(self.data),
                usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )

    def run(job_id, answer):
        payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job_id}
        payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
        return execute_planning(
            database, payload, settings, LocalStructuredModel(model_instance=Delta(answer))
        )

    first_id = response.json()["job_id"]
    assert (
        run(first_id, {"clarification": "Which company type should be excluded?"})[
            "planning_status"
        ]
        == "clarification_required"
    )
    second = client.post(
        f"/v1/jobs/{first_id}/clarifications?workspace_id={workspace}",
        json={"answer": "Exclude Product companies"},
    )
    assert second.status_code == 202, second.text
    second_id = second.json()["job_id"]
    assert (
        run(
            second_id,
            {"changes": [["exclude", "company_type", "eq", "Product", "exclude Product"]]},
        )["planning_status"]
        == "ready"
    )
    with database.tenant(actor, workspace) as session:
        old = JobRepository.get(session, source_job_id)
        new = JobRepository.get(session, second_id)
        original = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, old["plan_id"])["interpretation"]
        )
        revised = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, new["plan_id"])["interpretation"]
        )
        assert revised.limits == original.limits
        assert revised.must_have == original.must_have and revised.sources == original.sources
        assert JobRepository.get(session, first_id)["state"] == "paused"
    # Bootstrap already queued discovery; reuse its durable attempt directly.
    from skriller.db.schema import attempts

    with database.tenant(actor, workspace) as session:
        attempt_id = session.execute(
            sa.select(attempts.c.id).where(
                attempts.c.job_id == second_id, attempts.c.stage == "discovering"
            )
        ).scalar_one()
    provider = Provider()
    assert (
        execute_discovery(
            database,
            {
                "actor_id": actor,
                "workspace_id": workspace,
                "job_id": second_id,
                "attempt_id": attempt_id,
            },
            provider,
        )["status"]
        == "checkpointed"
    )
    assert provider.calls == 0
    with database.tenant(actor, workspace) as session:
        selected = next(row for row in result_rows(session, second_id) if row["id"] == entity_id)
        assert selected["fit"]["status"] == "excluded"
