"""Append-only evidence-dated role supersession."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "role_history",
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        *[
            sa.Column(name, UUID(as_uuid=False), nullable=False)
            for name in (
                "previous_id",
                "replacement_id",
                "previous_date_id",
                "replacement_date_id",
                "previous_evidence_id",
                "replacement_evidence_id",
            )
        ],
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.CheckConstraint("previous_id<>replacement_id"),
        sa.UniqueConstraint("workspace_id", "previous_id", "replacement_id"),
        *[
            sa.ForeignKeyConstraint(["workspace_id", name], ["claims.workspace_id", "claims.id"])
            for name in ("previous_id", "replacement_id", "previous_date_id", "replacement_date_id")
        ],
        *[
            sa.ForeignKeyConstraint(
                ["workspace_id", name], ["evidence.workspace_id", "evidence.id"]
            )
            for name in ("previous_evidence_id", "replacement_evidence_id")
        ],
    )
    op.execute(
        "ALTER TABLE role_history ENABLE ROW LEVEL SECURITY; ALTER TABLE role_history FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON role_history TO skriller_app"
    )
    op.execute(
        "CREATE POLICY scoped_read ON role_history FOR SELECT USING(tenant_allowed(workspace_id))"
    )
    op.execute(
        "CREATE POLICY scoped_insert ON role_history FOR INSERT WITH CHECK(tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true))"
    )
    op.execute(
        "CREATE TRIGGER immutable_role_history BEFORE UPDATE OR DELETE ON role_history FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change()"
    )


def downgrade():
    op.drop_table("role_history")
