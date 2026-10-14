"""Minimal scoped suppression markers and append-only deletion replay journal."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "erasure_journal",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("entity_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("url_hashes", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint("workspace_id", "request_key", "entity_id"),
    )
    op.execute(
        "ALTER TABLE erasure_journal ENABLE ROW LEVEL SECURITY; ALTER TABLE erasure_journal FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON erasure_journal TO skriller_app"
    )
    op.execute("""CREATE OR REPLACE FUNCTION prevent_immutable_change() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
        IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('list_snapshots','role_history')
          AND tenant_allowed(OLD.workspace_id)
          AND workspace_role(OLD.workspace_id,current_setting('app.actor_id',true))='owner'
          AND EXISTS(SELECT 1 FROM erasure_journal j WHERE j.workspace_id=OLD.workspace_id
            AND j.request_key=current_setting('app.erasure_request_key',true)) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Immutable record cannot be changed';
      END $$""")
    for table in ("list_snapshots", "role_history", "identity_events", "identity_reviews"):
        op.execute(f"GRANT DELETE ON {table} TO skriller_app")
        op.execute(f"""CREATE POLICY owner_erasure ON {table} FOR DELETE USING(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND EXISTS(SELECT 1 FROM erasure_journal j WHERE j.workspace_id={table}.workspace_id
            AND j.request_key=current_setting('app.erasure_request_key',true)))""")
    op.execute(
        "CREATE POLICY scoped_read ON erasure_journal FOR SELECT USING(tenant_allowed(workspace_id))"
    )
    op.execute("""CREATE POLICY owner_record ON erasure_journal FOR INSERT WITH CHECK(tenant_allowed(workspace_id)
      AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner' AND created_by=current_setting('app.actor_id',true))""")


def downgrade():
    for table in ("list_snapshots", "role_history", "identity_events", "identity_reviews"):
        op.execute(
            f"DROP POLICY owner_erasure ON {table}; REVOKE DELETE ON {table} FROM skriller_app"
        )
    op.execute(
        "CREATE OR REPLACE FUNCTION prevent_immutable_change() RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$ BEGIN RAISE EXCEPTION 'Immutable record cannot be changed'; END $$"
    )
    op.drop_table("erasure_journal")
