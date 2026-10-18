"""Operator-only durable resolution of verified payment references."""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE billing_event_references (
      provider varchar(16) NOT NULL CHECK(provider IN ('stripe','razorpay')),
      account_scope varchar(192) NOT NULL,event_key varchar(192) NOT NULL,
      payload_hash varchar(64) NOT NULL,event_type varchar(80) NOT NULL,
      reference_id varchar(192) NOT NULL,
      state varchar(16) NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','resolved','quarantined')),
      attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 5),
      next_attempt_at timestamptz NOT NULL DEFAULT now(),received_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(provider,account_scope,event_key));
      CREATE INDEX billing_reference_due ON billing_event_references(state,next_attempt_at);
      REVOKE ALL ON billing_event_references FROM PUBLIC,skriller_app""")


def downgrade():
    op.drop_table("billing_event_references")
