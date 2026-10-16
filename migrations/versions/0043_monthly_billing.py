"""Verified provider billing windows, preserving immutable historical admissions."""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def _admission(count):
    op.execute(
        """CREATE OR REPLACE FUNCTION enforce_entitlement_admission() RETURNS trigger LANGUAGE plpgsql
        SECURITY DEFINER SET search_path=pg_catalog,public AS $$ DECLARE policy record; used integer;
        BEGIN
          IF NOT tenant_allowed(NEW.workspace_id) OR NEW.actor_id<>current_setting('app.actor_id',true)
          THEN RAISE EXCEPTION 'Admission unavailable' USING ERRCODE='42501'; END IF;
          SELECT * INTO policy FROM workspace_entitlements WHERE workspace_id=NEW.workspace_id FOR UPDATE;
          IF NOT FOUND OR NOT policy.enabled THEN RAISE EXCEPTION 'Execution unavailable' USING ERRCODE='42501'; END IF;
          """
        + count
        + """
          IF used>=policy.run_limit THEN RAISE EXCEPTION 'Workspace run quota exhausted' USING ERRCODE='42501'; END IF;
          RETURN NEW;
        END $$"""
    )


def upgrade():
    op.add_column("billing_bindings", sa.Column("period_start", sa.DateTime(timezone=True)))
    op.add_column("billing_bindings", sa.Column("period_end", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "billing_window_bounds",
        "billing_bindings",
        "(period_start IS NULL AND period_end IS NULL) OR (period_start IS NOT NULL AND period_end IS NOT NULL AND period_start<period_end)",
    )
    op.add_column(
        "billing_workspace_catalog",
        sa.Column("monthly", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column("billing_reconciliations", sa.Column("allowance", sa.JSON))
    op.execute("""CREATE FUNCTION entitlement_used_runs(workspace uuid) RETURNS bigint
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE window_start timestamptz; window_end timestamptz; total bigint;
      BEGIN
        IF NOT public.tenant_allowed(workspace) THEN
          RAISE EXCEPTION 'Workspace unavailable' USING ERRCODE='42501'; END IF;
        SELECT period_start,period_end INTO window_start,window_end FROM public.billing_bindings
          WHERE workspace_id=workspace;
        SELECT count(*) INTO total FROM public.entitlement_admissions
          WHERE workspace_id=workspace AND (window_start IS NULL OR
            (admitted_at>=window_start AND admitted_at<window_end));
        RETURN total;
      END $$;
      REVOKE ALL ON FUNCTION entitlement_used_runs(uuid) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION entitlement_used_runs(uuid) TO skriller_app""")
    _admission("used := public.entitlement_used_runs(NEW.workspace_id);")


def downgrade():
    _admission(
        "SELECT count(*) INTO used FROM entitlement_admissions WHERE workspace_id=NEW.workspace_id;"
    )
    op.execute("DROP FUNCTION entitlement_used_runs(uuid)")
    op.drop_column("billing_reconciliations", "allowance")
    op.drop_column("billing_workspace_catalog", "monthly")
    op.drop_constraint("billing_window_bounds", "billing_bindings")
    op.drop_column("billing_bindings", "period_end")
    op.drop_column("billing_bindings", "period_start")
