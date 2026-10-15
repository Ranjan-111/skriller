from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.diagnostics import diagnose
from skriller.connectors.registry import ConnectorRegistry
from skriller.connectors.router import router
from skriller.connectors.switches import is_disabled, set_disabled, source_switches
from skriller.db import WorkspaceRepository
from skriller.db.schema import entities
from skriller.settings import Settings


def setup(database):
    owner = f"diagnostics-{uuid4()}"
    workspace = database.create_workspace(owner, "Diagnostics fixture")["id"]
    app = create_app(Settings())
    app.state.database = database
    if not any(
        getattr(route, "path", None) == "/v1/workspaces/{workspace_id}/sources"
        for route in app.routes
    ):
        app.include_router(router)
    app.dependency_overrides[require_identity] = lambda: Identity(owner)
    return owner, workspace, app, TestClient(app)


def test_public_discovery_is_not_authenticated_platform_access(database, monkeypatch):
    _owner, workspace, _, client = setup(database)
    monkeypatch.setattr(
        "agent_reach.doctor.check_all", lambda *_: pytest.fail("Host doctor forbidden")
    )
    response = client.get(f"/v1/workspaces/{workspace}/sources")
    assert response.status_code == 200
    assert len(response.json()) == 27
    linked = [row for row in response.json() if row["capability"]["source"] == "linkedin"]
    discovery = next(row for row in linked if row["capability"]["operation"] == "discover")
    read = next(row for row in linked if row["capability"]["operation"] == "read")
    assert discovery["setup_state"] == "experimental"
    assert discovery["evidence_scope"] == "public_indexed_references"
    assert discovery["credential_validation"] == "not_performed"
    assert read["setup_state"] == "needs_connection"
    assert read["capability"]["engineering_status"] == "planned"


def test_one_operation_failure_is_redacted_and_does_not_break_others(database):
    owner, workspace, _, _ = setup(database)
    registry = ConnectorRegistry(UUID(workspace))
    original = registry.capability

    def fail_one(source, operation):
        if (source, operation) == ("linkedin", "read"):
            raise RuntimeError("secret-cookie-and-host-path")
        return original(source, operation)

    registry.capability = fail_one
    with database.tenant(owner, workspace) as session:
        result = diagnose(session, registry)
    assert len(result) == 27
    assert sum(row.setup_state == "diagnostic_error" for row in result) == 1
    assert "secret-cookie-and-host-path" not in str(result)
    assert (
        next(
            row
            for row in result
            if (row.capability.source, row.capability.operation) == ("reddit", "discover")
        ).setup_state
        == "experimental"
    )


def test_owner_switch_is_persistent_operation_scoped_and_retains_results(database):
    owner, workspace, _, client = setup(database)
    base = f"/v1/workspaces/{workspace}/sources"
    with database.tenant(owner, workspace) as session:
        session.execute(
            sa.insert(entities).values(
                workspace_id=workspace, id=str(uuid4()), kind="other", attributes={}
            )
        )
        before = session.execute(sa.select(sa.func.count()).select_from(entities)).scalar_one()
    response = client.put(f"{base}/linkedin/read", json={"disabled": True})
    assert response.status_code == 200, response.text
    assert response.json()["setup_state"] == "disabled"
    assert client.put(f"{base}/linkedin/read", json={"disabled": True}).status_code == 200
    with database.tenant(owner, workspace) as session:
        assert is_disabled(session, "linkedin", "read")
        assert not is_disabled(session, "linkedin", "discover")
        assert not is_disabled(session, "reddit", "read")
        assert (
            session.execute(sa.select(sa.func.count()).select_from(entities)).scalar_one() == before
        )
        assert (
            session.execute(sa.select(sa.func.count()).select_from(source_switches)).scalar_one()
            == 1
        )
    assert client.put(f"{base}/linkedin/read", json={"disabled": False}).json()["disabled"] is False


def test_member_read_owner_write_and_foreign_scope_denied(database):
    owner, workspace, app, client = setup(database)
    member = f"member-{uuid4()}"
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    base = f"/v1/workspaces/{workspace}/sources"
    app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.get(base).status_code == 200
    assert client.put(f"{base}/web/discover", json={"disabled": True}).status_code == 403
    with database.tenant(member, workspace) as session, pytest.raises(sa.exc.DBAPIError):
        session.execute(
            sa.insert(source_switches).values(
                workspace_id=workspace,
                id=str(uuid4()),
                source="web",
                operation="read",
                disabled=True,
                updated_by=member,
            )
        )
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.get(base).status_code == 404
    assert client.put(f"{base}/web/discover", json={"disabled": True}).status_code == 403
    app.dependency_overrides.clear()
    assert client.get(base).status_code == 401


def test_switches_do_not_cross_tenants_and_invalid_operations_rejected(database):
    owner, workspace, _, client = setup(database)
    other = database.create_workspace(owner, "Separate fixture")["id"]
    with database.tenant(owner, workspace) as session:
        set_disabled(session, "reddit", "discover", True)
    with database.tenant(owner, other) as session:
        assert not is_disabled(session, "reddit", "discover")
        with pytest.raises(ValueError):
            diagnose(session, ConnectorRegistry(UUID(workspace)))
    base = f"/v1/workspaces/{workspace}/sources"
    assert client.put(f"{base}/unknown/read", json={"disabled": True}).status_code == 422
    assert client.put(f"{base}/reddit/execute", json={"disabled": True}).status_code == 422
    assert client.put(f"{base}/reddit/read", json={"disabled": "false"}).status_code == 422


def test_globally_disabled_search_is_not_reported_operational(database):
    _, workspace, app, client = setup(database)
    app.state.settings = Settings(search_provider="disabled")
    response = client.get(f"/v1/workspaces/{workspace}/sources")
    assert response.status_code == 200
    discovery = [row for row in response.json() if row["capability"]["operation"] == "discover"]
    assert len(discovery) == 9
    assert all(row["setup_state"] == "unavailable" for row in discovery)


def test_youtube_configuration_is_reported_without_promoting_sample_to_tenant_verification(
    database, monkeypatch
):
    _, workspace, app, client = setup(database)
    monkeypatch.setattr(
        "skriller.connectors.youtube_executor.IsolatedRunner.run",
        lambda *args, **kwargs: pytest.fail("Diagnostics must not launch source reads"),
    )
    url = f"/v1/workspaces/{workspace}/sources"

    def read_status():
        response = client.get(url)
        assert response.status_code == 200
        return next(
            row
            for row in response.json()
            if (row["capability"]["source"], row["capability"]["operation"]) == ("youtube", "read")
        )

    disabled = read_status()
    assert disabled["setup_state"] == "unavailable"
    assert disabled["capability"]["engineering_status"] == "tested"
    app.state.settings = Settings(
        public_collection_proxy_url="http://127.0.0.1:18080",
        public_youtube_image="sha256:" + "a" * 64,
    )
    configured = read_status()
    assert configured["setup_state"] == "experimental"
    assert configured["capability"]["auth_kind"] == "none"
    assert configured["evidence_scope"] == "dedicated_adapter"
    assert "analytics" not in configured["capability"]["allowed_fields"]
    switched = client.put(url + "/youtube/read", json={"disabled": True})
    assert switched.status_code == 200 and switched.json()["setup_state"] == "disabled"
