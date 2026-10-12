"""Tenant/source/access/template version scoped adaptive parser fingerprints."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "adaptive_fingerprints",
        sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
        sa.Column("id", UUID(as_uuid=False), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("access_scope", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("template_id", UUID(as_uuid=False), nullable=False),
        sa.Column("template_version", sa.Integer, nullable=False),
        sa.Column("selector_identifier", sa.Text, nullable=False),
        sa.Column(
            "selector_hash", sa.String(32), sa.Computed("md5(selector_identifier)", persisted=True)
        ),
        sa.Column("element_data", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint(
            "workspace_id",
            "source",
            "access_scope",
            "domain",
            "template_id",
            "template_version",
            "selector_hash",
            name="adaptive_namespace",
        ),
        sa.CheckConstraint(
            "source IN ('linkedin','reddit','web','github','rss','youtube','x','instagram','facebook')"
        ),
        sa.CheckConstraint(
            "access_scope='public' OR access_scope ~ '^connection:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
        ),
        sa.CheckConstraint("length(domain) BETWEEN 1 AND 253"),
        sa.CheckConstraint("template_version > 0"),
        sa.CheckConstraint("length(selector_identifier) BETWEEN 1 AND 4096"),
    )
    op.execute("""
        ALTER TABLE adaptive_fingerprints ENABLE ROW LEVEL SECURITY;
        ALTER TABLE adaptive_fingerprints FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant ON adaptive_fingerprints
        USING(tenant_allowed(workspace_id)) WITH CHECK(tenant_allowed(workspace_id));
        GRANT SELECT,INSERT,UPDATE,DELETE ON adaptive_fingerprints TO skriller_app;
    """)


def downgrade():
    op.drop_table("adaptive_fingerprints")
