"""Actual saved-HTTP extraction uses reviewed copied-selector mappings."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import test_fetch
from test_page_extraction_workflow import ModelFixture, prepare_page

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope
from skriller.contracts import ExecutionContext
from skriller.db import ResearchRepository
from skriller.extraction.adaptive import FieldRule, SemanticAnchor, validate_field
from skriller.extraction.models import LocalStructuredModel
from skriller.research.adaptive_templates import template_observations
from skriller.research.page_extraction import execute_page_extraction
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def registry(path, workspace, template):
    path.write_text(
        json.dumps(
            {
                "templates": [
                    {
                        "workspace_id": str(workspace),
                        "source_url": "http://example.com/company",
                        "template_id": str(template),
                        "template_version": 1,
                        "fields": [
                            {
                                "field": "company_name",
                                "identifier": "company.name",
                                "css": ".company-name",
                                "expected_text": "Aurora Ledger",
                                "container_xpath": "ancestor::main[1]",
                                "anchors": [{"css": "article h2", "expected_text": "Founder"}],
                            }
                        ],
                    }
                ]
            }
        )
    )
    return str(path)


def seed(database, context, template):
    html = (Path(__file__).parents[1] / "fixtures/research/company.html").read_text()
    scope = StorageScope(context.workspace_id, "web", "public", template, 1)
    rule = FieldRule(
        "company.name",
        ".company-name",
        "Aurora Ledger",
        "ancestor::main[1]",
        (SemanticAnchor("article h2", "Founder"),),
    )
    baseline = html.replace("<h1>", '<h1 class="company-name">')
    assert (
        validate_field(
            baseline,
            "http://example.com/company",
            database=database,
            context=context,
            storage_scope=scope,
            rule=rule,
        ).status
        == "accepted"
    )
    return html, scope


def test_saved_page_checkpoint_reuses_reviewed_relocation_without_publishing(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, _, _ = proxy
    actor, client, accepted, task, storage = prepare_page(
        database, monkeypatch, endpoint, tmp_path / "objects"
    )
    context = ExecutionContext(
        workspace_id=UUID(accepted["workspace_id"]),
        job_id=UUID(task["job_id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=2),
        attempt_budget=5,
    )
    template = uuid4()
    _, scope = seed(database, context, template)
    settings = Settings(
        reviewed_page_templates_file=registry(
            tmp_path / "templates.json", context.workspace_id, template
        )
    )
    store = PostgreSQLStorageSystem(database, actor, scope, "http://example.com/company")
    baseline = store.retrieve("company.name")
    outcome = execute_page_extraction(
        database,
        task,
        storage=storage,
        settings=settings,
        model=LocalStructuredModel(model_instance=ModelFixture()),
    )
    assert outcome["status"] == "checkpointed"
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"][0]
    assert result["qualification"] == "unverified"
    assert all(item["status"] == "unverified" for item in result["extraction"]["observations"])
    assert "_adaptive_validation" not in result
    with database.tenant(actor, accepted["workspace_id"]) as session:
        diagnostics = ResearchRepository.get_entity(session, result["id"])["attributes"][
            "_adaptive_validation"
        ]
        assert diagnostics[0]["status"] == "accepted" and diagnostics[0]["recovered"]
    assert store.retrieve("company.name") == baseline
    assert (
        PostgreSQLStorageSystem(
            database,
            actor,
            StorageScope(context.workspace_id, "web", "public", template, 2),
            "http://example.com/company",
        ).retrieve("company.name")
        is None
    )


def test_wrong_relationship_is_quarantined_and_registry_is_workspace_exact(database, tmp_path):
    actor = "adaptive-" + uuid4().hex
    workspace = UUID(database.create_workspace(actor, "Reviewed templates")["id"])
    context = ExecutionContext(
        workspace_id=workspace,
        job_id=uuid4(),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=2),
        attempt_budget=5,
    )
    template = uuid4()
    html, _ = seed(database, context, template)
    path = registry(tmp_path / "templates.json", workspace, template)
    observations, diagnostics = template_observations(
        database,
        context,
        html.replace("<h2>Founder</h2>", "<h2>Investor</h2>"),
        "http://example.com/company",
        path,
    )
    assert not observations and diagnostics[0]["reason"] == "semantic_anchor_mismatch"
    registry(Path(path), uuid4(), template)
    assert template_observations(database, context, html, "http://example.com/company", path) == (
        (),
        [],
    )
    Path(path).write_text('{"templates": [{"unknown": "source-controlled rule"}]}')
    observations, diagnostics = template_observations(
        database, context, html, "http://example.com/company", path
    )
    assert not observations and diagnostics[0]["reason"] == "template_configuration_invalid"
    registry(Path(path), workspace, template)
    payload = json.loads(Path(path).read_text())
    payload["templates"][0]["fields"][0]["css"] = "["
    Path(path).write_text(json.dumps(payload))
    observations, diagnostics = template_observations(
        database, context, html, "http://example.com/company", path
    )
    assert not observations and diagnostics[0]["reason"] == "template_selector_invalid"
    assert template_observations(
        database, context, html, "http://example.com/company?different=1", path
    ) == ((), [])
    observations, diagnostics = template_observations(
        database,
        context.model_copy(update={"connection_ref": uuid4()}),
        html,
        "http://example.com/company",
        path,
    )
    assert not observations and diagnostics[0]["reason"] == "template_access_scope_mismatch"
