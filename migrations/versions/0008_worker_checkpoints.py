"""Generation-fenced stage checkpoints and independently audited external calls."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attempts", sa.Column("lease_owner", UUID(as_uuid=False)))
    op.add_column("attempts", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "attempts", sa.Column("generation", sa.Integer, nullable=False, server_default="0")
    )
    op.create_check_constraint("attempt_generation_nonnegative", "attempts", "generation >= 0")
    for table, extra, constraints in (
        (
            "stage_checkpoints",
            [
                sa.Column("stage", sa.String(64), nullable=False),
                sa.Column("result_refs", sa.JSON, nullable=False),
            ],
            [sa.UniqueConstraint("workspace_id", "attempt_id")],
        ),
        (
            "external_calls",
            [
                sa.Column("operation_key", sa.String(200), nullable=False),
                sa.Column("reservation_id", UUID(as_uuid=False), nullable=False),
                sa.Column("state", sa.String(16), nullable=False),
                sa.Column("finished_at", sa.DateTime(timezone=True)),
            ],
            [
                sa.UniqueConstraint("workspace_id", "attempt_id", "generation", "operation_key"),
                sa.ForeignKeyConstraint(
                    ["workspace_id", "reservation_id"],
                    ["reservations.workspace_id", "reservations.id"],
                ),
                sa.CheckConstraint("state IN ('in_flight','confirmed','uncertain')"),
            ],
        ),
    ):
        op.create_table(
            table,
            sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
            sa.Column("id", UUID(as_uuid=False), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("job_id", UUID(as_uuid=False), nullable=False),
            sa.Column("attempt_id", UUID(as_uuid=False), nullable=False),
            sa.Column("generation", sa.Integer, nullable=False),
            *extra,
            sa.PrimaryKeyConstraint("workspace_id", "id"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.ForeignKeyConstraint(
                ["workspace_id", "job_id", "attempt_id"],
                ["attempts.workspace_id", "attempts.job_id", "attempts.id"],
            ),
            sa.CheckConstraint("generation > 0"),
            *constraints,
        )
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table} FORCE ROW LEVEL SECURITY; CREATE POLICY tenant ON {table} USING(tenant_allowed(workspace_id)) WITH CHECK(tenant_allowed(workspace_id)); GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO skriller_app"
        )
    op.execute(
        "CREATE TRIGGER immutable_stage_checkpoints BEFORE UPDATE OR DELETE ON stage_checkpoints FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change()"
    )


def downgrade():
    op.drop_table("external_calls")
    op.drop_table("stage_checkpoints")
    op.drop_constraint("attempt_generation_nonnegative", "attempts")
    for name in ("generation", "lease_expires_at", "lease_owner"):
        op.drop_column("attempts", name)
