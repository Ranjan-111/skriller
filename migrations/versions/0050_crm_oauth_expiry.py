"""Owner-bound expiry wipe across CRM consent owners and pending deliveries."""

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION expire_crm_oauth_consents() RETURNS integer
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      DECLARE workspace uuid; removed integer;
      BEGIN
        workspace := current_setting('app.workspace_id',true)::uuid;
        IF workspace IS NULL OR NOT tenant_allowed(workspace)
          OR workspace_role(workspace,current_setting('app.actor_id',true)) IS DISTINCT FROM 'owner'
        THEN RAISE EXCEPTION 'Workspace owner required'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('privacy:' || workspace::text,0));
        UPDATE public.crm_destinations d SET enabled=false,ciphertext=''::bytea,generation=generation+1
          WHERE d.workspace_id=workspace AND d.enabled AND EXISTS(
            SELECT 1 FROM public.crm_oauth_consents c WHERE c.workspace_id=workspace
              AND c.destination_id=d.id AND c.expires_at<=clock_timestamp());
        UPDATE public.crm_deliveries d SET state='cancelled',last_code='consent_expired',
          lease_token=NULL,lease_expires_at=NULL
          WHERE d.workspace_id=workspace AND d.state IN ('pending','delivering') AND EXISTS(
            SELECT 1 FROM public.crm_oauth_consents c WHERE c.workspace_id=workspace
              AND c.destination_id=d.destination_id AND c.expires_at<=clock_timestamp());
        UPDATE public.crm_oauth_consents SET state='revoked',state_hash=NULL,ciphertext=''::bytea,version=version+1
          WHERE workspace_id=workspace AND expires_at<=clock_timestamp() AND state<>'revoked';
        GET DIAGNOSTICS removed=ROW_COUNT;
        RETURN removed;
      END $$;
      REVOKE ALL ON FUNCTION expire_crm_oauth_consents() FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION expire_crm_oauth_consents() TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION expire_crm_oauth_consents()")
