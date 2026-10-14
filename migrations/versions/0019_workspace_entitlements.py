"""Bounded trial/pilot policies and immutable job admission accounting."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_entitlements",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("tier", sa.String(16), nullable=False, server_default="trial"),
        sa.Column("run_limit", sa.Integer, nullable=False, server_default="25"),
        sa.Column("result_cap", sa.Integer, nullable=False, server_default="25"),
        sa.Column("source_cap", sa.Integer, nullable=False, server_default="3"),
        sa.Column("result_limit", sa.Integer, nullable=False, server_default="25"),
        sa.Column("source_limit", sa.Integer, nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("invoice_reference", sa.String(120)),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.CheckConstraint("tier IN ('trial','pilot')"),
        sa.CheckConstraint(
            "run_limit BETWEEN 0 AND 1000 AND result_cap BETWEEN 1 AND 100 AND source_cap BETWEEN 1 AND 9"
        ),
        sa.CheckConstraint(
            "result_limit BETWEEN 1 AND result_cap AND source_limit BETWEEN 1 AND source_cap"
        ),
        sa.CheckConstraint(
            "(tier='trial' AND run_limit<=25 AND result_cap<=25 AND source_cap<=3 AND invoice_reference IS NULL) OR (tier='pilot' AND length(trim(invoice_reference)) BETWEEN 1 AND 120)"
        ),
    )
    op.create_table(
        "entitlement_admissions",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column(
            "admitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
    )
    op.add_column("outbox", sa.Column("discarded_at", sa.DateTime(timezone=True)))
    for table in ("workspace_entitlements", "entitlement_admissions"):
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table} FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON {table} TO skriller_app"
        )
        op.execute(
            f"CREATE POLICY scoped_read ON {table} FOR SELECT USING(tenant_allowed(workspace_id))"
        )
    op.execute("""CREATE POLICY trial_insert ON workspace_entitlements FOR INSERT WITH CHECK(
        tenant_allowed(workspace_id) AND tier='trial' AND run_limit=25 AND result_cap=25 AND source_cap=3
        AND result_limit=25 AND source_limit=3 AND enabled AND invoice_reference IS NULL
        AND updated_by=current_setting('app.actor_id',true))""")
    op.execute(
        "GRANT UPDATE(enabled,result_limit,source_limit,updated_by) ON workspace_entitlements TO skriller_app"
    )
    op.execute("""CREATE POLICY owner_update ON workspace_entitlements FOR UPDATE
        USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')
        WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
        AND updated_by=current_setting('app.actor_id',true))""")
    op.execute("""CREATE POLICY scoped_admit ON entitlement_admissions FOR INSERT WITH CHECK(
        tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true))""")
    op.execute("""CREATE FUNCTION enforce_entitlement_admission() RETURNS trigger LANGUAGE plpgsql
        SECURITY DEFINER SET search_path=pg_catalog,public AS $$ DECLARE policy record; used integer;
        BEGIN
          IF NOT tenant_allowed(NEW.workspace_id) OR NEW.actor_id<>current_setting('app.actor_id',true)
          THEN RAISE EXCEPTION 'Admission unavailable' USING ERRCODE='42501'; END IF;
          SELECT * INTO policy FROM workspace_entitlements WHERE workspace_id=NEW.workspace_id FOR UPDATE;
          IF NOT FOUND OR NOT policy.enabled THEN RAISE EXCEPTION 'Execution unavailable' USING ERRCODE='42501'; END IF;
          SELECT count(*) INTO used FROM entitlement_admissions WHERE workspace_id=NEW.workspace_id;
          IF used>=policy.run_limit THEN RAISE EXCEPTION 'Workspace run quota exhausted' USING ERRCODE='42501'; END IF;
          RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION enforce_entitlement_admission() FROM PUBLIC;
        CREATE TRIGGER bounded_admission BEFORE INSERT ON entitlement_admissions FOR EACH ROW EXECUTE FUNCTION enforce_entitlement_admission()""")


def downgrade():
    op.drop_table("entitlement_admissions")
    op.execute("DROP FUNCTION enforce_entitlement_admission()")
    op.drop_table("workspace_entitlements")
    op.drop_column("outbox", "discarded_at")
