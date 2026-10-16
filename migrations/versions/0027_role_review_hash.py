"""Retain the exact source-context hash of an explicit owner role review."""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("role_history", sa.Column("review_hash", sa.String(64)))
    op.create_check_constraint(
        "role_review_hash", "role_history", "review_hash IS NULL OR review_hash ~ '^[0-9a-f]{64}$'"
    )


def downgrade():
    op.drop_constraint("role_review_hash", "role_history", type_="check")
    op.drop_column("role_history", "review_hash")
