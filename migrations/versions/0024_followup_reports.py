"""Durable follow-up requests; reports store citation digests, never source excerpts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check "
        "CHECK(purpose IN ('research','planning','followup'))"
    )
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_stage_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_stage_check "
        "CHECK(stage IS NULL OR stage IN "
        "('planning','discovering','collecting','extracting','resolving','qualifying','reporting'))"
    )
    op.create_table(
        "followup_reports",
        sa.Column("workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("job_id", UUID(as_uuid=False), nullable=False),
        sa.Column("source_job_id", UUID(as_uuid=False), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("evidence_ids", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("citation_hashes", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("unknowns", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(["workspace_id", "source_job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]),
        sa.UniqueConstraint("workspace_id", "job_id"),
        sa.CheckConstraint("status IN ('pending','answered','unknown')"),
    )
    op.execute(
        "ALTER TABLE followup_reports ENABLE ROW LEVEL SECURITY; "
        "ALTER TABLE followup_reports FORCE ROW LEVEL SECURITY; "
        "GRANT SELECT,INSERT,UPDATE ON followup_reports TO skriller_app"
    )
    op.execute(
        "CREATE POLICY scoped_read ON followup_reports FOR SELECT "
        "USING(tenant_allowed(workspace_id))"
    )
    op.execute(
        "CREATE POLICY actor_insert ON followup_reports FOR INSERT "
        "WITH CHECK(tenant_allowed(workspace_id) AND "
        "created_by=current_setting('app.actor_id',true))"
    )
    op.execute(
        "CREATE POLICY actor_update ON followup_reports FOR UPDATE "
        "USING(tenant_allowed(workspace_id) AND ("
        "created_by=current_setting('app.actor_id',true) OR "
        "workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')) "
        "WITH CHECK(tenant_allowed(workspace_id) AND ("
        "created_by=current_setting('app.actor_id',true) OR "
        "workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'))"
    )


def downgrade():
    op.drop_table("followup_reports")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_stage_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_stage_check CHECK(stage IS NULL OR stage IN "
        "('planning','discovering','collecting','extracting','resolving','qualifying'))"
    )
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute("ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check CHECK(purpose IN ('research','planning'))")
