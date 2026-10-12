"""Coupled usage reservation dimensions and reconciliation outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reservations",
        sa.Column("dimensions", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("reservations", sa.Column("actual_dimensions", sa.JSON))
    op.add_column("reservations", sa.Column("reconciliation_status", sa.String(16)))
    op.add_column("reservations", sa.Column("actual_cost_usd", sa.Numeric(20, 8)))
    op.create_check_constraint(
        "reservation_actual_cost_nonnegative",
        "reservations",
        "actual_cost_usd IS NULL OR actual_cost_usd >= 0",
    )
    op.create_check_constraint(
        "reservation_reconciliation_status",
        "reservations",
        "reconciliation_status IS NULL OR reconciliation_status IN ('estimated','confirmed','not_charged')",
    )


def downgrade():
    op.drop_constraint("reservation_reconciliation_status", "reservations")
    op.drop_constraint("reservation_actual_cost_nonnegative", "reservations")
    for name in ("actual_cost_usd", "reconciliation_status", "actual_dimensions", "dimensions"):
        op.drop_column("reservations", name)
