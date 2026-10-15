"""Owner publication, immutable history and actual saved-page runtime selection."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from test_adaptive_pipeline import registry, seed
from test_page_extraction_workflow import ModelFixture, prepare_page

from skriller.auth import Identity, require_identity
from skriller.contracts import ExecutionContext
from skriller.db import ResearchRepository, WorkspaceRepository
from skriller.db.schema import page_template_audit, reviewed_template_versions
from skriller.extraction.models import LocalStructuredModel
from skriller.research.adaptive_templates import ReviewedTemplate, template_observations
from skriller.research.page_extraction import execute_page_extraction
from skriller.research.template_registry import publish_template, selected_templates
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def setup(database, monkeypatch, endpoint, tmp_path):
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
    path = tmp_path / "reviewed.json"
    registry(path, context.workspace_id, uuid4())
    template = json.loads(path.read_text())["templates"][0]
    return actor, client, accepted, task, storage, context, path, template


def test_owner_publication_rollback_and_saved_page_use_durable_active_version(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, _, _ = proxy
    actor, client, accepted, task, storage, context, path, template = setup(
        database, monkeypatch, endpoint, tmp_path
    )
    html, _ = seed(database, context, UUID(template["template_id"]))
    endpoint = f"/v1/workspaces/{context.workspace_id}/page-templates"
    response = client.post(endpoint, json={"template": template})
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    next_template = {
        **template,
        "template_version": 2,
        "fields": [{**template["fields"][0], "css": "h1"}],
    }
    assert (
        client.post(endpoint, json={"template": next_template, "expected_version": 1}).status_code
        == 201
    )
    observations, diagnostics = template_observations(
        database, context, html, template["source_url"], str(path)
    )
    assert observations and diagnostics[0]["template_version"] == 2
    assert not diagnostics[0][
        "recovered"
    ]  # Explicit database selection supersedes the legacy file.
    rollback = endpoint + f"/{template['template_id']}/rollback"
    assert (
        client.post(rollback, json={"target_version": 1, "expected_version": 2}).status_code == 200
    )
    assert (
        client.post(rollback, json={"target_version": 1, "expected_version": 2}).status_code == 409
    )
    stale = {**next_template, "template_version": 3}
    assert client.post(endpoint, json={"template": stale, "expected_version": 2}).status_code == 409
    assert client.get(endpoint).json()[0]["template_version"] == 1
    observations, diagnostics = template_observations(
        database, context, html, template["source_url"], None
    )
    assert observations and diagnostics[0]["recovered"] and diagnostics[0]["template_version"] == 1
    assert template_observations(database, context, html, "https://example.org/other", None) == (
        (),
        [],
    )
    result = execute_page_extraction(
        database,
        task,
        storage=storage,
        settings=Settings(),
        model=LocalStructuredModel(model_instance=ModelFixture()),
    )
    assert result["status"] == "checkpointed"
    row = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"][0]
    assert row["qualification"] == "unverified"
    assert any(
        item["field"] == "company_name" and item["value"] == "Aurora Ledger"
        for item in row["extraction"]["observations"]
    )
    with database.tenant(actor, str(context.workspace_id)) as session:
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(reviewed_template_versions)
            ).scalar_one()
            == 2
        )
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(page_template_audit)
            ).scalar_one()
            == 3
        )
        assert (
            ResearchRepository.get_entity(session, row["id"])["attributes"]["_adaptive_validation"][
                0
            ]["template_version"]
            == 1
        )


def test_registry_rejects_other_workspace_members_ambiguous_fields_and_invalid_rules(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, _, _ = proxy
    actor, client, _, _, _, context, _, template = setup(database, monkeypatch, endpoint, tmp_path)
    url = f"/v1/workspaces/{context.workspace_id}/page-templates"
    assert (
        client.post(url, json={"template": {**template, "workspace_id": str(uuid4())}}).status_code
        == 409
    )
    bad = {**template, "fields": [{**template["fields"][0], "css": "["}]}
    assert client.post(url, json={"template": bad}).status_code == 409
    assert client.post(url, json={"template": template}).status_code == 201
    other = database.create_workspace(actor, "Separate reviewed mappings")["id"]
    other_template = {**template, "workspace_id": other}
    other_url = f"/v1/workspaces/{other}/page-templates"
    assert client.post(other_url, json={"template": other_template}).status_code == 201
    assert client.get(url).json()[0]["workspace_id"] == str(context.workspace_id)
    assert client.get(other_url).json()[0]["workspace_id"] == other
    conflicting = {**template, "template_id": str(uuid4())}
    assert client.post(url, json={"template": conflicting}).status_code == 409
    changed_source = {**template, "source_url": "https://example.org/other", "template_version": 2}
    assert (
        client.post(url, json={"template": changed_source, "expected_version": 1}).status_code
        == 409
    )
    member = f"template-member-{uuid4()}"
    with database.tenant(actor, str(context.workspace_id)) as session:
        WorkspaceRepository.add_member(session, member)
    client.app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.get(url).status_code == 403
    assert client.post(url, json={"template": template}).status_code == 403
    with (
        database.tenant(member, str(context.workspace_id)) as session,
        pytest.raises(sa.exc.DBAPIError),
    ):
        session.execute(
            sa.insert(reviewed_template_versions).values(
                workspace_id=str(context.workspace_id),
                template_id=str(uuid4()),
                template_version=1,
                source_url=template["source_url"],
                source_hash="0" * 64,
                payload=template,
                created_by=member,
            )
        )
    for statement in (
        sa.update(reviewed_template_versions).values(payload={}),
        sa.delete(reviewed_template_versions),
    ):
        with (
            database.tenant(actor, str(context.workspace_id)) as session,
            pytest.raises(sa.exc.DBAPIError),
        ):
            session.execute(statement)
    with database.tenant(actor, str(context.workspace_id)) as session:
        assert len(selected_templates(session)) == 1
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(reviewed_template_versions)
            ).scalar_one()
            == 1
        )


def test_concurrent_publications_compare_active_version_and_preserve_losing_history(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, _, _ = proxy
    actor, _, _, _, _, context, _, template = setup(database, monkeypatch, endpoint, tmp_path)
    with database.tenant(actor, str(context.workspace_id)) as session:
        publish_template(session, ReviewedTemplate.model_validate(template), expected_version=None)

    def publish(css):
        candidate = ReviewedTemplate.model_validate(
            {**template, "template_version": 2, "fields": [{**template["fields"][0], "css": css}]}
        )
        try:
            with database.tenant(actor, str(context.workspace_id)) as session:
                publish_template(session, candidate, expected_version=1)
            return "published"
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(publish, ["h1", "main h1"])) == ["conflict", "published"]
    with database.tenant(actor, str(context.workspace_id)) as session:
        assert selected_templates(session)[0].template_version == 2
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(reviewed_template_versions)
            ).scalar_one()
            == 2
        )
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(page_template_audit)
            ).scalar_one()
            == 2
        )
