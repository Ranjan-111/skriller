import csv
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_identity import fact, setup

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.contracts import Criterion, SearchPlan
from skriller.db import ConversationRepository
from skriller.db.schema import evidence
from skriller.exports import create_export, download_export
from skriller.exports.formats import serialize
from skriller.exports.router import router
from skriller.settings import Settings
from skriller.storage import BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


def fixture(database, tmp_path):
    actor, workspace, a, b = setup(database)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path / "exports"))
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Export fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="person",
            requested_fields=["name", "location", "size"],
            must_have=[Criterion(field="location", operator="eq", value="India")],
            preferences=[Criterion(field="size", operator="gte", value=10)],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        fact(session, a, "location", "India")
        fact(session, a, "name", "=Míra,\n東京")
        fact(session, b, "name", "Other")
    return actor, workspace, a, b, revision["id"], storage


@pytest.mark.parametrize("format", ["csv", "json", "jsonl"])
def test_formats_unicode_union_nulls_evidence_schema_and_formula_safety(database, tmp_path, format):
    actor, workspace, a, b, plan, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        result = create_export(
            session, storage, plan, (a, b), format=format, selected_near_ids=(b,)
        )
        content, kind = download_export(session, storage, result["id"])
        assert kind == format
    if format == "csv":
        rows = list(csv.DictReader(io.StringIO(content.decode())))
        assert rows[0]["field.name"] == "'=Míra,\n東京"
        assert rows[1]["field.location"] == ""
        assert "field.location" in json.loads(rows[1]["null_fields"])
        assert json.loads(rows[0]["export_metadata"])["evidence"][0]["source_url"]
    elif format == "json":
        doc = json.loads(content)
        rows = doc["records"]
        assert doc["metadata"]["schema_version"] == "skriller-qualified-v1"
        assert rows[0]["field.name"] == "=Míra,\n東京"
        assert rows[1]["field.location"] is None
    else:
        records = [json.loads(line) for line in content.decode().splitlines()]
        assert records[0]["type"] == "metadata"
        rows = records[1:]
        assert all(row["type"] == "record" for row in rows)
        assert rows[1]["field.location"] is None
    assert rows[0]["fit"] == "confirmed" and rows[1]["fit"] == "near_match"


@pytest.mark.parametrize("format", ["csv", "json", "jsonl"])
def test_empty_exports_are_valid_files(database, tmp_path, format):
    actor, workspace, _, _, plan, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        result = create_export(session, storage, plan, (), format=format)
        content, _ = download_export(session, storage, result["id"])
    assert content
    if format == "csv":
        assert list(csv.DictReader(io.StringIO(content.decode()))) == []
    elif format == "json":
        assert json.loads(content)["records"] == []
    else:
        assert json.loads(content)["type"] == "metadata"


def test_near_match_needs_explicit_selection_and_unverified_values_never_export(database, tmp_path):
    actor, workspace, a, b, plan, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ValueError):
            create_export(session, storage, plan, (b,), format="json")
        fact(session, a, "secret_guessed_email", "madeup@example.org", status="unverified")
        fact(session, a, "private_email", "private@example.org", status="accepted")
        result = create_export(session, storage, plan, (a,), format="json")
        content, _ = download_export(session, storage, result["id"])
        assert b"madeup@example.org" not in content
        assert b"private@example.org" not in content


def test_real_router_checks_bearer_tenant_expiry_and_private_headers(database, tmp_path):
    actor, workspace, a, _, plan, storage = fixture(database, tmp_path)
    other_actor, other_workspace, _, _ = setup(database)
    app = create_app(Settings())
    app.state.database, app.state.evidence_storage = database, storage
    if not any(
        getattr(route, "path", None) == "/v1/workspaces/{workspace_id}/exports"
        for route in app.routes
    ):
        app.include_router(router)
    client = TestClient(app)
    assert client.get(f"/v1/workspaces/{workspace}/exports/{uuid4()}").status_code == 401
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    response = client.post(
        f"/v1/workspaces/{workspace}/exports",
        json={"plan_id": plan, "entity_ids": [a], "format": "json"},
    )
    assert response.status_code == 200
    export = response.json()["id"]
    downloaded = client.get(f"/v1/workspaces/{workspace}/exports/{export}")
    assert downloaded.status_code == 200 and downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "object_key" not in response.text
    app.dependency_overrides[require_identity] = lambda: Identity(other_actor)
    assert client.get(f"/v1/workspaces/{other_workspace}/exports/{export}").status_code == 404
    with pytest.raises(BlobUnavailable), database.tenant(other_actor, other_workspace) as session:
        download_export(session, storage, export)
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == export)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert client.get(f"/v1/workspaces/{workspace}/exports/{export}").status_code == 404


def test_csv_formula_guards_preserve_negative_numeric_and_quoting():
    content = serialize(
        [{"value": " \t+cmd", "number": -12}, {"value": 'line, "quoted"\nnext', "number": None}],
        {"columns": ["value", "number"]},
        "csv",
    )
    rows = list(csv.DictReader(io.StringIO(content.decode())))
    assert rows[0] == {"value": "' \t+cmd", "number": "-12"}
    assert rows[1]["value"] == 'line, "quoted"\nnext'


def test_download_rechecks_source_evidence_expiry(database, tmp_path):
    actor, workspace, a, _, plan, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        result = create_export(session, storage, plan, (a,), format="json")
        content, _ = download_export(session, storage, result["id"])
        source_id = json.loads(content)["metadata"]["evidence"][0]["id"]
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == source_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        with pytest.raises(BlobUnavailable):
            download_export(session, storage, result["id"])


def test_excluded_group_cannot_be_exported_even_explicitly_selected(database, tmp_path):
    actor, workspace, a, _, plan_id, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        original = ConversationRepository.get_plan(session, plan_id)
        selected = SearchPlan.model_validate(original["interpretation"])
        selected = selected.model_copy(
            update={
                "revision": 2,
                "exclusions": [Criterion(field="location", operator="eq", value="India")],
            }
        )
        revised = ConversationRepository.revise_plan(
            session,
            original["conversation_id"],
            selected.model_dump(mode="json"),
            parent_id=plan_id,
        )
        with pytest.raises(ValueError, match="Only confirmed"):
            create_export(
                session, storage, revised["id"], (a,), format="json", selected_near_ids=(a,)
            )


def test_requested_contact_fields_require_published_professional_validation(database, tmp_path):
    actor, workspace, a, _, plan_id, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        original = ConversationRepository.get_plan(session, plan_id)
        selected = SearchPlan.model_validate(original["interpretation"])
        selected = selected.model_copy(
            update={
                "revision": 2,
                "requested_fields": ["private_email", "phone", "professional_email"],
            }
        )
        revised = ConversationRepository.revise_plan(
            session,
            original["conversation_id"],
            selected.model_dump(mode="json"),
            parent_id=plan_id,
        )
        fact(session, a, "private_email", "private@example.org")
        fact(session, a, "phone", "+12345678")
        fact(session, a, "professional_email", "public@example.org")
        result = create_export(session, storage, revised["id"], (a,), format="json")
        content, _ = download_export(session, storage, result["id"])
        record = json.loads(content)["records"][0]
        assert record["field.private_email"] is None and record["field.phone"] is None
        assert record["field.professional_email"] == "public@example.org"
        assert b"private@example.org" not in content and b"+12345678" not in content
