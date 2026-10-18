"""Boolean-only X grant validity fence across initiating-owner RLS boundaries."""

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION x_connection_allowed(workspace uuid, connection uuid) RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
        SELECT public.tenant_allowed(workspace) AND EXISTS(
          SELECT 1 FROM public.source_connections s WHERE s.workspace_id=workspace AND s.id=connection
            AND s.source='x' AND s.auth_kind='oauth' AND s.state='active'
            AND public.workspace_role(workspace,s.created_by)='owner'
            AND NOT EXISTS(SELECT 1 FROM public.x_oauth_consents c
              WHERE c.workspace_id=workspace AND c.connection_id=connection
              AND (c.state<>'active' OR c.expires_at<=clock_timestamp()
                OR c.created_by<>s.created_by)))
      $$;
      REVOKE ALL ON FUNCTION x_connection_allowed(uuid,uuid) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION x_connection_allowed(uuid,uuid) TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION x_connection_allowed(uuid,uuid)")
