"""Bounded private analytics payload lifetime across initiating owners."""

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION expire_analytics_summary_snapshots() RETURNS integer
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      DECLARE workspace uuid; removed integer;
      BEGIN
        workspace := current_setting('app.workspace_id',true)::uuid;
        IF workspace IS NULL OR NOT tenant_allowed(workspace)
          OR workspace_role(workspace,current_setting('app.actor_id',true)) IS DISTINCT FROM 'owner'
        THEN RAISE EXCEPTION 'Workspace owner required'; END IF;
        UPDATE public.youtube_analytics_summary_jobs
          SET ciphertext=''::bytea,state='cancelled'
          WHERE workspace_id=workspace AND expires_at<=clock_timestamp()
            AND octet_length(ciphertext)>0;
        GET DIAGNOSTICS removed=ROW_COUNT;
        RETURN removed;
      END $$;
      REVOKE ALL ON FUNCTION expire_analytics_summary_snapshots() FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION expire_analytics_summary_snapshots() TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION expire_analytics_summary_snapshots()")
