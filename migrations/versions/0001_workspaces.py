"""Workspaces, role membership and database-enforced tenant isolation."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT workspace_name_nonempty CHECK(length(trim(name)) > 0)
);
CREATE TABLE memberships (
    workspace_id uuid NOT NULL REFERENCES workspaces(id), actor_id varchar(128) NOT NULL,
    role varchar(16) NOT NULL CHECK(role IN ('owner','member')),
    CHECK(length(actor_id)>0), PRIMARY KEY(workspace_id,actor_id)
);
CREATE FUNCTION workspace_role(w uuid, a text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
    SELECT role::text FROM public.memberships WHERE workspace_id=w AND actor_id=a
$$;
REVOKE ALL ON FUNCTION workspace_role(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION workspace_role(uuid,text) TO skriller_app;
CREATE FUNCTION tenant_allowed(w uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
    SELECT w = nullif(current_setting('app.workspace_id',true),'')::uuid
       AND public.workspace_role(w,current_setting('app.actor_id',true)) IS NOT NULL
$$;
REVOKE ALL ON FUNCTION tenant_allowed(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION tenant_allowed(uuid) TO skriller_app;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_workspace ON workspaces USING(tenant_allowed(id)) WITH CHECK(tenant_allowed(id));
CREATE POLICY membership_read ON memberships FOR SELECT USING(tenant_allowed(workspace_id));
CREATE POLICY membership_insert ON memberships FOR INSERT WITH CHECK(
    tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner');
CREATE POLICY membership_update ON memberships FOR UPDATE USING(
    tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner')
    WITH CHECK(tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner');
CREATE POLICY membership_delete ON memberships FOR DELETE USING(
    tenant_allowed(workspace_id) AND workspace_role(workspace_id,current_setting('app.actor_id',true))='owner');
GRANT USAGE ON SCHEMA public TO skriller_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON workspaces,memberships TO skriller_app;
CREATE FUNCTION create_workspace(workspace_name text)
RETURNS TABLE(id uuid,name varchar,created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE actor text; new_id uuid;
BEGIN
    actor := current_setting('app.actor_id',true);
    IF actor IS NULL OR length(actor)=0 OR length(actor)>128 THEN
        RAISE EXCEPTION 'Verified actor required';
    END IF;
    INSERT INTO public.workspaces(name) VALUES(workspace_name) RETURNING workspaces.id INTO new_id;
    INSERT INTO public.memberships VALUES(new_id,actor,'owner');
    RETURN QUERY SELECT w.id,w.name,w.created_at FROM public.workspaces w WHERE w.id=new_id;
END $$;
REVOKE ALL ON FUNCTION create_workspace(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION create_workspace(text) TO skriller_app;
""")


def downgrade():
    op.execute(
        "DROP FUNCTION create_workspace(text); DROP TABLE memberships,workspaces CASCADE; "
        "DROP FUNCTION IF EXISTS tenant_allowed(uuid); DROP FUNCTION IF EXISTS workspace_role(uuid,text);"
    )
