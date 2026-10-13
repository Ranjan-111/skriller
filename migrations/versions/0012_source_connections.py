"""Encrypted scoped source credentials; no raw credentials in public metadata."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def columns():
    return [
        sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    ]


def upgrade():
    op.create_table(
        "source_connections",
        *columns(),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("auth_kind", sa.String(16), nullable=False),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('active','expired','revoked')"),
        sa.CheckConstraint("auth_kind IN ('session','oauth','api_key')"),
    )
    op.create_table(
        "source_connection_secrets",
        *columns(),
        sa.Column("connection_id", UUID(as_uuid=False), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.UniqueConstraint("workspace_id", "connection_id"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext) BETWEEN 17 AND 65552"),
    )
    op.create_table(
        "source_connection_audit",
        *columns(),
        sa.Column("connection_id", UUID(as_uuid=False), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("runner", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.CheckConstraint("action IN ('created','loaded','revoked','expired')"),
    )
    for table in ("source_connections", "source_connection_secrets", "source_connection_audit"):
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table} FORCE ROW LEVEL SECURITY; GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO skriller_app"
        )
        op.execute(
            f"CREATE POLICY scoped_read ON {table} FOR SELECT USING(tenant_allowed(workspace_id))"
        )
    owner = "tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner'"
    for table in ("source_connections", "source_connection_secrets"):
        op.execute(f"CREATE POLICY owner_insert ON {table} FOR INSERT WITH CHECK({owner})")
        op.execute(
            f"CREATE POLICY owner_update ON {table} FOR UPDATE USING({owner}) WITH CHECK({owner})"
        )
        op.execute(f"CREATE POLICY owner_delete ON {table} FOR DELETE USING({owner})")
    op.execute(
        f"CREATE POLICY audited_insert ON source_connection_audit FOR INSERT WITH CHECK(tenant_allowed(workspace_id) AND actor_id=current_setting('app.actor_id',true) AND (action='loaded' OR ({owner})))"
    )
    op.execute(
        "CREATE TRIGGER immutable_connection_audit BEFORE UPDATE OR DELETE ON source_connection_audit FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change()"
    )


def downgrade():
    for table in ("source_connection_audit", "source_connection_secrets", "source_connections"):
        op.drop_table(table)
