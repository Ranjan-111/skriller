"""Explicit owner bootstrap and transaction-scoped non-owner tenant sessions."""

from contextlib import contextmanager
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session


class WorkspaceAccessDenied(PermissionError):
    """Verified actor is not a member of the requested workspace."""


def bootstrap(owner_url: str, *, application_password: str) -> None:
    """Provision the restricted login role using an explicit owner connection."""
    from psycopg import sql

    engine = sa.create_engine(owner_url, connect_args={"connect_timeout": 5})
    try:
        with engine.begin() as connection:
            driver = connection.connection.driver_connection
            if driver is None:
                raise RuntimeError("Bootstrap requires an active PostgreSQL driver connection")
            cursor = driver.cursor()
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'skriller_app'")
            exists = cursor.fetchone()
            action = "ALTER" if exists else "CREATE"
            cursor.execute(
                sql.SQL(
                    action + " ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}"
                ).format(sql.Identifier("skriller_app"), sql.Literal(application_password))
            )
            cursor.execute(
                "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
                "WHERE r.rolname='skriller_app'"
            )
            if cursor.fetchone():
                raise RuntimeError("Application role must not inherit any other role")
    finally:
        engine.dispose()


class Database:
    def __init__(self, application_url: str, *, pool_size: int = 5):
        self.engine = sa.create_engine(
            application_url, pool_size=pool_size, max_overflow=0, pool_pre_ping=True
        )

    @staticmethod
    def _assert_application_role(session):
        role = session.execute(
            sa.text(
                "SELECT r.rolsuper, r.rolbypassrls, "
                "EXISTS(SELECT 1 FROM pg_class c WHERE c.relname='workspaces' "
                "AND c.relowner=r.oid) AS owns_tenant_table FROM pg_roles r "
                "WHERE r.rolname=current_user"
            )
        ).one()
        if any(role):
            raise RuntimeError("Tenant sessions require a restricted non-owner database role")

    @contextmanager
    def tenant(self, actor_id: str, workspace_id: str):
        workspace_id = str(UUID(str(workspace_id)))
        if not actor_id or len(actor_id) > 128:
            raise WorkspaceAccessDenied("Invalid actor identity")
        with Session(self.engine) as session, session.begin():
            self._assert_application_role(session)
            session.execute(
                sa.text(
                    "SELECT set_config('app.actor_id', :actor, true), "
                    "set_config('app.workspace_id', :workspace, true)"
                ),
                {"actor": actor_id, "workspace": workspace_id},
            )
            membership = session.execute(
                sa.text("SELECT workspace_role(:workspace, :actor)"),
                {"workspace": workspace_id, "actor": actor_id},
            ).scalar_one()
            if membership is None:
                raise WorkspaceAccessDenied("Workspace membership required")
            session.info.update(actor_id=actor_id, workspace_id=workspace_id, role=membership)
            yield session

    def create_workspace(self, actor_id: str, name: str) -> dict:
        if not actor_id or len(actor_id) > 128 or not name.strip() or len(name) > 200:
            raise ValueError("Valid actor and workspace name required")
        with Session(self.engine) as session, session.begin():
            self._assert_application_role(session)
            session.execute(
                sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor_id}
            )
            row = (
                session.execute(sa.text("SELECT * FROM create_workspace(:name)"), {"name": name})
                .mappings()
                .one()
            )
            return {**dict(row), "id": str(row["id"])}

    def dispose(self):
        self.engine.dispose()
