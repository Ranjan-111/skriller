"""Authenticated actor scope discovery without granting membership table bypass."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE FUNCTION actor_workspaces()
RETURNS TABLE(id uuid, name varchar, created_at timestamptz, role varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
    SELECT w.id,w.name,w.created_at,m.role FROM public.workspaces w
    JOIN public.memberships m ON m.workspace_id=w.id
    WHERE m.actor_id=nullif(current_setting('app.actor_id',true),'')
    ORDER BY w.created_at,w.id
$$;
REVOKE ALL ON FUNCTION actor_workspaces() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION actor_workspaces() TO skriller_app;
CREATE FUNCTION get_or_create_personal_workspace()
RETURNS TABLE(id uuid, name varchar, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE actor text; selected uuid;
BEGIN
    actor := current_setting('app.actor_id',true);
    IF actor IS NULL OR length(actor)=0 OR length(actor)>128 THEN
        RAISE EXCEPTION 'Verified actor required';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('personal-workspace:' || actor,0));
    SELECT w.id INTO selected FROM public.workspaces w
    JOIN public.memberships m ON m.workspace_id=w.id
    WHERE m.actor_id=actor AND m.role='owner' ORDER BY w.created_at,w.id LIMIT 1;
    IF selected IS NULL THEN
        SELECT c.id INTO selected FROM public.create_workspace('My research workspace') c;
    END IF;
    RETURN QUERY SELECT w.id,w.name,w.created_at FROM public.workspaces w WHERE w.id=selected;
END $$;
REVOKE ALL ON FUNCTION get_or_create_personal_workspace() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_or_create_personal_workspace() TO skriller_app;
""")


def downgrade():
    op.execute(
        "DROP FUNCTION get_or_create_personal_workspace(); DROP FUNCTION actor_workspaces();"
    )
