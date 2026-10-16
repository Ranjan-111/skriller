"""Database-owned admission timestamps protect monthly quota accounting."""

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION enforce_admission_timestamp() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
      BEGIN
        NEW.admitted_at := clock_timestamp();
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION enforce_admission_timestamp() FROM PUBLIC;
      CREATE TRIGGER aa_admission_timestamp BEFORE INSERT ON entitlement_admissions
        FOR EACH ROW EXECUTE FUNCTION enforce_admission_timestamp()""")


def downgrade():
    op.execute("DROP TRIGGER aa_admission_timestamp ON entitlement_admissions")
    op.execute("DROP FUNCTION enforce_admission_timestamp()")
