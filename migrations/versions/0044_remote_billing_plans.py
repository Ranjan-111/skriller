"""Durable approved-catalog provider creation receipts and uncertain writes."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_remote_plans",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("account_scope", sa.String(192), primary_key=True),
        sa.Column("slug", sa.String(16), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("remote_id", sa.String(192)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("state IN ('dispatching','ready','uncertain')"),
    )
    op.execute("REVOKE ALL ON billing_remote_plans FROM PUBLIC,skriller_app")


def downgrade():
    op.drop_table("billing_remote_plans")
