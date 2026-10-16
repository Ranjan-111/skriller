"""Distinct owner-only OAuth grants, never public-source connection references."""

import sqlalchemy as sa

from skriller.db.schema import scoped

grants = scoped(
    "youtube_analytics_grants",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("state_hash", sa.String(64)),
    sa.Column("configuration_hash", sa.String(64), nullable=False),
    sa.Column("channel_id", sa.String(64)),
    sa.Column("scopes", sa.JSON, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("access_expires_at", sa.DateTime(timezone=True)),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    constraints=(
        sa.CheckConstraint("state IN ('pending','exchanging','active','revoked')"),
        sa.CheckConstraint("version>0"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext)<=65536"),
    ),
)

summary_jobs = scoped(
    "youtube_analytics_summary_jobs",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("grant_id", sa.String(36), nullable=False),
    sa.Column("grant_version", sa.Integer, nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    constraints=(
        sa.CheckConstraint("state IN ('queued','running','completed','failed','cancelled')"),
        sa.CheckConstraint("grant_version>0"),
        sa.CheckConstraint("octet_length(nonce)=12"),
        sa.CheckConstraint("octet_length(ciphertext)<=65536"),
    ),
)
