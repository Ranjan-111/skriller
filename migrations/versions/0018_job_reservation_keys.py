"""Scope operation reservations to their job without rewriting existing usage."""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""DO $$ DECLARE old_name text; BEGIN
      SELECT c.conname INTO STRICT old_name FROM pg_constraint c
      WHERE c.conrelid='reservations'::regclass AND c.contype='u'
        AND (SELECT array_agg(a.attname::text ORDER BY k.ordinality)
             FROM unnest(c.conkey) WITH ORDINALITY k(attnum,ordinality)
             JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum)
            = ARRAY['workspace_id','idempotency_key'];
      EXECUTE format('ALTER TABLE reservations DROP CONSTRAINT %I',old_name);
      ALTER TABLE reservations ADD CONSTRAINT reservations_job_operation_key
        UNIQUE(workspace_id,job_id,idempotency_key);
    END $$""")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM reservations GROUP BY workspace_id,idempotency_key HAVING count(*)>1)
      THEN RAISE EXCEPTION 'Cannot restore workspace-wide keys with independent job operations'; END IF;
    END $$""")
    op.execute("ALTER TABLE reservations DROP CONSTRAINT reservations_job_operation_key")
    op.execute("ALTER TABLE reservations ADD UNIQUE(workspace_id,idempotency_key)")
