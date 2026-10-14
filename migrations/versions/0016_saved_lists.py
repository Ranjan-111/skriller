"""Tenant saved lists and immutable snapshot revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("saved_lists", "list_snapshots"):
        common = [
            sa.Column(
                "workspace_id",
                UUID(as_uuid=False),
                sa.ForeignKey("workspaces.id"),
                primary_key=True,
            ),
            sa.Column("id", UUID(as_uuid=False), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("plan_id", UUID(as_uuid=False), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.ForeignKeyConstraint(
                ["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]
            ),
        ]
        columns = (
            [sa.Column("name", sa.String(120), nullable=False)]
            if name == "saved_lists"
            else [
                sa.Column("list_id", UUID(as_uuid=False), nullable=False),
                sa.Column("revision", sa.Integer, nullable=False),
                sa.Column("payload", sa.JSON, nullable=False),
                sa.ForeignKeyConstraint(
                    ["workspace_id", "list_id"], ["saved_lists.workspace_id", "saved_lists.id"]
                ),
                sa.UniqueConstraint("workspace_id", "list_id", "revision"),
                sa.CheckConstraint("revision>0"),
            ]
        )
        op.create_table(name, *common, *columns)
        op.execute(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON {name} TO skriller_app"
        )
        op.execute(
            f"CREATE POLICY scoped_read ON {name} FOR SELECT USING(tenant_allowed(workspace_id))"
        )
        op.execute(
            f"CREATE POLICY owner_insert ON {name} FOR INSERT WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner' AND created_by=current_setting('app.actor_id',true))"
        )
        op.execute(
            f"CREATE TRIGGER immutable_saved_record BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change()"
        )


def downgrade():
    op.drop_table("list_snapshots")
    op.drop_table("saved_lists")
