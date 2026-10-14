"""Owner reviewed reversible identity links and append-only audit events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("identity_reviews", "identity_events"):
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
        ]
        if name == "identity_reviews":
            columns = [
                sa.Column("source_id", UUID(as_uuid=False), nullable=False),
                sa.Column("target_id", UUID(as_uuid=False), nullable=False),
                sa.Column("state", sa.String(16), nullable=False),
                sa.Column("reason", sa.String(64), nullable=False),
                sa.Column("created_by", sa.String(128), nullable=False),
                sa.Column("reviewed_by", sa.String(128)),
                sa.CheckConstraint("state IN ('suggestion','linked','reversed')"),
                sa.CheckConstraint("source_id<>target_id"),
                sa.ForeignKeyConstraint(
                    ["workspace_id", "source_id"], ["entities.workspace_id", "entities.id"]
                ),
                sa.ForeignKeyConstraint(
                    ["workspace_id", "target_id"], ["entities.workspace_id", "entities.id"]
                ),
            ]
        else:
            columns = [
                sa.Column("review_id", UUID(as_uuid=False), nullable=False),
                sa.Column("action", sa.String(16), nullable=False),
                sa.Column("actor_id", sa.String(128), nullable=False),
                sa.Column("reason", sa.String(64), nullable=False),
                sa.ForeignKeyConstraint(
                    ["workspace_id", "review_id"],
                    ["identity_reviews.workspace_id", "identity_reviews.id"],
                ),
            ]
        op.create_table(name, *common, *columns)
        op.execute(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {name} FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT ON {name} TO skriller_app"
        )
        op.execute(
            f"CREATE POLICY scoped_read ON {name} FOR SELECT USING(tenant_allowed(workspace_id))"
        )
        actor_column = "created_by" if name == "identity_reviews" else "actor_id"
        owner = "tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'"
        op.execute(
            f"CREATE POLICY owner_insert ON {name} FOR INSERT WITH CHECK({owner} AND {actor_column}=current_setting('app.actor_id',true))"
        )
        if name == "identity_reviews":
            op.execute(f"GRANT UPDATE ON {name} TO skriller_app")
            op.execute(
                f"CREATE POLICY owner_update ON {name} FOR UPDATE USING({owner}) WITH CHECK({owner} AND reviewed_by=current_setting('app.actor_id',true))"
            )


def downgrade():
    op.drop_table("identity_events")
    op.drop_table("identity_reviews")
