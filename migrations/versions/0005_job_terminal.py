"""Canonical terminal reasons and database terminal-state protection."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE jobs ADD COLUMN terminal_reason VARCHAR(64)")
    op.execute("""
        UPDATE jobs SET terminal_reason=CASE state
            WHEN 'completed' THEN 'source_exhausted' WHEN 'partial' THEN 'source_interrupted'
            WHEN 'failed' THEN 'processing_error' WHEN 'cancelled' THEN 'user_cancelled' END
        WHERE state IN ('completed','partial','failed','cancelled');
        ALTER TABLE jobs ADD CONSTRAINT terminal_reason_consistent CHECK (
            (state='completed' AND terminal_reason IN ('source_exhausted','target_met')) OR
            (state='partial' AND terminal_reason IN
                ('budget_limit','deadline_limit','source_interrupted')) OR
            (state='failed' AND terminal_reason IN
                ('budget_limit','deadline_limit','source_interrupted','processing_error')) OR
            (state='cancelled' AND terminal_reason='user_cancelled') OR
            (state NOT IN ('completed','partial','failed','cancelled') AND terminal_reason IS NULL)
        );
        ALTER TABLE jobs ADD CONSTRAINT terminal_reason_required CHECK (
            (state IN ('completed','partial','failed','cancelled')) = (terminal_reason IS NOT NULL)
        );
        CREATE FUNCTION protect_terminal_job() RETURNS trigger
        LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF OLD.state IN ('completed','partial','failed','cancelled') AND
            (NEW.state IS DISTINCT FROM OLD.state OR
             NEW.stage IS DISTINCT FROM OLD.stage OR
             NEW.terminal_reason IS DISTINCT FROM OLD.terminal_reason OR
             NEW.completed_at IS DISTINCT FROM OLD.completed_at OR
             NEW.failure_code IS DISTINCT FROM OLD.failure_code OR
             NEW.version IS DISTINCT FROM OLD.version) THEN
            RAISE EXCEPTION 'Terminal job cannot restart or change outcome';
          END IF;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION protect_terminal_job() FROM PUBLIC;
        CREATE TRIGGER protect_terminal_job BEFORE UPDATE ON jobs
        FOR EACH ROW EXECUTE FUNCTION protect_terminal_job();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER protect_terminal_job ON jobs;
        DROP FUNCTION protect_terminal_job();
        ALTER TABLE jobs DROP CONSTRAINT terminal_reason_consistent;
        ALTER TABLE jobs DROP CONSTRAINT terminal_reason_required;
        ALTER TABLE jobs DROP COLUMN terminal_reason;
    """)
