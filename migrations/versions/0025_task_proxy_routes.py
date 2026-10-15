"""Durable tenant-private task egress bindings and traffic counters."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_proxy_routes",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("job_id", UUID(as_uuid=False), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=False)),
        sa.Column("account_connection_id", UUID(as_uuid=False)),
        sa.Column("configuration_digest", sa.String(64), nullable=False),
        sa.Column("provider_index", sa.Integer),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("traffic_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("failed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "account_connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.UniqueConstraint("workspace_id", "job_id", "source"),
        sa.CheckConstraint("attempts >= 0 AND traffic_bytes >= 0"),
        sa.CheckConstraint("provider_index IS NULL OR provider_index BETWEEN 0 AND 7"),
    )
    op.execute(
        "ALTER TABLE task_proxy_routes ENABLE ROW LEVEL SECURITY; ALTER TABLE task_proxy_routes FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT,UPDATE ON task_proxy_routes TO skriller_app"
    )
    op.execute(
        "CREATE POLICY scoped_read ON task_proxy_routes FOR SELECT USING(tenant_allowed(workspace_id))"
    )
    actor = "tenant_allowed(workspace_id) AND created_by=current_setting('app.actor_id',true)"
    op.execute(f"CREATE POLICY actor_insert ON task_proxy_routes FOR INSERT WITH CHECK({actor})")
    op.execute(
        f"CREATE POLICY actor_update ON task_proxy_routes FOR UPDATE USING({actor}) WITH CHECK({actor})"
    )


def downgrade():
    op.drop_table("task_proxy_routes")
