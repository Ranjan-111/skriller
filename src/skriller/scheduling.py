"""Opt-in saved-plan scheduling through the existing bounded research job/outbox."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from skriller.connections.tables import connections
from skriller.connectors.switches import disabled_operations
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.db.schema import jobs, messages, plans, scoped
from skriller.entitlements import admit, policy_for, request_denial, used_runs
from skriller.jobs.outbox import submit
from skriller.lists import _plan, saved_lists

schedules = scoped(
    "research_schedules",
    sa.Column("list_id", PGUUID(as_uuid=False), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("prompt_message_id", PGUUID(as_uuid=False)),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("cadence_hours", sa.Integer, nullable=False),
    sa.Column("max_runs", sa.Integer, nullable=False),
    sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("required_connection_ids", sa.JSON, nullable=False),
    sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_token", PGUUID(as_uuid=False)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column("last_job_id", PGUUID(as_uuid=False)),
    sa.Column("last_reason", sa.String(40)),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "prompt_message_id"],
            [messages.c.workspace_id, messages.c.id],
            name="schedule_prompt_scope",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "list_id"], [saved_lists.c.workspace_id, saved_lists.c.id]
        ),
        sa.ForeignKeyConstraint(["workspace_id", "last_job_id"], [jobs.c.workspace_id, jobs.c.id]),
        sa.UniqueConstraint("workspace_id", "list_id"),
        sa.CheckConstraint(
            "cadence_hours BETWEEN 1 AND 720 AND max_runs BETWEEN 1 AND 25 AND run_count BETWEEN 0 AND max_runs"
        ),
    ),
)
runs = scoped(
    "scheduled_research_runs",
    sa.Column("schedule_id", PGUUID(as_uuid=False), nullable=False),
    sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
    sa.Column("job_id", PGUUID(as_uuid=False), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "schedule_id"], [schedules.c.workspace_id, schedules.c.id]
        ),
        sa.ForeignKeyConstraint(["workspace_id", "job_id"], [jobs.c.workspace_id, jobs.c.id]),
        sa.UniqueConstraint("workspace_id", "schedule_id", "scheduled_for"),
    ),
)


def create_schedule(
    session, list_id, *, opt_in, cadence_hours, max_runs, required_connection_ids=()
):
    require_owner(session)
    if (
        opt_in is not True
        or type(cadence_hours) is not int
        or not 1 <= cadence_hours <= 720
        or type(max_runs) is not int
        or not 1 <= max_runs <= 25
        or not isinstance(required_connection_ids, tuple)
        or len(required_connection_ids) > 9
    ):
        raise ValueError("Explicit bounded refresh schedule required")
    refs = tuple(str(UUID(value)) for value in required_connection_ids)
    if len(set(refs)) != len(refs):
        raise ValueError("Unique connection references required")
    header = (
        session.execute(
            sa.select(saved_lists).where(
                saved_lists.c.workspace_id == scope(session), saved_lists.c.id == str(UUID(list_id))
            )
        )
        .mappings()
        .one_or_none()
    )
    if header is None:
        raise LookupError("Saved list unavailable")
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "research-schedules:" + scope(session)},
    )
    count = session.execute(
        sa.select(sa.func.count())
        .select_from(schedules)
        .where(schedules.c.workspace_id == scope(session))
    ).scalar_one()
    if count >= 10:
        raise ValueError("Workspace schedule limit reached")
    plan = _plan(session, header["plan_id"])
    revision = ConversationRepository.get_plan(session, header["plan_id"])
    latest_plan = session.execute(
        sa.select(plans.c.id)
        .where(
            plans.c.workspace_id == scope(session),
            plans.c.conversation_id == str(plan.conversation_id),
        )
        .order_by(plans.c.revision.desc())
        .limit(1)
    ).scalar_one()
    prompt = (
        session.execute(
            sa.select(messages)
            .where(
                messages.c.workspace_id == scope(session),
                messages.c.conversation_id == str(plan.conversation_id),
                messages.c.role == "user",
                messages.c.created_at <= revision["created_at"],
            )
            .order_by(messages.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if (
        latest_plan != header["plan_id"]
        or prompt is None
        or not prompt["content"].strip()
        or len(prompt["content"]) > 1500
    ):
        raise ValueError("Scheduling needs the latest saved plan and its explicit objective")
    for ref in refs:
        connection = (
            session.execute(
                sa.select(connections).where(
                    connections.c.workspace_id == scope(session),
                    connections.c.id == ref,
                )
            )
            .mappings()
            .one_or_none()
        )
        if connection is None or connection["source"] not in plan.sources:
            raise LookupError("Required source connection unavailable")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    return insert_row(
        session,
        schedules,
        list_id=header["id"],
        created_by=session.info["actor_id"],
        prompt_message_id=prompt["id"],
        enabled=True,
        cadence_hours=cadence_hours,
        max_runs=max_runs,
        required_connection_ids=list(refs),
        next_due_at=now + timedelta(hours=cadence_hours),
    )


def disable_schedule(session, schedule_id):
    require_owner(session)
    result = session.execute(
        sa.update(schedules)
        .where(schedules.c.workspace_id == scope(session), schedules.c.id == str(UUID(schedule_id)))
        .values(
            enabled=False, last_reason="owner_disabled", lease_token=None, lease_expires_at=None
        )
        .returning(schedules.c.id)
    ).scalar_one_or_none()
    if result is None:
        raise LookupError("Refresh schedule unavailable")


def resume_schedule(session, schedule_id, *, opt_in):
    require_owner(session)
    if opt_in is not True:
        raise ValueError("Explicit schedule opt-in required")
    row = (
        session.execute(
            sa.select(schedules)
            .where(
                schedules.c.workspace_id == scope(session), schedules.c.id == str(UUID(schedule_id))
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Refresh schedule unavailable")
    if row["run_count"] >= row["max_runs"]:
        raise ValueError("Schedule run allowance exhausted")
    if row["enabled"]:
        return dict(row)
    if row["prompt_message_id"] is None:
        raise ValueError("Schedule needs a pinned objective")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    return dict(
        session.execute(
            sa.update(schedules)
            .where(schedules.c.workspace_id == scope(session), schedules.c.id == row["id"])
            .values(
                enabled=True,
                last_reason="owner_resumed",
                lease_token=None,
                lease_expires_at=None,
                next_due_at=now + timedelta(hours=row["cadence_hours"]),
            )
            .returning(schedules)
        )
        .mappings()
        .one()
    )


def scheduled_execution_denial(session, job):
    """Repeat connection opt-in gates immediately before existing worker I/O."""
    if job["schedule_id"] is None:
        return None
    row = (
        session.execute(
            sa.select(schedules).where(
                schedules.c.workspace_id == scope(session), schedules.c.id == job["schedule_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return "schedule_unavailable"
    if row["prompt_message_id"] is None:
        return "plan_requires_review"
    if row["last_reason"] in {"owner_disabled", "data_erasure", "restore_requires_opt_in"}:
        return "schedule_disabled"
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    for ref in row["required_connection_ids"]:
        connection = (
            session.execute(
                sa.select(connections).where(
                    connections.c.workspace_id == scope(session), connections.c.id == ref
                )
            )
            .mappings()
            .one_or_none()
        )
        if connection is None or connection["state"] != "active" or connection["expires_at"] <= now:
            return "source_disconnected"
    return None


def pinned_prompt(session, job, plan):
    """Only scheduled jobs override discovery's ordinary latest-message lookup."""
    if job["schedule_id"] is None:
        return None
    row = session.execute(
        sa.select(messages.c.content)
        .join(
            schedules,
            sa.and_(
                messages.c.workspace_id == schedules.c.workspace_id,
                messages.c.id == schedules.c.prompt_message_id,
            ),
        )
        .where(
            schedules.c.workspace_id == scope(session),
            schedules.c.id == job["schedule_id"],
            messages.c.conversation_id == str(plan.conversation_id),
            messages.c.role == "user",
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Scheduled research objective unavailable")
    return row


def claim_due(session):
    require_owner(session)
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    row = (
        session.execute(
            sa.select(schedules)
            .where(
                schedules.c.workspace_id == scope(session),
                schedules.c.created_by == session.info["actor_id"],
                schedules.c.enabled.is_(True),
                schedules.c.next_due_at <= now,
                sa.or_(schedules.c.lease_expires_at.is_(None), schedules.c.lease_expires_at <= now),
            )
            .order_by(schedules.c.next_due_at, schedules.c.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    token = str(uuid4())
    session.execute(
        sa.update(schedules)
        .where(schedules.c.workspace_id == scope(session), schedules.c.id == row["id"])
        .values(lease_token=token, lease_expires_at=now + timedelta(seconds=60))
    )
    return {"schedule_id": row["id"], "lease_token": token}


def execute_due(session, task, *, search_enabled):
    """No source/model I/O. Admission + one logical job + due advance are atomic.

    Existing workers still recheck all source switches, execution budgets and
    account policies immediately before I/O. Saved lists remain immutable; this
    creates a separately reviewable research job, not an automatic list overwrite.
    """
    require_owner(session)
    row = (
        session.execute(
            sa.select(schedules)
            .where(
                schedules.c.workspace_id == scope(session),
                schedules.c.id == str(UUID(task["schedule_id"])),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if (
        row is None
        or not row["enabled"]
        or row["created_by"] != session.info["actor_id"]
        or row["lease_token"] != task["lease_token"]
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= now
    ):
        return {"status": "stale_lease", "job_id": None}
    reason = None
    header = (
        session.execute(
            sa.select(saved_lists).where(
                saved_lists.c.workspace_id == scope(session), saved_lists.c.id == row["list_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    plan = _plan(session, header["plan_id"]) if header else None
    if plan is None:
        reason = "list_unavailable"
    elif row["run_count"] >= row["max_runs"]:
        reason = "schedule_limit"
    elif not search_enabled or not plan.sources or plan.limits.search_calls < len(plan.sources):
        reason = "search_unavailable"
    elif plan.clarification or plan.unsupported_criteria:
        reason = "plan_requires_review"
    elif any((source, "discover") in disabled_operations(session) for source in plan.sources):
        reason = "source_disabled"
    if reason is None:
        assert plan is not None
        for ref in row["required_connection_ids"]:
            connection = (
                session.execute(
                    sa.select(connections).where(
                        connections.c.workspace_id == scope(session),
                        connections.c.id == ref,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                connection is None
                or connection["state"] != "active"
                or connection["expires_at"] <= now
                or connection["source"] not in plan.sources
            ):
                reason = "source_disconnected"
                break
    if reason is None and row["last_job_id"]:
        previous = JobRepository.get(session, row["last_job_id"])
        if previous and previous["state"] not in {"completed", "partial", "failed", "cancelled"}:
            reason = "previous_run_incomplete"
    if reason is None:
        assert plan is not None
        policy = policy_for(session, lock=True)
        reason = request_denial(policy, result_limit=plan.limits.result_limit, sources=plan.sources)
        if reason is None and used_runs(session) >= policy["run_limit"]:
            reason = "entitlement_exhausted"
    changes: dict[str, Any] = {"lease_token": None, "lease_expires_at": None}
    job_id = None
    if reason:
        changes.update(enabled=False, last_reason=reason)
    else:
        revision = ConversationRepository.get_plan(session, header["plan_id"])
        key = f"scheduled:{row['id']}:{row['next_due_at'].isoformat()}"
        job = submit(session, revision["conversation_id"], revision["id"], key)
        session.execute(
            sa.update(jobs)
            .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
            .values(schedule_id=row["id"])
        )
        denial = admit(session, job["id"])
        if denial:
            # Roll back the whole transaction; never commit a bypassed admission.
            raise RuntimeError("Scheduled admission changed within its policy lock")
        job_id = job["id"]
        insert_row(
            session, runs, schedule_id=row["id"], scheduled_for=row["next_due_at"], job_id=job_id
        )
        changes.update(
            last_job_id=job_id,
            run_count=row["run_count"] + 1,
            enabled=row["run_count"] + 1 < row["max_runs"],
            last_reason="queued",
            next_due_at=now + timedelta(hours=row["cadence_hours"]),
        )
    session.execute(
        sa.update(schedules)
        .where(schedules.c.workspace_id == scope(session), schedules.c.id == row["id"])
        .values(**changes)
    )
    return {"status": reason or "queued", "job_id": job_id}
