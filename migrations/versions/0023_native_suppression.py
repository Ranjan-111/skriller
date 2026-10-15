"""Retain minimal native-identifier hashes when source URLs change."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "erasure_journal",
        sa.Column("native_hashes", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade():
    op.drop_column("erasure_journal", "native_hashes")
