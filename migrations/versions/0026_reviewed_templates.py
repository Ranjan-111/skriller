"""Immutable reviewed mappings and owner-controlled active selection."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    def scoped_columns():
        return [
            sa.Column(
                "workspace_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("workspaces.id"),
                primary_key=True,
            ),
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ]

    op.create_table(
        "reviewed_template_versions",
        *scoped_columns(),
        sa.Column("template_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("template_version", sa.Integer, nullable=False),
        sa.Column("source_url", sa.String(4096), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint("workspace_id", "template_id", "template_version"),
        sa.CheckConstraint("template_version BETWEEN 1 AND 1000000"),
    )
    op.create_table(
        "active_page_templates",
        *scoped_columns(),
        sa.Column("version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "version_id"],
            ["reviewed_template_versions.workspace_id", "reviewed_template_versions.id"],
        ),
    )
    op.create_table(
        "page_template_audit",
        *scoped_columns(),
        sa.Column("template_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("previous_version", sa.Integer),
        sa.Column("selected_version", sa.Integer, nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint("action IN ('publish','rollback')"),
    )
    for name in ("reviewed_template_versions", "active_page_templates", "page_template_audit"):
        op.execute(sa.text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"GRANT SELECT,INSERT ON {name} TO skriller_app"))
        op.execute(
            sa.text(
                f"CREATE POLICY scoped_read ON {name} FOR SELECT USING(tenant_allowed(workspace_id))"
            )
        )
        owner = (
            f"tenant_allowed({name}.workspace_id) AND EXISTS(SELECT 1 FROM memberships m "
            f"WHERE m.workspace_id={name}.workspace_id AND m.actor_id=current_setting('app.actor_id',true) "
            "AND m.role='owner')"
        )
        actor_column = "updated_by" if name == "active_page_templates" else "created_by"
        owner += f" AND {actor_column}=current_setting('app.actor_id',true)"
        op.execute(sa.text(f"CREATE POLICY owner_insert ON {name} FOR INSERT WITH CHECK({owner})"))
        if name == "active_page_templates":
            op.execute(sa.text(f"GRANT UPDATE ON {name} TO skriller_app"))
            op.execute(
                sa.text(
                    f"CREATE POLICY owner_update ON {name} FOR UPDATE USING(tenant_allowed(workspace_id) AND EXISTS(SELECT 1 FROM memberships m WHERE m.workspace_id={name}.workspace_id AND m.actor_id=current_setting('app.actor_id',true) AND m.role='owner')) WITH CHECK({owner})"
                )
            )


def downgrade():
    for name in ("page_template_audit", "active_page_templates", "reviewed_template_versions"):
        op.drop_table(name)
