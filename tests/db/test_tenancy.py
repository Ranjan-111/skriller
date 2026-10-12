from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db import WorkspaceAccessDenied, WorkspaceRepository

pytestmark = pytest.mark.integration_db


def test_workspace_requires_membership_at_application_and_database_boundaries(database):
    actor_a, actor_b = str(uuid4()), str(uuid4())
    a = database.create_workspace(actor_a, "A")
    b = database.create_workspace(actor_b, "B")
    with pytest.raises(WorkspaceAccessDenied), database.tenant(actor_a, b["id"]):
        pass
    with database.tenant(actor_a, a["id"]) as session:
        assert WorkspaceRepository.get(session)["name"] == "A"
        assert (
            session.execute(
                sa.text("SELECT count(*) FROM workspaces WHERE id=:b"), {"b": b["id"]}
            ).scalar_one()
            == 0
        )
        session.execute(sa.text("SELECT set_config('app.workspace_id', :b, true)"), {"b": b["id"]})
        assert session.execute(sa.text("SELECT count(*) FROM workspaces")).scalar_one() == 0


def test_pool_context_resets_after_commit_and_failure(database):
    actor_a, actor_b = str(uuid4()), str(uuid4())
    a = database.create_workspace(actor_a, "A")
    b = database.create_workspace(actor_b, "B")
    with database.tenant(actor_a, a["id"]) as session:
        first_pid = session.execute(sa.text("SELECT pg_backend_pid()")).scalar_one()
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT nullif(current_setting('app.actor_id',true),'')")
            ).scalar_one()
            is None
        )
        assert connection.execute(sa.text("SELECT count(*) FROM workspaces")).scalar_one() == 0
    with pytest.raises(RuntimeError, match="rollback"), database.tenant(actor_a, a["id"]):
        raise RuntimeError("rollback")
    with database.tenant(actor_b, b["id"]) as session:
        assert session.execute(sa.text("SELECT pg_backend_pid()")).scalar_one() == first_pid
        assert session.execute(sa.text("SELECT name FROM workspaces")).scalars().all() == ["B"]


def test_member_cannot_add_members_even_with_direct_sql(database):
    owner, member = str(uuid4()), str(uuid4())
    workspace = database.create_workspace(owner, "Membership test")
    with database.tenant(owner, workspace["id"]) as session:
        WorkspaceRepository.add_member(session, member)
    with pytest.raises(WorkspaceAccessDenied), database.tenant(member, workspace["id"]) as session:
        WorkspaceRepository.add_member(session, str(uuid4()))
    with pytest.raises(DBAPIError), database.tenant(member, workspace["id"]) as session:
        session.execute(
            sa.text("INSERT INTO memberships VALUES(:w,:actor,'owner')"),
            {"w": workspace["id"], "actor": str(uuid4())},
        )
    with database.engine.connect() as connection:
        role = connection.execute(
            sa.text(
                "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        assert not any(role)
        assert (
            connection.execute(
                sa.text(
                    "SELECT c.relowner=current_user::regrole FROM pg_class c "
                    "WHERE c.relname='workspaces'"
                )
            ).scalar_one()
            is False
        )


def test_owner_connection_is_rejected_for_normal_application_sessions(database):
    from skriller.db import Database
    from skriller.settings import Settings

    owner_db = Database(Settings().database_url)
    try:
        with pytest.raises(RuntimeError, match="non-owner"):
            owner_db.create_workspace(str(uuid4()), "Must not use owner engine")
    finally:
        owner_db.dispose()
