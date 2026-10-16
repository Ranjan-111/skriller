"""Pin scheduled research to an immutable user message, never a later follow-up."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_schedules", sa.Column("prompt_message_id", UUID(as_uuid=False)))
    op.create_foreign_key(
        "schedule_prompt_scope",
        "research_schedules",
        "messages",
        ["workspace_id", "prompt_message_id"],
        ["workspace_id", "id"],
    )
    # Earlier local schedules lack a reviewed objective; never infer one.
    op.execute(
        "UPDATE research_schedules SET enabled=false,last_reason='plan_requires_review',lease_token=NULL,lease_expires_at=NULL WHERE prompt_message_id IS NULL"
    )


def downgrade():
    op.drop_constraint("schedule_prompt_scope", "research_schedules", type_="foreignkey")
    op.drop_column("research_schedules", "prompt_message_id")
