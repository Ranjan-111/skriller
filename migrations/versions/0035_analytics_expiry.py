"""Owner-authorised expired-secret cleanup across a workspace's grant owners."""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION expire_youtube_analytics_grants() RETURNS integer
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      DECLARE workspace uuid; removed integer;
      BEGIN
        workspace := current_setting('app.workspace_id',true)::uuid;
        IF workspace IS NULL OR NOT tenant_allowed(workspace)
          OR workspace_role(workspace,current_setting('app.actor_id',true)) IS DISTINCT FROM 'owner'
        THEN RAISE EXCEPTION 'Workspace owner required'; END IF;
        UPDATE public.youtube_analytics_grants
          SET state='revoked',state_hash=NULL,ciphertext=''::bytea,version=version+1
          WHERE workspace_id=workspace AND expires_at<=clock_timestamp() AND state<>'revoked';
        GET DIAGNOSTICS removed=ROW_COUNT;
        RETURN removed;
      END $$;
      REVOKE ALL ON FUNCTION expire_youtube_analytics_grants() FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION expire_youtube_analytics_grants() TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION expire_youtube_analytics_grants()")
