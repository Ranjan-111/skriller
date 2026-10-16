"""Persist finite reviewed per-workspace billing catalog inputs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_workspace_catalog",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=False),
            sa.ForeignKey("billing_bindings.workspace_id"),
            primary_key=True,
        ),
        sa.Column("customer_id", sa.String(192), nullable=False),
        sa.Column("plan_id", sa.String(192), nullable=False),
        sa.Column("runs", sa.Integer, nullable=False),
        sa.Column("results", sa.Integer, nullable=False),
        sa.Column("sources", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "runs BETWEEN 1 AND 1000 AND results BETWEEN 1 AND 100 AND sources BETWEEN 1 AND 9"
        ),
    )
    op.execute("REVOKE ALL ON billing_workspace_catalog FROM PUBLIC,skriller_app")


def downgrade():
    op.drop_table("billing_workspace_catalog")
