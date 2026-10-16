"""Owner-scoped, bounded qualified-record CRM delivery ledger."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_deliveries",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("destination_id", UUID(as_uuid=False), nullable=False),
        sa.Column("destination_generation", sa.Integer, nullable=False),
        sa.Column("plan_id", UUID(as_uuid=False), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
        sa.Column("selected_near", sa.Boolean, nullable=False),
        sa.Column("field_map", sa.JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
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
        sa.Column("last_code", sa.String(40)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "destination_id"],
            ["crm_destinations.workspace_id", "crm_destinations.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.UniqueConstraint("workspace_id", "created_by", "idempotency_key"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5 AND destination_generation>0"),
        sa.CheckConstraint(
            "state IN ('pending','delivering','succeeded','failed','suppressed','cancelled')"
        ),
    )
    op.execute("ALTER TABLE crm_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_deliveries FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON crm_deliveries TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON crm_deliveries FOR ALL
      USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))
      WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND created_by=current_setting('app.actor_id',true))""")
    op.create_index(
        "crm_due_owner",
        "crm_deliveries",
        ["workspace_id", "created_by", "state", "next_attempt_at"],
    )


def downgrade():
    op.drop_table("crm_deliveries")
