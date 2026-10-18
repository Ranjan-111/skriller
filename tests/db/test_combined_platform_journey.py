"""Dual-platform journey with real persistence/adapters and synthetic source I/O."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_linkedin_resource_execution import Runner as LinkedInRunner
from test_reddit_thread_execution import Runner as RedditRunner
from test_research_reports import Stub
from test_research_workflow import Provider, isolate_capacity, prepare

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor
from skriller.connectors.reddit_executor import ConcreteRedditExecutor
from skriller.contracts import Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.schema import attempts
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.collection import execute_collection
from skriller.research.followups import execute_followup
from skriller.research.page_extraction import execute_page_extraction
from skriller.research.planner import Interpretation, PlanScope, grounded_plan
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


class FounderRunner(LinkedInRunner):
    def run(self, operation, target, **kwargs):
        result = super().run(operation, target, **kwargs)
        if operation == "linkedin_resource_read":
            payload = json.loads(result.stdout)
            payload["sections"]["main_profile"] = (
                "Synthetic Founder. Engineer; effective 2021-01-01. Founder; effective 2025-01-01."
            )
            result = replace(result, stdout=json.dumps(payload))
        return result


class FixtureExtraction:
    def __init__(self, source):
        self.source = source
        self.calls = 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        assert config["callbacks"] == []
        if self.source == "linkedin":
            claims = []
            for role, effective in (("Engineer", "2021-01-01"), ("Founder", "2025-01-01")):
                quote = f"{role}; effective {effective}."
                claims.extend(
                    [
                        {"field": "job_title", "value": role, "quote": quote},
                        {"field": "role_effective_date", "value": effective, "quote": quote},
                    ]
                )
            value = {"claims": claims}
        else:
            value = {"signals": [{"resource_id": "t1_com123", "quote": "A queue problem"}]}
        return AIMessage(
            content=json.dumps(value),
            usage_metadata={"input_tokens": 30, "output_tokens": 40, "total_tokens": 70},
        )


@pytest.mark.parametrize(
    "linkedin_outage,reviewed_founder", [(False, False), (True, False), (False, True)]
)
def test_combined_sources_preserve_identity_evidence_outage_and_revision(
    database, monkeypatch, tmp_path, linkedin_outage, reviewed_founder
):
    actor = "combined-" + uuid4().hex
    settings = Settings(
        public_linkedin_image="sha256:" + "a" * 64,
        public_reddit_image="sha256:" + "b" * 64,
        public_collection_proxy_url="http://127.0.0.1:18080",
    )
    if reviewed_founder:
        workspace = database.create_workspace(actor, "Synthetic founder journey")["id"]
        with database.tenant(actor, workspace) as session:
            conversation = ConversationRepository.create(
                session, "Find founders and demand context"
            )
            prompt = "Find founders on LinkedIn and Reddit."
            ConversationRepository.add_message(
                session,
                conversation["id"],
                "user",
                prompt,
            )
            plan = grounded_plan(
                prompt,
                Interpretation(
                    entity_type="person",
                    entity_quote="founders",
                    rules=[("must_have", "role", "contains", "founders", "founders")],
                    sources=[("linkedin", "LinkedIn"), ("reddit", "Reddit")],
                ),
                PlanScope(
                    workspace_id=workspace,
                    conversation_id=conversation["id"],
                    revision=1,
                    limits=Limits(),
                    allowed_sources=["linkedin", "reddit"],
                ),
            )
            revision = ConversationRepository.revise_plan(
                session, conversation["id"], plan.model_dump(mode="json")
            )
            job = submit(session, conversation["id"], revision["id"], "founder-fixture")
        accepted = {"workspace_id": workspace, "job_id": job["id"]}
        app = create_app(settings)
        app.state.database = database
        app.dependency_overrides[require_identity] = lambda: Identity(actor)
        monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
        client = TestClient(app)
    else:
        _, client, accepted = prepare(
            database, monkeypatch, actor, sources=["linkedin", "reddit"], settings=settings
        )
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    with database.tenant(actor, accepted["workspace_id"]) as session:
        for source, auth, credential in (
            ("linkedin", "session", {"session_cookie": "synthetic-session"}),
            ("reddit", "oauth", {"access_token": "fixture-access-token"}),
        ):
            store.create(
                session,
                source,
                auth,
                SecretPayload(credentials=credential),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=("read", "discover"),
            )
        original_job = JobRepository.get(session, accepted["job_id"])
        original_plan = ConversationRepository.get_plan(session, original_job["plan_id"])
    linkedin = ConcreteLinkedInExecutor(settings.public_linkedin_image)
    linkedin.runner = FounderRunner() if reviewed_founder else LinkedInRunner()
    linkedin.runner.failed = linkedin_outage
    reddit = ConcreteRedditExecutor(settings.public_reddit_image)
    reddit.runner = RedditRunner()
    fallback = Provider()
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    isolate_capacity(monkeypatch, task["job_id"])
    discovery = CheckpointWorker(database, {}).schedule(task)
    discovery_task = {**task, "attempt_id": discovery["attempt_id"]}
    kwargs = {
        "linkedin_reader": linkedin,
        "reddit_reader": reddit,
        "connection_store": store,
        "collection_proxy_url": settings.public_collection_proxy_url,
    }
    result = execute_discovery(database, discovery_task, fallback, **kwargs)
    assert result["status"] == "checkpointed", result
    counts = len(linkedin.runner.calls), len(reddit.runner.calls)
    assert fallback.calls == 0
    replay = execute_discovery(database, discovery_task, fallback, **kwargs)
    assert replay["status"] == "checkpointed"
    assert counts == (len(linkedin.runner.calls), len(reddit.runner.calls))
    with database.tenant(actor, task["workspace_id"]) as session:
        collecting = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"],
                    attempts.c.stage == "collecting",
                )
            )
            .mappings()
            .all()
        )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    handler = collection.collection_handler

    def isolated_handler(*args, **options):
        work = handler(*args, **options)
        return replace(
            work,
            capacity_source=task["job_id"] + work.capacity_source,
            capacity_host=task["job_id"] + work.capacity_host,
        )

    monkeypatch.setattr(collection, "collection_handler", isolated_handler)
    for attempt in collecting:
        outcome = execute_collection(
            database,
            {**task, "attempt_id": attempt["id"]},
            settings.public_collection_proxy_url,
            storage=storage,
            linkedin_reader=linkedin,
            reddit_reader=reddit,
            connection_store=store,
            enable_extraction=reviewed_founder,
        )
        assert outcome["status"] == "checkpointed", outcome
    if reviewed_founder:
        with database.tenant(actor, task["workspace_id"]) as session:
            extracting = (
                session.execute(
                    sa.select(attempts).where(
                        attempts.c.job_id == task["job_id"], attempts.c.stage == "extracting"
                    )
                )
                .mappings()
                .all()
            )
            extraction_sources = {
                attempt["id"]: ResearchRepository.get_entity(
                    session, attempt["logical_key"].removeprefix("extracting:")
                )["attributes"]["source"]
                for attempt in extracting
            }
        assert set(extraction_sources.values()) == {"linkedin", "reddit"}
        for attempt in extracting:
            model = FixtureExtraction(extraction_sources[attempt["id"]])
            outcome = execute_page_extraction(
                database,
                {**task, "attempt_id": attempt["id"]},
                settings=settings,
                storage=storage,
                model=LocalStructuredModel(model_instance=model),
            )
            assert outcome["status"] == "checkpointed" and model.calls == 1, outcome
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200, response.text
    rows = response.json()["results"]
    assert {row["source"] for row in rows} == (
        {"reddit"} if linkedin_outage else {"linkedin", "reddit"}
    )
    for row in rows:
        assert row["qualification"] == "unverified"
        assert row["fit"]["status"] != "confirmed"
        if row["source"] == "linkedin":
            assert row["provider"] == "linkedin_mcp" and row["evidence_kind"] == "search_reference"
            assert row["linkedin_read"]["resource"]["subject_identity"] == "unknown"
            assert row["reddit_thread"] is None
        else:
            assert row["provider"] == "reddit_oauth" and row["evidence_kind"] == "public_post"
            assert row["reddit_thread"]["thread"]["subject_identity"] == "unknown"
            assert row["linkedin_read"] is None
        assert all(item["source"] == row["source"] for item in row["provenance"])
    assert all("example.org" not in row["url"] for row in rows)
    # Unverified sections must not become a cited qualification report about a
    # named buyer just because source text was successfully collected.
    report = client.post(
        f"/v1/jobs/{task['job_id']}/followups",
        json={"entity_id": rows[0]["id"], "question": "Why is this founder a buyer?"},
        headers={"Idempotency-Key": "unverified-report"},
    )
    assert report.status_code == 422
    assert "no current qualification evidence" in report.text
    if reviewed_founder:
        founder = next(row for row in rows if row["source"] == "linkedin")
        evidence_id = founder["linkedin_read"]["evidence_id"]
        # Copied-graph observations are literal drafts, never manually accepted. The
        # actual owner review is the only operation that accepts the chronology
        # and confirms this original profile describes a person.
        with database.tenant(actor, task["workspace_id"]) as session:
            refs = []
            observations = founder["extraction"]["observations"]
            assert len(observations) == 4 and all(
                item["status"] != "accepted" for item in observations
            )
            for role, effective in (("Engineer", "2021-01-01"), ("Founder", "2025-01-01")):
                claim = next(
                    item
                    for item in observations
                    if item["field"] == "job_title" and item["value"] == role
                )
                date_claim = next(
                    item
                    for item in observations
                    if item["field"] == "role_effective_date" and item["value"] == effective
                )
                refs.append(
                    {
                        "role_claim_id": claim["claim_id"],
                        "date_claim_id": date_claim["claim_id"],
                        "evidence_id": evidence_id,
                    }
                )
            quote = ResearchRepository.get_evidence(session, evidence_id)["excerpt"]
        review = {"entity_id": founder["id"], "previous": refs[0], "replacement": refs[1]}
        review_path = f"/v1/workspaces/{task['workspace_id']}/role-refreshes"
        preview = client.post(review_path + "/preview", json=review)
        assert preview.status_code == 200, preview.text
        assert preview.json()["requires_person_confirmation"] is True
        approval = {
            **review,
            "same_subject_confirmed": True,
            "expected_review_hash": preview.json()["review_hash"],
        }
        assert client.post(review_path, json=approval).status_code == 409
        approved = client.post(review_path, json={**approval, "person_subject_confirmed": True})
        assert approved.status_code == 200, approved.text
        fresh = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"]
        current = next(row for row in fresh if row["id"] == founder["id"])
        assert current["fit"]["status"] == "confirmed"
        assert current["linkedin_read"]["resource"]["subject_identity"] == "unknown"
        discussion = next(row for row in fresh if row["source"] == "reddit")
        assert discussion["fit"]["status"] != "confirmed"
        assert discussion["reddit_thread"]["signals"][0]["quote"] == "A queue problem"
        assert discussion["reddit_thread"]["signals"][0]["buying_intent"] == "not_inferred"
        # Close the local copied-extraction -> explicit owner review -> confirmed
        # download chain without substituting manually accepted seed facts.
        app.state.evidence_storage = storage
        export_path = f"/v1/workspaces/{task['workspace_id']}/exports"
        exported = client.post(
            export_path,
            json={
                "plan_id": original_job["plan_id"],
                "entity_ids": [founder["id"]],
                "format": "json",
            },
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["row_count"] == 1
        downloaded = client.get(f"{export_path}/{exported.json()['id']}")
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["cache-control"] == "no-store"
        records = downloaded.json()["records"]
        assert len(records) == 1 and records[0]["entity_id"] == founder["id"]
        assert records[0]["fit"] == "confirmed"
        assert evidence_id in records[0]["evidence_ids"]
        denied = client.post(
            export_path,
            json={
                "plan_id": original_job["plan_id"],
                "entity_ids": [discussion["id"]],
                "format": "json",
            },
        )
        assert denied.status_code == 422
        created = client.post(
            f"/v1/jobs/{task['job_id']}/followups",
            json={
                "entity_id": founder["id"],
                "question": "Which role is supported by the saved evidence?",
            },
            headers={"Idempotency-Key": "reviewed-founder-report"},
        )
        assert created.status_code == 202, created.text
        report_task = {**task, "job_id": created.json()["job_id"]}
        report_task["attempt_id"] = CheckpointWorker(database, {}).schedule(report_task)[
            "attempt_id"
        ]
        model = Stub([{"evidence_id": evidence_id, "quote": quote}])
        outcome = execute_followup(
            database, report_task, LocalStructuredModel(model_instance=model)
        )
        assert outcome == {"status": "checkpointed", "report_status": "answered"}, outcome
        report_view = client.get(f"/v1/jobs/{report_task['job_id']}/report").json()
        assert report_view["status"] == "answered" and model.calls == 1
        assert report_view["observations"][0]["evidence_id"] == evidence_id
        assert report_view["observations"][0]["source_platform"] == "linkedin"
        assert report_view["observations"][0]["quote"] == quote
        assert report_view["inference_status"] == "unavailable"
        assert counts[0] + 1 == len(linkedin.runner.calls)
    # Existing conversational delta parser and immutable plan lineage are used.
    refined = client.post(
        f"/v1/jobs/{task['job_id']}/refine",
        json={"prompt": "Exclude consultancies"},
        headers={"Idempotency-Key": "combined-refinement"},
    )
    assert refined.status_code == 202, refined.text
    with database.tenant(actor, task["workspace_id"]) as session:
        old = ConversationRepository.get_plan(session, original_job["plan_id"])
        new_job = JobRepository.get(session, refined.json()["job_id"])
        new = ConversationRepository.get_plan(session, new_job["plan_id"])
        assert old == original_plan
        plan = SearchPlan.model_validate(new["interpretation"])
        assert new["parent_id"] == old["id"] and new["revision"] == old["revision"] + 1
        assert plan.limits == SearchPlan.model_validate(old["interpretation"]).limits
        assert plan.exclusions[-1].value == "consultancy"
