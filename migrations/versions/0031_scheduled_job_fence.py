"""Retain scheduled provenance on jobs even when RLS hides a revoked opt-in."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("schedule_id", UUID(as_uuid=False)))
    op.create_foreign_key(
        "job_schedule_scope",
        "jobs",
        "research_schedules",
        ["workspace_id", "schedule_id"],
        ["workspace_id", "id"],
    )


def downgrade():
    op.drop_constraint("job_schedule_scope", "jobs", type_="foreignkey")
    op.drop_column("jobs", "schedule_id")
