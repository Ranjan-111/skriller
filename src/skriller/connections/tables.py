"""Tenant-scoped credential envelopes and immutable metadata-only audits."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from skriller.db.schema import scoped

connections = scoped(
    "source_connections",
    sa.Column("source", sa.String(32), nullable=False),
    sa.Column("auth_kind", sa.String(16), nullable=False),
    sa.Column("scopes", sa.JSON, nullable=False),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    constraints=(
        sa.CheckConstraint("state IN ('active','expired','revoked')"),
        sa.CheckConstraint("auth_kind IN ('session','oauth','api_key')"),
    ),
)

secrets = scoped(
    "source_connection_secrets",
    sa.Column("connection_id", UUID(as_uuid=False), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.UniqueConstraint("workspace_id", "connection_id"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext) BETWEEN 17 AND 65552"),
    ),
)

connection_audit = scoped(
    "source_connection_audit",
    sa.Column("connection_id", UUID(as_uuid=False), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("action", sa.String(20), nullable=False),
    sa.Column("runner", sa.String(64)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["source_connections.workspace_id", "source_connections.id"],
        ),
        sa.CheckConstraint("action IN ('created','loaded','revoked','expired')"),
    ),
)
