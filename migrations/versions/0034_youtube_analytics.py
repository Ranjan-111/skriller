"""Separate owner-authorised YouTube Analytics OAuth from public video reads."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "youtube_analytics_grants",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_hash", sa.String(64)),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("channel_id", sa.String(64)),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint("state IN ('pending','exchanging','active','revoked')"),
        sa.CheckConstraint("version>0"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext)<=65536"),
    )
    op.execute("ALTER TABLE youtube_analytics_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE youtube_analytics_grants FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON youtube_analytics_grants TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON youtube_analytics_grants FOR ALL
        USING(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND created_by=current_setting('app.actor_id',true))
        WITH CHECK(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND created_by=current_setting('app.actor_id',true))""")


def downgrade():
    op.drop_table("youtube_analytics_grants")
