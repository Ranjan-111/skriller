"""Opt-in signed snapshot notifications and durable delivery leases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "webhook_endpoints",
        *common(),
        sa.Column("list_id", UUID(as_uuid=False), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "list_id"], ["saved_lists.workspace_id", "saved_lists.id"]
        ),
    )
    op.create_table(
        "webhook_deliveries",
        *common(),
        sa.Column("endpoint_id", UUID(as_uuid=False), nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=False), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_token", UUID(as_uuid=False)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_code", sa.String(32)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "endpoint_id"],
            ["webhook_endpoints.workspace_id", "webhook_endpoints.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"], ["list_snapshots.workspace_id", "list_snapshots.id"]
        ),
        sa.UniqueConstraint("workspace_id", "endpoint_id", "snapshot_id"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5"),
        sa.CheckConstraint(
            "state IN ('pending','delivering','delivered','failed','cancelled','blocked')"
        ),
    )
    op.create_index("webhook_due", "webhook_deliveries", ["workspace_id", "next_attempt_at"])
    for table in ("webhook_endpoints", "webhook_deliveries"):
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table} FORCE ROW LEVEL SECURITY"
        )
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON {table} TO skriller_app")
        op.execute(f"""CREATE POLICY owner_write ON {table} FOR ALL
          USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')
          WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')""")


def downgrade():
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
