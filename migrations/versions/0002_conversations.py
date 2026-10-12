"""Immutable conversation messages and request plan revisions."""

from alembic import op

revision = "0002"
down_revision = "0001a"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE conversations (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(),
 created_at timestamptz NOT NULL DEFAULT now(), title varchar(200) NOT NULL,
 created_by varchar(128) NOT NULL, PRIMARY KEY(workspace_id,id)
);
CREATE TABLE messages (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(),
 created_at timestamptz NOT NULL DEFAULT now(), conversation_id uuid NOT NULL,
 role varchar(16) NOT NULL CHECK(role IN ('user','assistant','system')), content text NOT NULL,
 sequence integer NOT NULL CHECK(sequence>0), PRIMARY KEY(workspace_id,id),
 FOREIGN KEY(workspace_id,conversation_id) REFERENCES conversations(workspace_id,id),
 UNIQUE(workspace_id,conversation_id,sequence)
);
CREATE TABLE plans (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(),
 created_at timestamptz NOT NULL DEFAULT now(), conversation_id uuid NOT NULL, parent_id uuid,
 revision integer NOT NULL CHECK(revision>0), interpretation json NOT NULL, created_by varchar(128) NOT NULL,
 PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,conversation_id,revision),
 UNIQUE(workspace_id,conversation_id,id),
 FOREIGN KEY(workspace_id,conversation_id) REFERENCES conversations(workspace_id,id),
 FOREIGN KEY(workspace_id,conversation_id,parent_id) REFERENCES plans(workspace_id,conversation_id,id)
);
CREATE FUNCTION prevent_immutable_change() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN RAISE EXCEPTION 'Immutable record cannot be changed'; END $$;
REVOKE ALL ON FUNCTION prevent_immutable_change() FROM PUBLIC;
CREATE TRIGGER immutable_plans BEFORE UPDATE OR DELETE ON plans
 FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change();
CREATE TRIGGER immutable_messages BEFORE UPDATE OR DELETE ON messages
 FOR EACH ROW EXECUTE FUNCTION prevent_immutable_change();
""")
    for table in ("conversations", "messages", "plans"):
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; "
            f"CREATE POLICY tenant ON {table} USING(tenant_allowed(workspace_id)) "
            "WITH CHECK(tenant_allowed(workspace_id)); "
            f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO skriller_app;"
        )


def downgrade():
    op.execute("DROP TABLE plans,messages,conversations; DROP FUNCTION prevent_immutable_change();")
