"""Workspace owner operation kill switches."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_switches",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("disabled", sa.Boolean, nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_id", "source", "operation"),
        sa.CheckConstraint("operation IN ('discover','read','analytics')"),
        sa.CheckConstraint(
            "source IN ('linkedin','reddit','web','github','rss','youtube','x','instagram','facebook')"
        ),
    )
    op.execute(
        "ALTER TABLE source_switches ENABLE ROW LEVEL SECURITY; ALTER TABLE source_switches FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT,UPDATE ON source_switches TO skriller_app"
    )
    op.execute(
        "CREATE POLICY scoped_read ON source_switches FOR SELECT USING(tenant_allowed(workspace_id))"
    )
    owner = "tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner' AND updated_by=current_setting('app.actor_id',true)"
    op.execute(f"CREATE POLICY owner_insert ON source_switches FOR INSERT WITH CHECK({owner})")
    op.execute(
        f"CREATE POLICY owner_update ON source_switches FOR UPDATE USING(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner') WITH CHECK({owner})"
    )


def downgrade():
    op.drop_table("source_switches")
