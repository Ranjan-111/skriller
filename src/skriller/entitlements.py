"""Finite workspace admission, immutable run usage and owner-controlled ceilings."""

from uuid import UUID as UUIDValue

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.db import JobRepository
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import metadata
from skriller.jobs.budget import locked_job

policies = sa.Table(
    "workspace_entitlements",
    metadata,
    sa.Column(
        "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
    ),
    sa.Column("tier", sa.String(16), nullable=False, server_default="trial"),
    sa.Column("run_limit", sa.Integer, nullable=False, server_default="25"),
    sa.Column("result_cap", sa.Integer, nullable=False, server_default="25"),
    sa.Column("source_cap", sa.Integer, nullable=False, server_default="3"),
    sa.Column("result_limit", sa.Integer, nullable=False, server_default="25"),
    sa.Column("source_limit", sa.Integer, nullable=False, server_default="3"),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("invoice_reference", sa.String(120)),
    sa.Column("updated_by", sa.String(128), nullable=False),
)
admissions = sa.Table(
    "entitlement_admissions",
    metadata,
    sa.Column("workspace_id", UUID(as_uuid=False), primary_key=True),
    sa.Column("job_id", UUID(as_uuid=False), primary_key=True),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column(
        "admitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.ForeignKeyConstraint(["workspace_id", "job_id"], ["jobs.workspace_id", "jobs.id"]),
)


def policy_for(session, *, lock=False):
    workspace = scope(session)
    if lock:
        # Members need serialized admission without receiving UPDATE rights on
        # owner settings. The INSERT trigger independently locks the policy row.
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"entitlement:{workspace}"},
        )
    row = (
        session.execute(sa.select(policies).where(policies.c.workspace_id == workspace))
        .mappings()
        .one_or_none()
    )
    if row is None:
        if not lock:
            session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"entitlement:{workspace}"},
            )
        session.execute(
            insert(policies)
            .values(workspace_id=workspace, updated_by=session.info["actor_id"])
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
    statement = sa.select(policies).where(policies.c.workspace_id == workspace)
    return dict(session.execute(statement).mappings().one())


def used_runs(session):
    return session.execute(
        sa.select(sa.func.count())
        .select_from(admissions)
        .where(admissions.c.workspace_id == scope(session))
    ).scalar_one()


def policy_view(session):
    policy = policy_for(session)
    used = used_runs(session)
    return {
        key: policy[key]
        for key in (
            "tier",
            "enabled",
            "run_limit",
            "result_cap",
            "source_cap",
            "result_limit",
            "source_limit",
        )
    } | {
        "workspace_id": scope(session),
        "used_runs": used,
        "remaining_runs": max(0, policy["run_limit"] - used),
        "can_manage": session.info["role"] == "owner",
    }


def request_denial(policy, *, result_limit, sources):
    if not policy["enabled"]:
        return "workspace_disabled"
    if result_limit > policy["result_limit"] or len(sources) > policy["source_limit"]:
        return "entitlement_limits"
    return None


def admit(session, job_id):
    """One committed admission per job; lock order is job then workspace policy."""
    job = locked_job(session, job_id)
    policy = policy_for(session, lock=True)
    from skriller.jobs.control import plan_for_job

    plan = plan_for_job(session, job)
    reason = request_denial(policy, result_limit=plan.limits.result_limit, sources=plan.sources)
    if reason:
        return reason
    existing = session.execute(
        sa.select(admissions.c.job_id).where(
            admissions.c.workspace_id == scope(session), admissions.c.job_id == job_id
        )
    ).scalar_one_or_none()
    if existing:
        return None
    if used_runs(session) >= policy["run_limit"]:
        return "entitlement_exhausted"
    # The trigger repeats the quota/actor checks under this same policy lock.
    session.execute(
        insert(admissions).values(
            workspace_id=scope(session), job_id=job_id, actor_id=session.info["actor_id"]
        )
    )
    return None


def execution_allowed(session, job_id):
    job = locked_job(session, job_id)
    if job["state"] not in {"queued", "running"}:
        return False
    from skriller.jobs.control import remaining_seconds

    if remaining_seconds(session, job) <= 0:
        JobRepository.transition(session, job_id, "paused", failure_code="deadline_exceeded")
        JobRepository.event(session, job_id, "deadline:reached", "deadline_reached")
        return False
    reason = admit(session, job_id)
    if reason:
        job = locked_job(session, job_id)
        if job["state"] in {"queued", "running"}:
            JobRepository.transition(session, job_id, "paused", failure_code=reason)
            JobRepository.event(
                session, job_id, f"entitlement:{reason}", "entitlement_blocked", {"code": reason}
            )
        return False
    return True


def update_settings(session, *, enabled, result_limit, source_limit):
    require_owner(session)
    policy = policy_for(session, lock=True)
    if type(enabled) is not bool or type(result_limit) is not int or type(source_limit) is not int:
        raise ValueError("Strict workspace settings required")
    if (
        not 1 <= result_limit <= policy["result_cap"]
        or not 1 <= source_limit <= policy["source_cap"]
    ):
        raise ValueError("Settings exceed the operator-provisioned ceilings")
    session.execute(
        sa.update(policies)
        .where(policies.c.workspace_id == scope(session))
        .values(
            enabled=enabled,
            result_limit=result_limit,
            source_limit=source_limit,
            updated_by=session.info["actor_id"],
        )
    )
    return policy_view(session)


def provision_manual_pilot(connection, workspace_id, *, runs, results, sources, invoice_reference):
    workspace_id = str(UUIDValue(str(workspace_id)))
    if (
        type(runs) is not int
        or not 1 <= runs <= 1000
        or type(results) is not int
        or not 1 <= results <= 100
        or type(sources) is not int
        or not 1 <= sources <= 9
        or not invoice_reference.strip()
        or len(invoice_reference) > 120
    ):
        raise ValueError("Bounded manual allowance and invoice reference required")
    authority = connection.execute(
        sa.text(
            "SELECT r.rolname,r.rolsuper,c.relowner=r.oid FROM pg_roles r,pg_class c WHERE r.rolname=current_user AND c.oid='workspace_entitlements'::regclass"
        )
    ).one()
    role = authority[0]
    if not any(authority[1:]):
        raise PermissionError("Pilot provisioning requires the operator database role")
    values = {
        "workspace_id": workspace_id,
        "tier": "pilot",
        "run_limit": runs,
        "result_cap": results,
        "source_cap": sources,
        "result_limit": results,
        "source_limit": sources,
        "enabled": True,
        "invoice_reference": invoice_reference.strip(),
        "updated_by": "operator:" + role,
    }
    query = insert(policies).values(**values)
    connection.execute(
        query.on_conflict_do_update(
            index_elements=["workspace_id"],
            set_={key: value for key, value in values.items() if key != "workspace_id"},
        )
    )
    return {
        key: values[key]
        for key in ("workspace_id", "tier", "run_limit", "result_cap", "source_cap")
    }
