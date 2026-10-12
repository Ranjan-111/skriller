"""Workspace mutations are owner-only; creation uses the scoped provisioning function."""

from alembic import op

revision = "0001a"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
DROP POLICY tenant_workspace ON workspaces;
CREATE POLICY workspace_read ON workspaces FOR SELECT USING(tenant_allowed(id));
CREATE POLICY workspace_update ON workspaces FOR UPDATE USING(
    tenant_allowed(id) AND workspace_role(id,current_setting('app.actor_id',true))='owner')
    WITH CHECK(tenant_allowed(id) AND workspace_role(id,current_setting('app.actor_id',true))='owner');
CREATE POLICY workspace_delete ON workspaces FOR DELETE USING(
    tenant_allowed(id) AND workspace_role(id,current_setting('app.actor_id',true))='owner');
""")


def downgrade():
    op.execute("""DROP POLICY workspace_read ON workspaces;
DROP POLICY workspace_update ON workspaces;
DROP POLICY workspace_delete ON workspaces;
CREATE POLICY tenant_workspace ON workspaces USING(tenant_allowed(id)) WITH CHECK(tenant_allowed(id));""")
