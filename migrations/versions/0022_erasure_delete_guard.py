"""Reject unauthorized immutable deletion explicitly, including owner sessions."""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION require_erasure_delete() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
        IF tenant_allowed(OLD.workspace_id)
          AND workspace_role(OLD.workspace_id,current_setting('app.actor_id',true))='owner'
          AND EXISTS(SELECT 1 FROM erasure_journal j WHERE j.workspace_id=OLD.workspace_id
            AND j.request_key=current_setting('app.erasure_request_key',true)) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Immutable deletion requires an owner erasure journal';
      END $$;
      REVOKE ALL ON FUNCTION require_erasure_delete() FROM PUBLIC;""")
    for table in ("list_snapshots", "role_history", "identity_events", "identity_reviews"):
        op.execute(f"DROP POLICY owner_erasure ON {table}")
        op.execute(f"""CREATE POLICY owner_erasure ON {table} FOR DELETE USING(
          tenant_allowed(workspace_id) AND
          workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')""")
        op.execute(f"""CREATE TRIGGER erasure_delete_guard BEFORE DELETE ON {table}
          FOR EACH ROW EXECUTE FUNCTION require_erasure_delete()""")


def downgrade():
    for table in ("list_snapshots", "role_history", "identity_events", "identity_reviews"):
        op.execute(
            f"DROP TRIGGER erasure_delete_guard ON {table}; DROP POLICY owner_erasure ON {table}"
        )
        op.execute(f"""CREATE POLICY owner_erasure ON {table} FOR DELETE USING(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND EXISTS(SELECT 1 FROM erasure_journal j WHERE j.workspace_id={table}.workspace_id
            AND j.request_key=current_setting('app.erasure_request_key',true)))""")
    op.execute("DROP FUNCTION require_erasure_delete()")
