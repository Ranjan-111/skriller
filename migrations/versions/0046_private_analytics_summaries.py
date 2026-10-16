"""Encrypted initiating-owner summary snapshots; wipe on grant invalidation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "youtube_analytics_summary_jobs",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("grant_id", sa.String(36), nullable=False),
        sa.Column("grant_version", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.ForeignKeyConstraint(["workspace_id", "id"], ["jobs.workspace_id", "jobs.id"]),
        sa.CheckConstraint("state IN ('queued','running','completed','failed','cancelled')"),
        sa.CheckConstraint("grant_version>0"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext)<=65536"),
    )
    op.execute("ALTER TABLE youtube_analytics_summary_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE youtube_analytics_summary_jobs FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE ON youtube_analytics_summary_jobs TO skriller_app")
    op.execute("""CREATE POLICY initiating_owner ON youtube_analytics_summary_jobs FOR ALL
        USING(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND created_by=current_setting('app.actor_id',true))
        WITH CHECK(tenant_allowed(workspace_id)
          AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'
          AND created_by=current_setting('app.actor_id',true))""")
    # SECURITY DEFINER is needed for expiry/restore invalidation across owners.
    # No arguments or callable function API; scope comes exclusively from NEW.
    op.execute("""CREATE FUNCTION wipe_analytics_summary_snapshots() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public SET row_security=off AS $$
      BEGIN
        IF NEW.state='revoked' OR NEW.version<>OLD.version THEN
          UPDATE public.youtube_analytics_summary_jobs SET ciphertext=''::bytea,state='cancelled'
          WHERE workspace_id=NEW.workspace_id AND grant_id=NEW.id::text;
        END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION wipe_analytics_summary_snapshots() FROM PUBLIC;
      CREATE TRIGGER analytics_summary_invalidation AFTER UPDATE ON youtube_analytics_grants
        FOR EACH ROW EXECUTE FUNCTION wipe_analytics_summary_snapshots()""")


def downgrade():
    op.execute("DROP TRIGGER analytics_summary_invalidation ON youtube_analytics_grants")
    op.execute("DROP FUNCTION wipe_analytics_summary_snapshots()")
    op.drop_table("youtube_analytics_summary_jobs")
