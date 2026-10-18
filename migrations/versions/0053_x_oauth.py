"""Encrypted initiating-owner X OAuth lifecycle and access-generation fences."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "x_oauth_consents",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_hash", sa.String(64)),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=False)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.CheckConstraint("state IN ('pending','exchanging','active','revoked') AND version>0"),
        sa.CheckConstraint("octet_length(nonce)=12 AND octet_length(ciphertext)<=65536"),
        sa.UniqueConstraint("workspace_id", "connection_id"),
    )
    op.execute("ALTER TABLE x_oauth_consents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE x_oauth_consents FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON x_oauth_consents TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON x_oauth_consents FOR ALL
      USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))
      WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))""")
    op.execute("""CREATE FUNCTION revoke_x_oauth_on_disconnect() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      BEGIN
        IF NEW.state='revoked' THEN
          UPDATE public.x_oauth_consents SET state='revoked',state_hash=NULL,ciphertext=''::bytea,version=version+1
            WHERE workspace_id=NEW.workspace_id AND connection_id=NEW.id AND state<>'revoked';
        END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION revoke_x_oauth_on_disconnect() FROM PUBLIC;
      CREATE TRIGGER x_oauth_disconnect AFTER UPDATE ON source_connections
        FOR EACH ROW EXECUTE FUNCTION revoke_x_oauth_on_disconnect()""")
    op.execute("""CREATE FUNCTION expire_x_oauth_consents() RETURNS integer
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      DECLARE workspace uuid; removed integer;
      BEGIN
        workspace := current_setting('app.workspace_id',true)::uuid;
        IF workspace IS NULL OR NOT tenant_allowed(workspace)
          OR workspace_role(workspace,current_setting('app.actor_id',true)) IS DISTINCT FROM 'owner'
        THEN RAISE EXCEPTION 'Workspace owner required'; END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('privacy:' || workspace::text,0));
        DELETE FROM public.source_connection_secrets s WHERE s.workspace_id=workspace AND EXISTS(
          SELECT 1 FROM public.x_oauth_consents c WHERE c.workspace_id=workspace
            AND c.connection_id=s.connection_id AND (c.expires_at<=clock_timestamp()
            OR workspace_role(workspace,c.created_by) IS DISTINCT FROM 'owner'));
        UPDATE public.source_connections s SET state='revoked',revoked_at=clock_timestamp()
          WHERE s.workspace_id=workspace AND s.state<>'revoked' AND EXISTS(
            SELECT 1 FROM public.x_oauth_consents c WHERE c.workspace_id=workspace
              AND c.connection_id=s.id AND (c.expires_at<=clock_timestamp()
              OR workspace_role(workspace,c.created_by) IS DISTINCT FROM 'owner'));
        UPDATE public.x_oauth_consents SET state='revoked',state_hash=NULL,ciphertext=''::bytea,version=version+1
          WHERE workspace_id=workspace AND state<>'revoked' AND (expires_at<=clock_timestamp()
          OR workspace_role(workspace,created_by) IS DISTINCT FROM 'owner');
        GET DIAGNOSTICS removed=ROW_COUNT;
        RETURN removed;
      END $$;
      REVOKE ALL ON FUNCTION expire_x_oauth_consents() FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION expire_x_oauth_consents() TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION expire_x_oauth_consents()")
    op.execute("DROP TRIGGER x_oauth_disconnect ON source_connections")
    op.execute("DROP FUNCTION revoke_x_oauth_on_disconnect()")
    op.drop_table("x_oauth_consents")
