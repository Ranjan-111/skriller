from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from lxml.html import fromstring
from scrapling.core.storage import StorageSystemMixin

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope, storage_arguments
from skriller.contracts import ExecutionContext
from skriller.db import WorkspaceAccessDenied


def context(workspace, connection=None):
    return ExecutionContext(
        workspace_id=workspace,
        job_id=uuid4(),
        actor_id="verified-test-actor",
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        attempt_budget=1,
        connection_ref=connection,
    )


def test_cache_contract_and_scope_identity():
    assert issubclass(PostgreSQLStorageSystem.__wrapped__, StorageSystemMixin)
    workspace, template = uuid4(), uuid4()
    scope = StorageScope(workspace, "web", "public", template, 1)
    assert hash(scope) == hash(StorageScope(workspace, "web", "public", template, 1))
    assert scope != StorageScope(workspace, "web", "public", template, 2)


@pytest.mark.parametrize("version", [0, -1, True, 1.5])
def test_invalid_template_version_rejected(version):
    with pytest.raises(ValueError, match="positive"):
        StorageScope(uuid4(), "web", "public", uuid4(), version)


@pytest.mark.parametrize("scope", ["../other-workspace", "session", "connection:not-a-uuid"])
def test_access_scope_not_a_filesystem_path_or_arbitrary_session(scope):
    with pytest.raises(ValueError):
        StorageScope(uuid4(), "web", scope, uuid4(), 1)


def test_trusted_context_must_match_workspace_and_connection():
    workspace, connection = uuid4(), uuid4()
    scope = StorageScope(workspace, "linkedin", f"connection:{connection}", uuid4(), 1)
    database = object()
    with pytest.raises(WorkspaceAccessDenied, match="workspace"):
        storage_arguments(database, context(uuid4(), connection), scope, "https://linkedin.com")
    with pytest.raises(WorkspaceAccessDenied, match="connection"):
        storage_arguments(database, context(workspace, uuid4()), scope, "https://linkedin.com")
    public_scope = StorageScope(workspace, "linkedin", "public", uuid4(), 1)
    with pytest.raises(WorkspaceAccessDenied, match="connection"):
        storage_arguments(
            database, context(workspace, connection), public_scope, "https://linkedin.com"
        )
    args = storage_arguments(
        database, context(workspace, connection), scope, "https://linkedin.com"
    )
    assert args["scope"] == scope and args["actor_id"] == "verified-test-actor"


def test_storage_constructor_requires_public_url_and_verified_actor():
    scope = StorageScope(uuid4(), "web", "public", uuid4(), 1)
    with pytest.raises(WorkspaceAccessDenied):
        PostgreSQLStorageSystem(object(), "", scope, "https://example.com")
    with pytest.raises(ValueError):
        PostgreSQLStorageSystem(object(), "actor", scope, "file:///etc/passwd")
    first = PostgreSQLStorageSystem(object(), "actor", scope, "https://example.com")
    assert first.domain == "example.com"
    with pytest.raises(ValueError):
        first._key("")
    with pytest.raises(ValueError):
        first._key("a" * 4097)


def test_rejected_identifier_collision_is_not_silent_success():
    class CollisionResult:
        def scalar_one_or_none(self):
            return None

    class Session:
        def execute(self, statement):
            return CollisionResult()

    class DatabaseFixture:
        @contextmanager
        def tenant(self, actor, workspace):
            yield Session()

    scope = StorageScope(uuid4(), "web", "public", uuid4(), 1)
    storage = PostgreSQLStorageSystem(DatabaseFixture(), "actor", scope, "https://example.com")
    with pytest.raises(ValueError, match="collision"):
        storage.save(fromstring("<article>Must not replace another key</article>"), "selector")
