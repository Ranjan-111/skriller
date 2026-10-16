"""Durable payment-event inbox with no tenant application privileges."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_event_inbox",
        sa.Column("provider", sa.String(16), primary_key=True),
        sa.Column("account_scope", sa.String(192), primary_key=True),
        sa.Column("event_key", sa.String(192), primary_key=True),
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("subscription_id", sa.String(192), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("provider IN ('stripe','razorpay')"),
        sa.CheckConstraint("state IN ('pending','reconciled','quarantined')"),
    )
    op.execute("REVOKE ALL ON billing_event_inbox FROM PUBLIC, skriller_app")


def downgrade():
    op.drop_table("billing_event_inbox")
