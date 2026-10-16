"""Separate encrypted initiating-owner Salesforce OAuth lifecycle."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_oauth_consents",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_hash", sa.String(64)),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("destination_id", UUID(as_uuid=False)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "destination_id"],
            ["crm_destinations.workspace_id", "crm_destinations.id"],
        ),
        sa.CheckConstraint("state IN ('pending','exchanging','active','revoked') AND version>0"),
        sa.CheckConstraint("octet_length(nonce)=12 AND octet_length(ciphertext)<=65536"),
        sa.UniqueConstraint("workspace_id", "destination_id"),
    )
    op.execute("ALTER TABLE crm_oauth_consents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_oauth_consents FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON crm_oauth_consents TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON crm_oauth_consents FOR ALL
      USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))
      WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))""")
    op.execute("""CREATE FUNCTION revoke_crm_oauth_on_disconnect() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      BEGIN
        IF NOT NEW.enabled OR NEW.generation<>OLD.generation THEN
          UPDATE public.crm_oauth_consents SET state='revoked',state_hash=NULL,ciphertext=''::bytea,version=version+1
            WHERE workspace_id=NEW.workspace_id AND destination_id=NEW.id;
        END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION revoke_crm_oauth_on_disconnect() FROM PUBLIC;
      CREATE TRIGGER crm_oauth_disconnect AFTER UPDATE ON crm_destinations
        FOR EACH ROW EXECUTE FUNCTION revoke_crm_oauth_on_disconnect()""")


def downgrade():
    op.execute("DROP TRIGGER crm_oauth_disconnect ON crm_destinations")
    op.execute("DROP FUNCTION revoke_crm_oauth_on_disconnect()")
    op.drop_table("crm_oauth_consents")
