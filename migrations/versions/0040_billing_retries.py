"""Durable finite billing read attempts and retry backoff."""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "billing_event_inbox",
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_event_inbox",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "billing_attempt_bounds", "billing_event_inbox", "attempt_count BETWEEN 0 AND 5"
    )
    op.create_index(
        "billing_pending_workspace",
        "billing_event_inbox",
        ["workspace_id", "state", "next_attempt_at"],
    )


def downgrade():
    op.drop_index("billing_pending_workspace", table_name="billing_event_inbox")
    op.drop_constraint("billing_attempt_bounds", "billing_event_inbox")
    op.drop_column("billing_event_inbox", "next_attempt_at")
    op.drop_column("billing_event_inbox", "attempt_count")
