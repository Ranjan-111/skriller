"""One-use tenant/job/request/credential-bound Reddit pagination."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reddit_search_continuations",
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("job_id", UUID(as_uuid=False), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=False), nullable=False),
        sa.Column("credential_id", UUID(as_uuid=False), nullable=False),
        sa.Column("plan_revision", sa.Integer, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("after", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "credential_id"],
            ["source_connection_secrets.workspace_id", "source_connection_secrets.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('ready','consumed') AND plan_revision>0 AND length(request_hash)=64"
        ),
        sa.CheckConstraint("after ~ '^t3_[a-z0-9]{3,13}$'"),
        sa.UniqueConstraint("workspace_id", "job_id", "credential_id", "request_hash", "after"),
    )
    op.execute("ALTER TABLE reddit_search_continuations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reddit_search_continuations FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON reddit_search_continuations TO skriller_app")
    op.execute("""CREATE POLICY job_actor ON reddit_search_continuations FOR ALL
      USING(tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true))
      WITH CHECK(tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true))""")


def downgrade():
    op.drop_table("reddit_search_continuations")
