"""Route owner-private analytics summaries through existing opaque job outbox."""

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check CHECK(purpose IN ('research','planning','followup','template_repair','owner_summary'))"
    )


def downgrade():
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_purpose_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_purpose_check CHECK(purpose IN ('research','planning','followup','template_repair'))"
    )
