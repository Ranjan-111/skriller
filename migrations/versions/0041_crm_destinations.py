"""Initiating-owner encrypted Salesforce destinations, independent of sources."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_destinations",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("instance_url", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "generation>0 AND octet_length(nonce)=12 AND octet_length(ciphertext)<=16384"
        ),
    )
    op.execute("ALTER TABLE crm_destinations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_destinations FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON crm_destinations TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON crm_destinations FOR ALL
      USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))
      WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))""")


def downgrade():
    op.drop_table("crm_destinations")
