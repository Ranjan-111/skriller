"""Allow removal of notification derivatives only under journalled owner erasure."""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT DELETE ON webhook_deliveries TO skriller_app")
    op.execute(
        "CREATE TRIGGER webhook_erasure_delete_guard BEFORE DELETE ON webhook_deliveries FOR EACH ROW EXECUTE FUNCTION require_erasure_delete()"
    )


def downgrade():
    op.execute("DROP TRIGGER webhook_erasure_delete_guard ON webhook_deliveries")
    op.execute("REVOKE DELETE ON webhook_deliveries FROM skriller_app")
