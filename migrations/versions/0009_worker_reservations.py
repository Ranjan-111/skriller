"""Link attempt reservations and bounded replay references."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attempts", sa.Column("reservation_id", UUID(as_uuid=False)))
    op.add_column("attempts", sa.Column("result_entity_ids", sa.JSON))
    op.create_foreign_key(
        "attempt_reservation_scope",
        "attempts",
        "reservations",
        ["workspace_id", "reservation_id"],
        ["workspace_id", "id"],
    )


def downgrade():
    op.drop_constraint("attempt_reservation_scope", "attempts", type_="foreignkey")
    op.drop_column("attempts", "result_entity_ids")
    op.drop_column("attempts", "reservation_id")
