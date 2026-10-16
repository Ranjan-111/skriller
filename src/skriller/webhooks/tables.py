"""Tenant-owned opt-ins and durable at-least-once delivery records."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from skriller.db.schema import scoped
from skriller.lists import list_snapshots, saved_lists

endpoints = scoped(
    "webhook_endpoints",
    sa.Column("list_id", UUID(as_uuid=False), nullable=False),
    sa.Column("url", sa.String(2048), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("secret_ciphertext", sa.LargeBinary, nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "list_id"], [saved_lists.c.workspace_id, saved_lists.c.id]
        ),
    ),
)
deliveries = scoped(
    "webhook_deliveries",
    sa.Column("endpoint_id", UUID(as_uuid=False), nullable=False),
    sa.Column("snapshot_id", UUID(as_uuid=False), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("lease_token", UUID(as_uuid=False)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("last_code", sa.String(32)),
    sa.Column("delivered_at", sa.DateTime(timezone=True)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "endpoint_id"], [endpoints.c.workspace_id, endpoints.c.id]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"], [list_snapshots.c.workspace_id, list_snapshots.c.id]
        ),
        sa.UniqueConstraint("workspace_id", "endpoint_id", "snapshot_id"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5"),
        sa.CheckConstraint(
            "state IN ('pending','delivering','delivered','failed','cancelled','blocked')"
        ),
    ),
)
