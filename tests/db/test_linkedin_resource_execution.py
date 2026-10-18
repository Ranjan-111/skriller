"""Real owner/generation fences and durable private evidence, synthetic capture only."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from test_linkedin_execution import Runner as SearchRunner
from test_linkedin_execution import prepared
from test_research_workflow import Provider, isolate_capacity

from skriller.connections.lifecycle import reconnect
from skriller.connections.store import SecretPayload
from skriller.connectors.linkedin_executor import LinkedInUnavailable
from skriller.connectors.linkedin_read import LinkedInRead
from skriller.connectors.switches import set_disabled
from skriller.db.schema import attempts, entities, evidence
from skriller.erasure import erase
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.page_extraction import execute_page_extraction
from skriller.research.service import execute_discovery
from skriller.security.runner import RunResult
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


class Runner(SearchRunner):
    def run(self, operation, target, **kwargs):
        if operation == "linkedin_search":
            return super().run(operation, target, **kwargs)
        assert operation == "linkedin_resource_read" and not kwargs["cancel_check"]()
        assert kwargs["credential_material"].injection() == {
            "LINKEDIN_SESSION_COOKIE": "synthetic-session"
        }
        request = LinkedInRead.model_validate_json(target)
        self.calls.append(request)
        if self.after:
            self.after()
        return RunResult(
            "completed",
            0,
            json.dumps(
                {
                    "url": request.target_url(),
                    "sections": {request.section(): "Synthetic Founder\nHead of Operations"},
                }
            ),
            "",
            1,
        )


@pytest.mark.parametrize("change", [None, "read_disabled", "wrong_generation", "rotate_during"])
def test_owner_read_uses_exact_generation_and_no_discovery_scope(database, monkeypatch, change):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch, scopes=("read",))
    reader.runner = runner = Runner()
    with database.tenant(actor, accepted["workspace_id"]) as session:
        material = store.load_for_runner(session, context, "linkedin_resource_read")
        if change == "read_disabled":
            set_disabled(session, "linkedin", "read", True)

    def rotate():
        with database.tenant(actor, accepted["workspace_id"]) as session:
            reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials={"session_cookie": "replacement"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    if change == "wrong_generation":
        rotate()
    if change == "rotate_during":
        runner.after = rotate
    call = lambda: reader.read(
        LinkedInRead(operation="read_profile", resource_id="synthetic"),
        database=database,
        store=store,
        context=context,
        expected_credential_ref=material.credential_ref,
    )
    if change is None:
        result = call()
        assert result.contact_details == "unavailable" and result.subject_identity == "unknown"
    else:
        with pytest.raises(LinkedInUnavailable):
            call()
        assert len(runner.calls) == (1 if change == "rotate_during" else 0)


@pytest.mark.parametrize("lifecycle", ["expiry", "erasure", "extraction"])
def test_durable_read_saved_extraction_retention_and_replay(
    database, monkeypatch, tmp_path, lifecycle
):
    settings = Settings(
        public_linkedin_image="sha256:" + "a" * 64,
        public_collection_proxy_url="http://127.0.0.1:18080",
        enable_page_extraction=lifecycle == "extraction",
    )
    actor, client, accepted, store, _, reader = prepared(database, monkeypatch, settings=settings)
    reader.runner = runner = Runner()
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    isolate_capacity(monkeypatch, task["job_id"])
    discovery = CheckpointWorker(database, {}).schedule(task)
    outcome = execute_discovery(
        database,
        {**task, "attempt_id": discovery["attempt_id"]},
        Provider(),
        linkedin_reader=reader,
        connection_store=store,
        collection_proxy_url="http://127.0.0.1:18080",
    )
    assert outcome["status"] == "checkpointed", outcome
    with database.tenant(actor, task["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "collecting"
                )
            )
            .mappings()
            .one()
        )
        entity_id = attempt["logical_key"].removeprefix("collecting:")
        attributes = session.execute(
            sa.select(entities.c.attributes).where(entities.c.id == entity_id)
        ).scalar_one()
        assert attributes["_read_connection_ref"] and attributes["_read_credential_ref"]
    original = collection.collection_handler
    monkeypatch.setattr(
        collection,
        "collection_handler",
        lambda *args, **kwargs: replace(
            original(*args, **kwargs),
            capacity_source="li-read-" + task["job_id"],
            capacity_host=task["job_id"] + ".example.invalid",
        ),
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    payload = {**task, "attempt_id": str(attempt["id"])}
    result = collection.execute_collection(
        database,
        payload,
        "http://127.0.0.1:18080",
        storage=storage,
        linkedin_reader=reader,
        connection_store=store,
        enable_extraction=lifecycle == "extraction",
    )
    assert result["status"] == "checkpointed", result
    if lifecycle == "extraction":

        class Model:
            calls = 0

            async def ainvoke(self, messages, config):
                self.calls += 1
                assert "untrusted_source" in messages[1].content and config["callbacks"] == []
                return AIMessage(
                    content=json.dumps(
                        {
                            "claims": [
                                {
                                    "field": "job_title",
                                    "value": "Head of Operations",
                                    "quote": "Head of Operations",
                                },
                                {
                                    "field": "public_work_email",
                                    "value": "invented@example.com",
                                    "quote": "Synthetic Founder",
                                },
                            ]
                        }
                    ),
                    usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                )

        model = Model()
        with database.tenant(actor, task["workspace_id"]) as session:
            extracting = session.execute(
                sa.select(attempts.c.id).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "extracting"
                )
            ).scalar_one()
        extracted = execute_page_extraction(
            database,
            {**task, "attempt_id": str(extracting)},
            storage=storage,
            model=LocalStructuredModel(model_instance=model),
        )
        assert extracted["status"] == "checkpointed" and model.calls == 1, extracted
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    assert row["linkedin_read"]["resource"]["text"] == "Synthetic Founder\nHead of Operations"
    assert row["linkedin_read"]["resource"]["contact_details"] == "unavailable"
    assert row["platform_reference"] is None and row["evidence_kind"] == "search_reference"
    assert not any(key.startswith("_read") for key in row)
    if lifecycle == "extraction":
        observed = row["extraction"]["observations"]
        assert len(observed) == 1 and observed[0]["field"] == "job_title", row["extraction"]
        assert observed[0]["status"] == "unverified"
        assert not row["extraction"]["coverage_complete"]
    count = len(runner.calls)
    replay = collection.execute_collection(
        database,
        payload,
        "http://127.0.0.1:18080",
        storage=storage,
        linkedin_reader=reader,
        connection_store=store,
    )
    assert replay["status"] == "checkpointed" and len(runner.calls) == count
    with database.tenant(actor, task["workspace_id"]) as session:
        if lifecycle == "erasure":
            erase(session, storage, entity_id, request_key="erase-li-resource")
        else:
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == row["linkedin_read"]["evidence_id"])
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
    rows = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"]
    assert rows == [] if lifecycle == "erasure" else rows[0]["linkedin_read"] is None


@pytest.mark.parametrize("role", ["member", "owner"])
def test_resource_read_cannot_open_another_initiators_session(database, monkeypatch, role):
    from uuid import UUID, uuid4

    from skriller.db import JobRepository, WorkspaceRepository
    from skriller.jobs.outbox import submit

    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)
    reader.runner = runner = Runner()
    other = "li-read-other-" + uuid4().hex
    with database.tenant(actor, accepted["workspace_id"]) as session:
        WorkspaceRepository.add_member(session, other, role)
    with database.tenant(other, accepted["workspace_id"]) as session:
        previous = JobRepository.get(session, accepted["job_id"])
        job = submit(session, previous["conversation_id"], previous["plan_id"], uuid4().hex)
    context = context.model_copy(update={"actor_id": other, "job_id": UUID(job["id"])})
    with pytest.raises(LinkedInUnavailable):
        reader.read(
            LinkedInRead(operation="read_profile", resource_id="synthetic"),
            database=database,
            store=store,
            context=context,
        )
    assert runner.calls == []


@pytest.mark.parametrize("code", ["auth_expired", "access_denied", "rate_limited", "not_found"])
def test_source_barriers_remain_typed_without_raw_error_details(database, monkeypatch, code):
    _, _, _, store, context, reader = prepared(database, monkeypatch)

    class Blocked:
        def run(self, *args, **kwargs):
            return RunResult(
                "completed",
                0,
                json.dumps(
                    {
                        "_skriller_error": code,
                        "private_error": "NEVER DISPLAY RAW PROVIDER DIAGNOSTICS",
                    }
                ),
                "",
                1,
            )

    reader.runner = Blocked()
    with pytest.raises(LinkedInUnavailable) as caught:
        reader.read(
            LinkedInRead(operation="read_profile", resource_id="synthetic"),
            database=database,
            store=store,
            context=context,
        )
    assert caught.value.code == code and "PRIVATE" not in str(caught.value)
