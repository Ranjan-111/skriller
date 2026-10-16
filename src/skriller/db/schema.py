"""PostgreSQL persistence schema; every scoped reference carries its workspace."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

metadata = sa.MetaData()


def identifier():
    return str(uuid4())


def scoped(name, *columns, constraints=()):
    return sa.Table(
        name,
        metadata,
        sa.Column(
            "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
        ),
        sa.Column("id", UUID(as_uuid=False), primary_key=True, default=identifier),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        *columns,
        *constraints,
    )


workspaces = sa.Table(
    "workspaces",
    metadata,
    sa.Column("id", UUID(as_uuid=False), primary_key=True, default=identifier),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("length(trim(name)) > 0", name="workspace_name_nonempty"),
)
memberships = sa.Table(
    "memberships",
    metadata,
    sa.Column(
        "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
    ),
    sa.Column("actor_id", sa.String(128), primary_key=True),
    sa.Column("role", sa.String(16), nullable=False),
    sa.CheckConstraint("role IN ('owner','member')", name="membership_role"),
    sa.CheckConstraint("length(actor_id) > 0", name="membership_actor_nonempty"),
)

conversations = scoped(
    "conversations",
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
)
messages = scoped(
    "messages",
    sa.Column("conversation_id", UUID(as_uuid=False), nullable=False),
    sa.Column("role", sa.String(16), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("sequence", sa.Integer, nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id"], ["conversations.workspace_id", "conversations.id"]
        ),
        sa.UniqueConstraint("workspace_id", "conversation_id", "sequence"),
        sa.CheckConstraint("role IN ('user','assistant','system')"),
        sa.CheckConstraint("sequence > 0"),
    ),
)
plans = scoped(
    "plans",
    sa.Column("conversation_id", UUID(as_uuid=False), nullable=False),
    sa.Column("parent_id", UUID(as_uuid=False)),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("interpretation", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id"], ["conversations.workspace_id", "conversations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id", "parent_id"],
            ["plans.workspace_id", "plans.conversation_id", "plans.id"],
        ),
        sa.UniqueConstraint("workspace_id", "conversation_id", "revision"),
        sa.UniqueConstraint("workspace_id", "conversation_id", "id"),
        sa.CheckConstraint("revision > 0"),
        sa.CheckConstraint(
            "(revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL AND parent_id<>id)",
            name="revision_parent_shape",
        ),
    ),
)

entities = scoped(
    "entities",
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("display_name", sa.Text),
    sa.Column("canonical_key", sa.Text),
    sa.Column("attributes", sa.JSON, nullable=False, default=dict),
    constraints=(
        sa.CheckConstraint("kind IN ('person','company','post','video','community','other')"),
        sa.UniqueConstraint("workspace_id", "kind", "canonical_key"),
    ),
)
evidence = scoped(
    "evidence",
    sa.Column("source_url", sa.Text, nullable=False),
    sa.Column("source_platform", sa.String(32), nullable=False),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("excerpt", sa.Text),
    sa.Column("object_key", sa.Text),
    sa.Column("content_hash", sa.String(64)),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
)
claims = scoped(
    "claims",
    sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
    sa.Column("field", sa.String(120), nullable=False),
    sa.Column("value", sa.JSON),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("status", sa.String(16), nullable=False, default="unverified"),
    sa.Column("confidence", sa.Numeric(5, 4)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.CheckConstraint("mode IN ('observed','inferred','unavailable')"),
        sa.CheckConstraint("status IN ('accepted','unverified','conflict')"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),
    ),
)
claim_evidence = sa.Table(
    "claim_evidence",
    metadata,
    sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
    sa.Column("claim_id", UUID(as_uuid=False), primary_key=True),
    sa.Column("evidence_id", UUID(as_uuid=False), primary_key=True),
    sa.ForeignKeyConstraint(["workspace_id", "claim_id"], ["claims.workspace_id", "claims.id"]),
    sa.ForeignKeyConstraint(
        ["workspace_id", "evidence_id"], ["evidence.workspace_id", "evidence.id"]
    ),
)
entity_links = scoped(
    "entity_links",
    sa.Column("source_id", UUID(as_uuid=False), nullable=False),
    sa.Column("target_id", UUID(as_uuid=False), nullable=False),
    sa.Column("relation", sa.String(64), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "target_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.UniqueConstraint("workspace_id", "source_id", "target_id", "relation"),
    ),
)
qualifications = scoped(
    "qualifications",
    sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
    sa.Column("plan_id", UUID(as_uuid=False), nullable=False),
    sa.Column("criterion", sa.Text, nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("reason", sa.Text),
    sa.Column("claim_id", UUID(as_uuid=False)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]),
        sa.ForeignKeyConstraint(["workspace_id", "claim_id"], ["claims.workspace_id", "claims.id"]),
        sa.CheckConstraint("outcome IN ('match','no_match','unknown')"),
    ),
)
suppressions = scoped(
    "suppressions",
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.CheckConstraint("kind IN ('email','domain','profile','entity')"),
        sa.UniqueConstraint("workspace_id", "kind", "key"),
    ),
)

jobs = scoped(
    "jobs",
    sa.Column("conversation_id", UUID(as_uuid=False), nullable=False),
    sa.Column("plan_id", UUID(as_uuid=False), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, default="planned"),
    sa.Column("stage", sa.String(64)),
    sa.Column("version", sa.Integer, nullable=False, default=1),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("failure_code", sa.String(64)),
    sa.Column("purpose", sa.String(16), nullable=False, server_default="research"),
    sa.Column("schedule_id", UUID(as_uuid=False)),
    sa.Column("terminal_reason", sa.String(64)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "schedule_id"],
            ["research_schedules.workspace_id", "research_schedules.id"],
            name="job_schedule_scope",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "conversation_id", "plan_id"],
            ["plans.workspace_id", "plans.conversation_id", "plans.id"],
        ),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint(
            "state IN ('planned','queued','running','waiting_for_connection','paused','completed','partial','failed','cancelled')"
        ),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint(
            "purpose IN ('research','planning','followup','template_repair','owner_summary')"
        ),
        sa.CheckConstraint(
            "(state IN ('completed','partial','failed','cancelled')) = "
            "(terminal_reason IS NOT NULL)",
            name="terminal_reason_required",
        ),
        sa.CheckConstraint(
            "(state='completed' AND terminal_reason IN ('source_exhausted','target_met')) OR "
            "(state='partial' AND terminal_reason IN "
            "('budget_limit','deadline_limit','source_interrupted')) OR "
            "(state='failed' AND terminal_reason IN "
            "('budget_limit','deadline_limit','source_interrupted','processing_error')) OR "
            "(state='cancelled' AND terminal_reason='user_cancelled') OR "
            "(state NOT IN ('completed','partial','failed','cancelled') "
            "AND terminal_reason IS NULL)",
            name="terminal_reason_consistent",
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('planning','discovering','collecting','extracting','resolving','qualifying','reporting')"
        ),
    ),
)
followup_reports = scoped(
    "followup_reports",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("source_job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("entity_id", UUID(as_uuid=False), nullable=False),
    sa.Column("question", sa.String(500), nullable=False),
    sa.Column("evidence_ids", sa.JSON, nullable=False),
    sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
    sa.Column("citation_hashes", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
    sa.Column("unknowns", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_job_id"], ["jobs.workspace_id", "jobs.id"]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.UniqueConstraint("workspace_id", "job_id"),
        sa.CheckConstraint("status IN ('pending','answered','unknown')"),
    ),
)
attempts = scoped(
    "attempts",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("logical_key", sa.String(200), nullable=False),
    sa.Column("stage", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, default="pending"),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("reservation_id", UUID(as_uuid=False)),
    sa.Column("result_entity_ids", sa.JSON),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.UniqueConstraint("workspace_id", "job_id", "logical_key"),
        sa.UniqueConstraint("workspace_id", "job_id", "id"),
        sa.CheckConstraint("state IN ('pending','running','succeeded','failed','cancelled')"),
    ),
)
job_events = scoped(
    "job_events",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("sequence", sa.BigInteger, sa.Identity(), nullable=False),
    sa.Column("event_key", sa.String(200), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("details", sa.JSON, nullable=False, default=dict),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.UniqueConstraint("workspace_id", "job_id", "event_key"),
        sa.UniqueConstraint("sequence"),
    ),
)
outbox = scoped(
    "outbox",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("attempt_id", UUID(as_uuid=False)),
    sa.Column("topic", sa.String(32), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("discarded_at", sa.DateTime(timezone=True)),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id", "attempt_id"],
            ["attempts.workspace_id", "attempts.job_id", "attempts.id"],
        ),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint("topic IN ('execute_job','execute_attempt','cancel_job')"),
    ),
)
usage_records = scoped(
    "usage_records",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("attempt_id", UUID(as_uuid=False)),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
    sa.Column("cost_usd", sa.Numeric(20, 8), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id", "attempt_id"],
            ["attempts.workspace_id", "attempts.job_id", "attempts.id"],
        ),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint("quantity >= 0 AND cost_usd >= 0"),
    ),
)
reservations = scoped(
    "reservations",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("amount_usd", sa.Numeric(20, 8), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, default="held"),
    sa.Column("dimensions", sa.JSON, nullable=False, default=dict, server_default=sa.text("'{}'")),
    sa.Column("actual_dimensions", sa.JSON),
    sa.Column("reconciliation_status", sa.String(16)),
    sa.Column("actual_cost_usd", sa.Numeric(20, 8)),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
        sa.UniqueConstraint("workspace_id", "job_id", "idempotency_key"),
        sa.CheckConstraint("amount_usd >= 0"),
        sa.CheckConstraint("state IN ('held','committed','released')"),
        sa.CheckConstraint("actual_cost_usd IS NULL OR actual_cost_usd >= 0"),
        sa.CheckConstraint(
            "reconciliation_status IS NULL OR reconciliation_status IN "
            "('estimated','confirmed','not_charged')"
        ),
    ),
)

adaptive_fingerprints = scoped(
    "adaptive_fingerprints",
    sa.Column("source", sa.String(32), nullable=False),
    sa.Column("access_scope", sa.String(128), nullable=False),
    sa.Column("domain", sa.String(253), nullable=False),
    sa.Column("template_id", UUID(as_uuid=False), nullable=False),
    sa.Column("template_version", sa.Integer, nullable=False),
    sa.Column("selector_identifier", sa.Text, nullable=False),
    sa.Column(
        "selector_hash", sa.String(32), sa.Computed("md5(selector_identifier)", persisted=True)
    ),
    sa.Column("element_data", sa.JSON, nullable=False),
    constraints=(
        sa.UniqueConstraint(
            "workspace_id",
            "source",
            "access_scope",
            "domain",
            "template_id",
            "template_version",
            "selector_hash",
            name="adaptive_namespace",
        ),
        sa.CheckConstraint(
            "source IN ('linkedin','reddit','web','github','rss','youtube','x','instagram','facebook')"
        ),
        sa.CheckConstraint(
            "access_scope='public' OR access_scope ~ "
            "'^connection:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
        ),
        sa.CheckConstraint("length(domain) BETWEEN 1 AND 253"),
        sa.CheckConstraint("template_version > 0"),
        sa.CheckConstraint("length(selector_identifier) BETWEEN 1 AND 4096"),
    ),
)

# Worker leases fence obsolete deliveries before any canonical result writes.
attempts.append_column(sa.Column("lease_owner", UUID(as_uuid=False)))
attempts.append_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
attempts.append_column(sa.Column("generation", sa.Integer, nullable=False, server_default="0"))

stage_checkpoints = scoped(
    "stage_checkpoints",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("attempt_id", UUID(as_uuid=False), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("stage", sa.String(64), nullable=False),
    sa.Column("result_refs", sa.JSON, nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id", "attempt_id"],
            ["attempts.workspace_id", "attempts.job_id", "attempts.id"],
        ),
        sa.UniqueConstraint("workspace_id", "attempt_id"),
        sa.CheckConstraint("generation > 0"),
    ),
)
external_calls = scoped(
    "external_calls",
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("attempt_id", UUID(as_uuid=False), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("operation_key", sa.String(200), nullable=False),
    sa.Column("reservation_id", UUID(as_uuid=False), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id", "attempt_id"],
            ["attempts.workspace_id", "attempts.job_id", "attempts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "reservation_id"], ["reservations.workspace_id", "reservations.id"]
        ),
        sa.UniqueConstraint("workspace_id", "attempt_id", "generation", "operation_key"),
        sa.CheckConstraint("generation > 0"),
        sa.CheckConstraint("state IN ('in_flight','confirmed','uncertain')"),
    ),
)

# Owner-managed shared capacity: only checked SECURITY DEFINER operations expose
# these tables. Their RLS has no direct application policy by design.
capacity_leases = sa.Table(
    "capacity_leases",
    metadata,
    sa.Column(
        "id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")
    ),
    sa.Column("workspace_id", UUID(as_uuid=False), nullable=False),
    sa.Column("job_id", UUID(as_uuid=False), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("host", sa.Text, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
    sa.CheckConstraint("kind IN ('http','browser','model')"),
)
sa.Index("capacity_active", capacity_leases.c.expires_at)
capacity_cadence = sa.Table(
    "capacity_cadence",
    metadata,
    sa.Column("scope", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("delay", sa.Float, nullable=False, server_default="0"),
    sa.Column(
        "next_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("'-infinity'")
    ),
)

reviewed_template_versions = scoped(
    "reviewed_template_versions",
    sa.Column("template_id", UUID(as_uuid=False), nullable=False),
    sa.Column("template_version", sa.Integer, nullable=False),
    sa.Column("source_url", sa.String(4096), nullable=False),
    sa.Column("source_hash", sa.String(64), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.UniqueConstraint("workspace_id", "template_id", "template_version"),
        sa.CheckConstraint("template_version BETWEEN 1 AND 1000000"),
    ),
)
active_page_templates = scoped(
    "active_page_templates",
    sa.Column("version_id", UUID(as_uuid=False), nullable=False),
    sa.Column("updated_by", sa.String(128), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "version_id"],
            ["reviewed_template_versions.workspace_id", "reviewed_template_versions.id"],
        ),
    ),
)
page_template_audit = scoped(
    "page_template_audit",
    sa.Column("template_id", UUID(as_uuid=False), nullable=False),
    sa.Column("previous_version", sa.Integer),
    sa.Column("selected_version", sa.Integer, nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(sa.CheckConstraint("action IN ('publish','rollback')"),),
)
