"""Initial checkout intents and verified subscription event linkage."""

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE billing_checkout_intents (
      id uuid PRIMARY KEY,workspace_id uuid NOT NULL UNIQUE REFERENCES workspaces(id),
      created_by varchar(128) NOT NULL,provider varchar(16) NOT NULL CHECK(provider IN ('stripe','razorpay')),
      account_scope varchar(192) NOT NULL,slug varchar(16) NOT NULL CHECK(slug IN ('starter','pro')),
      plan_id varchar(192) NOT NULL,request_hash varchar(64) NOT NULL,
      state varchar(16) NOT NULL DEFAULT 'dispatching' CHECK(state IN ('dispatching','ready','uncertain','bound')),
      remote_id varchar(192),checkout_url varchar(4096),subscription_id varchar(192),
      expires_at timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
      REVOKE ALL ON billing_checkout_intents FROM PUBLIC,skriller_app;
      ALTER TABLE billing_event_references ADD COLUMN checkout_id uuid REFERENCES billing_checkout_intents(id);
      ALTER TABLE billing_event_references ADD COLUMN expected_subscription_id varchar(192);
      ALTER TABLE billing_event_references ADD CONSTRAINT checkout_reference_pair CHECK(
        (checkout_id IS NULL)=(expected_subscription_id IS NULL));""")


def downgrade():
    op.execute("ALTER TABLE billing_event_references DROP CONSTRAINT checkout_reference_pair")
    op.drop_column("billing_event_references", "expected_subscription_id")
    op.drop_column("billing_event_references", "checkout_id")
    op.drop_table("billing_checkout_intents")
