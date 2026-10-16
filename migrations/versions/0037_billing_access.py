"""Enforce operator-owned billing access independently of tenant owner settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_bindings",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("account_scope", sa.String(192), nullable=False),
        sa.Column("subscription_id", sa.String(192), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("provider", "account_scope", "subscription_id"),
        sa.CheckConstraint("provider IN ('stripe','razorpay')"),
        sa.CheckConstraint("NOT enabled OR valid_until IS NOT NULL"),
    )
    op.execute("REVOKE ALL ON billing_bindings FROM PUBLIC,skriller_app")
    op.execute("""CREATE FUNCTION billing_access_allowed(workspace uuid) RETURNS boolean
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE binding record;
      BEGIN
        IF NOT public.tenant_allowed(workspace) THEN RETURN false; END IF;
        SELECT enabled,valid_until INTO binding FROM public.billing_bindings
          WHERE workspace_id=workspace;
        IF NOT FOUND THEN RETURN true; END IF;
        RETURN binding.enabled AND binding.valid_until>clock_timestamp();
      END $$;
      REVOKE ALL ON FUNCTION billing_access_allowed(uuid) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION billing_access_allowed(uuid) TO skriller_app""")
    op.execute("""CREATE FUNCTION enforce_billing_admission() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      BEGIN
        -- bounded_admission runs first and locks the policy row. Billing writes
        -- lock that same row before modifying the binding.
        IF NOT public.billing_access_allowed(NEW.workspace_id) THEN
          RAISE EXCEPTION 'Billing access unavailable' USING ERRCODE='42501';
        END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION enforce_billing_admission() FROM PUBLIC;
      CREATE TRIGGER zz_billing_admission BEFORE INSERT ON entitlement_admissions
        FOR EACH ROW EXECUTE FUNCTION enforce_billing_admission()""")


def downgrade():
    op.execute("DROP TRIGGER zz_billing_admission ON entitlement_admissions")
    op.execute("DROP FUNCTION enforce_billing_admission()")
    op.execute("DROP FUNCTION billing_access_allowed(uuid)")
    op.drop_table("billing_bindings")
