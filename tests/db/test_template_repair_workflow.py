"""Real tenant/outbox/checkpoint/model ledger and owner-reviewed repair activation."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.db import JobRepository, WorkspaceRepository
from skriller.db.schema import evidence, page_template_audit
from skriller.extraction.models import LocalStructuredModel, ModelBounds
from skriller.jobs.budget import current_usage
from skriller.jobs.control import cancel
from skriller.jobs.worker import CheckpointWorker
from skriller.research.adaptive_templates import ReviewedTemplate
from skriller.research.template_registry import (
    publish_template,
    rollback_template,
    selected_templates,
)
from skriller.research.template_repair import (
    RepairInput,
    approve_repair,
    create_repair,
    execute_template_repair,
    repair_view,
)
from skriller.settings import Settings
from skriller.storage import BlobIntegrityError, BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
URL = "https://example.org/company"
OLD = '<article><h2>Company</h2><span class="old">Acme</span></article>'
NEW = '<article><h2>Company</h2><strong class="renamed">Acme</strong></article>'


class Model:
    def __init__(self, css=".renamed", hook=None):
        self.css, self.hook, self.calls = css, hook, 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        if self.hook:
            self.hook()
        return AIMessage(
            content=json.dumps({"css": self.css}),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


def setup(database, tmp_path, *, regression=OLD):
    actor = f"repair-owner-{uuid4()}"
    workspace = database.create_workspace(actor, "Template repair")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path / "objects"))
    template = ReviewedTemplate.model_validate(
        {
            "workspace_id": workspace,
            "source_url": URL,
            "template_id": str(uuid4()),
            "template_version": 1,
            "fields": [
                {
                    "field": "company_name",
                    "identifier": "name",
                    "css": ".old",
                    "expected_text": "Acme",
                    "container_xpath": "ancestor::article[1]",
                    "anchors": [{"css": "h2", "expected_text": "Company"}],
                }
            ],
        }
    )
    with database.tenant(actor, workspace) as session:
        publish_template(session, template, expected_version=None)
        ids = [
            storage.store(
                session,
                html.encode(),
                source_url=URL,
                source_platform="web",
                collected_at=datetime.now(UTC),
            )["id"]
            for html in [NEW, regression]
        ]
    inputs = RepairInput(
        expected_version=1,
        field_identifier="name",
        current_evidence_id=ids[0],
        regression_evidence_ids=[ids[1]],
    )
    return actor, workspace, storage, template, inputs


def requested(database, actor, workspace, template, inputs):
    with database.tenant(actor, workspace) as session:
        job = create_repair(session, template.template_id, inputs, "one-proposal")
        assert (
            create_repair(session, template.template_id, inputs, "one-proposal")["id"] == job["id"]
        )
    task = {"actor_id": actor, "workspace_id": workspace, "job_id": job["id"]}
    scheduled = CheckpointWorker(database, {}).schedule(task)
    task["attempt_id"] = scheduled["attempt_id"]
    return job, task


def test_worker_proposes_once_without_activation_then_explicit_review_publishes_and_audits(
    database, tmp_path
):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    job, task = requested(database, actor, workspace, template, inputs)
    stub = Model()
    model = LocalStructuredModel(model_instance=stub)
    assert (
        execute_template_repair(database, task, storage=storage, model=model)["status"]
        == "checkpointed"
    )
    assert (
        execute_template_repair(database, task, storage=storage, model=model)["status"]
        == "checkpointed"
    )
    assert stub.calls == 1
    with database.tenant(actor, workspace) as session:
        view = repair_view(session, job["id"])
        assert view.status == "ready_for_review" and view.proposal.template_version == 2
        assert view.proposal.fields[0].css == ".old, .renamed"
        assert selected_templates(session)[0].template_version == 1
        assert current_usage(session, job["id"])[1]["llm_calls"] == 1
        assert JobRepository.get(session, job["id"])["state"] == "completed"
        assert approve_repair(session, storage, job["id"], 1).status == "approved"
        assert approve_repair(session, storage, job["id"], 1).status == "approved"
        assert selected_templates(session)[0].template_version == 2
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(page_template_audit)
            ).scalar_one()
            == 2
        )


@pytest.mark.skipif(
    os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") != "1",
    reason="Explicit opt-in required for local Ollama owner-review acceptance",
)
def test_actual_local_model_proposal_owner_review_and_rollback(database, tmp_path):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    job, task = requested(database, actor, workspace, template, inputs)
    model = LocalStructuredModel(ModelBounds(timeout_seconds=10, output_tokens=128))
    outcome = execute_template_repair(database, task, storage=storage, model=model)
    assert outcome["status"] == "checkpointed"
    with database.tenant(actor, workspace) as session:
        assert repair_view(session, job["id"]).status == "ready_for_review"
        assert selected_templates(session)[0].template_version == 1
        assert approve_repair(session, storage, job["id"], 1).status == "approved"
        assert selected_templates(session)[0].template_version == 2
        rollback_template(session, template.template_id, target_version=1, expected_version=2)
        assert selected_templates(session)[0].template_version == 1
        usage = current_usage(session, job["id"])[1]
        assert usage["llm_calls"] == 1
    Path("docs/completions/REPAIR-REVIEW-LOCAL.json").write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(UTC).isoformat(),
                "scope": "Synthetic saved public-web evidence; actual local Ollama and tenant database",
                "model": model.model_name,
                "worker_status": outcome["status"],
                "proposal_reviewed": True,
                "active_before_review": 1,
                "active_after_review": 2,
                "active_after_rollback": 1,
                "metered_model_calls": usage["llm_calls"],
                "metered_tokens": usage["tokens"],
                "source_calls": 0,
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("case", ["unsafe", "wrong_neighbor", "expired", "erased_during_model"])
def test_invalid_repair_keeps_active_mapping_and_does_not_expose_a_proposal(
    database, tmp_path, case
):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    if case == "wrong_neighbor":
        with database.tenant(actor, workspace) as session:
            bad = storage.store(
                session,
                OLD.replace("Company", "Investor").encode(),
                source_url=URL,
                source_platform="web",
                collected_at=datetime.now(UTC),
            )
        inputs.regression_evidence_ids.append(UUID(bad["id"]))
    job, task = requested(database, actor, workspace, template, inputs)
    if case == "expired":
        with database.tenant(actor, workspace) as session:
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == str(inputs.current_evidence_id))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )

    def erase():
        with database.tenant(actor, workspace) as session:
            session.execute(
                sa.delete(evidence).where(evidence.c.id == str(inputs.current_evidence_id))
            )

    stub = Model(
        "javascript:alert(1)" if case == "unsafe" else ".renamed",
        hook=erase if case == "erased_during_model" else None,
    )
    assert (
        execute_template_repair(
            database, task, storage=storage, model=LocalStructuredModel(model_instance=stub)
        )["status"]
        == "checkpointed"
    )
    with database.tenant(actor, workspace) as session:
        view = repair_view(session, job["id"])
        assert view.status == "unknown" and view.proposal is None
        assert selected_templates(session)[0].template_version == 1
        with pytest.raises(ValueError):
            approve_repair(session, storage, job["id"], 1)
    assert stub.calls == (0 if case == "expired" else 1)


def test_cancellation_during_model_discards_proposal_and_blocks_duplicate_call(database, tmp_path):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    job, task = requested(database, actor, workspace, template, inputs)

    def stop():
        with database.tenant(actor, workspace) as session:
            cancel(session, job["id"])

    stub = Model(hook=stop)
    model = LocalStructuredModel(model_instance=stub)
    execute_template_repair(database, task, storage=storage, model=model)
    execute_template_repair(database, task, storage=storage, model=model)
    assert stub.calls == 1
    with database.tenant(actor, workspace) as session:
        assert selected_templates(session)[0].template_version == 1
        assert repair_view(session, job["id"]).proposal is None
        assert repair_view(session, job["id"]).status == "unknown"
        assert JobRepository.get(session, job["id"])["state"] == "cancelled"


@pytest.mark.parametrize("case", ["changed_template", "tampered_source"])
def test_approval_rechecks_source_integrity_and_active_version(database, tmp_path, case):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    job, task = requested(database, actor, workspace, template, inputs)
    execute_template_repair(
        database, task, storage=storage, model=LocalStructuredModel(model_instance=Model())
    )
    if case == "tampered_source":
        with database.tenant(actor, workspace) as session:
            row = (
                session.execute(
                    sa.select(evidence).where(evidence.c.id == str(inputs.current_evidence_id))
                )
                .mappings()
                .one()
            )
        (storage.backend.directory / row["object_key"]).write_bytes(b"altered")
    with database.tenant(actor, workspace) as session:
        if case == "changed_template":
            publish_template(
                session, template.model_copy(update={"template_version": 2}), expected_version=1
            )
        with pytest.raises((ValueError, BlobIntegrityError)):
            approve_repair(session, storage, job["id"], 1)
        assert repair_view(session, job["id"]).status == "ready_for_review"


def test_request_rejects_foreign_evidence_and_changed_idempotency_body(database, tmp_path):
    actor, workspace, _, template, inputs = setup(database, tmp_path)
    other_actor, other_workspace, _, _, other_inputs = setup(database, tmp_path / "other")
    with database.tenant(actor, workspace) as session:
        with pytest.raises(BlobUnavailable):
            create_repair(
                session,
                template.template_id,
                inputs.model_copy(update={"current_evidence_id": other_inputs.current_evidence_id}),
                "foreign",
            )
        create_repair(session, template.template_id, inputs, "original")
        with pytest.raises(ValueError):
            create_repair(
                session,
                template.template_id,
                inputs.model_copy(update={"field_identifier": "other"}),
                "original",
            )
    with database.tenant(other_actor, other_workspace) as session, pytest.raises(LookupError):
        create_repair(session, template.template_id, inputs, "other")


def test_authenticated_api_requires_owner_and_explicit_review_and_keeps_source_private(
    database, tmp_path, monkeypatch
):
    actor, workspace, storage, template, inputs = setup(database, tmp_path)
    app = create_app(
        Settings(
            enable_page_extraction=True,
            object_directory=str(tmp_path / "objects"),
            public_collection_proxy_url="http://127.0.0.1:1",
        )
    )
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr(
        "skriller.research.template_repair_router.safe_dispatch", lambda *args: None
    )
    client = TestClient(app)
    base = f"/v1/workspaces/{workspace}/page-templates"
    response = client.post(
        base + f"/{template.template_id}/repairs",
        json=inputs.model_dump(mode="json"),
        headers={"Idempotency-Key": "api"},
    )
    assert response.status_code == 202, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    job_id = response.json()["job_id"]
    task = {"actor_id": actor, "workspace_id": workspace, "job_id": job_id}
    task["attempt_id"] = CheckpointWorker(database, {}).schedule(task)["attempt_id"]
    execute_template_repair(
        database, task, storage=storage, model=LocalStructuredModel(model_instance=Model())
    )
    url = base + f"/repairs/{job_id}"
    view = client.get(url)
    assert (
        view.json()["status"] == "ready_for_review"
        and "<article>" not in view.text
        and "object_key" not in view.text
    )
    assert client.get(f"/v1/jobs/{job_id}/results").json()["results"] == []
    assert (
        client.post(
            url + "/approve", json={"expected_version": 1, "confirm_review": False}
        ).status_code
        == 409
    )
    assert (
        client.post(url + "/approve", json={"expected_version": 1, "confirm_review": True}).json()[
            "status"
        ]
        == "approved"
    )
    member = f"repair-member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.get(url).status_code == 403
    assert (
        client.post(
            base + f"/{template.template_id}/repairs",
            json=inputs.model_dump(mode="json"),
            headers={"Idempotency-Key": "denied"},
        ).status_code
        == 403
    )


def test_runtime_dispatches_repair_purpose_to_saved_evidence_worker(
    database, tmp_path, monkeypatch
):
    import skriller.research.template_repair as repair_module
    from skriller.research import runtime

    actor, workspace, _, template, inputs = setup(database, tmp_path)
    job, task = requested(database, actor, workspace, template, inputs)
    stub = Model()
    original = repair_module.execute_template_repair

    def execute(db, payload, *, storage):
        return original(
            db, payload, storage=storage, model=LocalStructuredModel(model_instance=stub)
        )

    monkeypatch.setattr(repair_module, "execute_template_repair", execute)
    monkeypatch.setattr(runtime, "database", database)
    monkeypatch.setattr(
        runtime,
        "settings",
        Settings(
            enable_page_extraction=True,
            public_collection_proxy_url="http://127.0.0.1:1",
            object_directory=str(tmp_path / "objects"),
        ),
    )
    monkeypatch.setattr(
        runtime,
        "execute_page_extraction",
        lambda *a, **k: pytest.fail("repair must not run ordinary page extraction"),
    )
    monkeypatch.setattr(
        runtime, "execute_discovery", lambda *a, **k: pytest.fail("repair must not fetch/search")
    )
    assert runtime.execute.run(task)["status"] == "checkpointed"
    assert stub.calls == 1
    with database.tenant(actor, workspace) as session:
        assert repair_view(session, job["id"]).status == "ready_for_review"
