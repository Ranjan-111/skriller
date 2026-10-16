"""Dedicated saved-evidence repair jobs use the existing tenant outbox/checkpoints."""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check "
        "CHECK(purpose IN ('research','planning','followup','template_repair'))"
    )


def downgrade():
    # Do not relabel existing repair jobs as ordinary research.
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check "
        "CHECK(purpose IN ('research','planning','followup'))"
    )
