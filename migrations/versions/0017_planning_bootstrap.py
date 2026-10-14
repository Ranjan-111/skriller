"""Durable planning purpose and explicit stage."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE jobs ADD COLUMN purpose varchar(16) NOT NULL DEFAULT 'research' CHECK(purpose IN ('research','planning'))"
    )
    op.execute("""DO $$ DECLARE constraint_name text; BEGIN
      SELECT conname INTO constraint_name FROM pg_constraint
      WHERE conrelid='jobs'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%stage%';
      EXECUTE format('ALTER TABLE jobs DROP CONSTRAINT %I',constraint_name);
      ALTER TABLE jobs ADD CONSTRAINT jobs_stage_check CHECK(stage IS NULL OR stage IN ('planning','discovering','collecting','extracting','resolving','qualifying'));
    END $$""")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM jobs WHERE stage='planning') THEN
      RAISE EXCEPTION 'Cannot downgrade with planning jobs'; END IF; END $$""")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_stage_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_stage_check CHECK(stage IS NULL OR stage IN ('discovering','collecting','extracting','resolving','qualifying'))"
    )
    op.execute("ALTER TABLE jobs DROP COLUMN purpose")
