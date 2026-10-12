"""Plan revision links must preserve contiguous conversation history."""

from alembic import op

revision = "0002a"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
ALTER TABLE plans ADD CONSTRAINT revision_parent_shape CHECK(
 (revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL AND parent_id<>id));
CREATE FUNCTION validate_plan_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE latest_id uuid; latest_revision integer;
BEGIN
 PERFORM id FROM conversations WHERE workspace_id=NEW.workspace_id AND id=NEW.conversation_id FOR UPDATE;
 SELECT id,revision INTO latest_id,latest_revision FROM plans
 WHERE workspace_id=NEW.workspace_id AND conversation_id=NEW.conversation_id ORDER BY revision DESC LIMIT 1;
 IF NEW.revision<>coalesce(latest_revision,0)+1 OR NEW.parent_id IS DISTINCT FROM latest_id THEN
   RAISE EXCEPTION 'Plan revision must append to latest conversation plan';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION validate_plan_revision() FROM PUBLIC;
CREATE TRIGGER plan_revision_history BEFORE INSERT ON plans
 FOR EACH ROW EXECUTE FUNCTION validate_plan_revision();
""")


def downgrade():
    op.execute(
        "DROP TRIGGER plan_revision_history ON plans; DROP FUNCTION validate_plan_revision(); "
        "ALTER TABLE plans DROP CONSTRAINT revision_parent_shape;"
    )
