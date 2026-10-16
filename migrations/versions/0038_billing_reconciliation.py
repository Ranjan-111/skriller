"""Operator-only immutable subscription reconciliation audit."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_reconciliations",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("event_key", sa.String(192), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("access_enabled", sa.Boolean, nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("plan_id", sa.String(192), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("REVOKE ALL ON billing_reconciliations FROM PUBLIC,skriller_app")


def downgrade():
    op.drop_table("billing_reconciliations")
