"""Durable per-workspace retention schedule with bounded service claiming."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE evidence SET expires_at=collected_at + CASE
        WHEN source_platform='skriller_export' THEN interval '1 hour'
        WHEN source_platform IN ('web','github','youtube') THEN interval '30 days'
        ELSE interval '7 days' END WHERE expires_at IS NULL""")
    op.create_table(
        "retention_schedules",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column(
            "next_due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("lease_token", UUID(as_uuid=False)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "ALTER TABLE retention_schedules ENABLE ROW LEVEL SECURITY; ALTER TABLE retention_schedules FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT,UPDATE ON retention_schedules TO skriller_app"
    )
    op.execute(
        "CREATE POLICY scoped_read ON retention_schedules FOR SELECT USING(tenant_allowed(workspace_id))"
    )
    op.execute(
        "CREATE POLICY scoped_write ON retention_schedules FOR ALL USING(tenant_allowed(workspace_id)) WITH CHECK(tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true))"
    )
    op.execute("""CREATE FUNCTION claim_due_retention(batch_limit integer) RETURNS TABLE(workspace_id uuid,actor_id varchar,lease_token uuid)
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ BEGIN
        IF batch_limit<1 OR batch_limit>100 THEN RAISE EXCEPTION 'Invalid retention batch'; END IF;
        RETURN QUERY WITH due AS (
          SELECT r.workspace_id FROM retention_schedules r
          WHERE r.next_due_at<=clock_timestamp() AND (r.lease_expires_at IS NULL OR r.lease_expires_at<=clock_timestamp())
          AND EXISTS(SELECT 1 FROM memberships m WHERE m.workspace_id=r.workspace_id AND m.actor_id=r.actor_id)
          ORDER BY r.next_due_at,r.workspace_id LIMIT batch_limit FOR UPDATE SKIP LOCKED
        ) UPDATE retention_schedules r SET lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '60 seconds'
          FROM due WHERE r.workspace_id=due.workspace_id RETURNING r.workspace_id,r.actor_id,r.lease_token;
      END $$;
      REVOKE ALL ON FUNCTION claim_due_retention(integer) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION claim_due_retention(integer) TO skriller_app""")


def downgrade():
    op.execute("DROP FUNCTION claim_due_retention(integer)")
    op.drop_table("retention_schedules")
