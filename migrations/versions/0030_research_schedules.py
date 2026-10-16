"""Bounded opt-in saved-plan refresh scheduling with durable occurrence identity."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0030"
down_revision = "0029"
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
        "research_schedules",
        *common(),
        sa.Column("list_id", UUID(as_uuid=False), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("cadence_hours", sa.Integer, nullable=False),
        sa.Column("max_runs", sa.Integer, nullable=False),
        sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("required_connection_ids", sa.JSON, nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", UUID(as_uuid=False)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_job_id", UUID(as_uuid=False)),
        sa.Column("last_reason", sa.String(40)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "list_id"], ["saved_lists.workspace_id", "saved_lists.id"]
        ),
        sa.ForeignKeyConstraint(["workspace_id", "last_job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.UniqueConstraint("workspace_id", "list_id"),
        sa.CheckConstraint(
            "cadence_hours BETWEEN 1 AND 720 AND max_runs BETWEEN 1 AND 25 AND run_count BETWEEN 0 AND max_runs"
        ),
    )
    op.create_table(
        "scheduled_research_runs",
        *common(),
        sa.Column("schedule_id", UUID(as_uuid=False), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_id", UUID(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "schedule_id"],
            ["research_schedules.workspace_id", "research_schedules.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.UniqueConstraint("workspace_id", "schedule_id", "scheduled_for"),
    )
    op.create_index("research_schedule_due", "research_schedules", ["workspace_id", "next_due_at"])
    for name in ("research_schedules", "scheduled_research_runs"):
        op.execute(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON {name} TO skriller_app"
        )
        op.execute(
            f"CREATE POLICY owner_access ON {name} FOR ALL USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner') WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')"
        )
    op.execute("GRANT UPDATE ON research_schedules TO skriller_app")
    op.execute(
        "CREATE TRIGGER immutable_scheduled_run BEFORE UPDATE OR DELETE ON scheduled_research_runs FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change()"
    )


def downgrade():
    op.drop_table("scheduled_research_runs")
    op.drop_table("research_schedules")
