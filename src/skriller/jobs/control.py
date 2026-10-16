"""Persisted stop and resume controls, shared by workers and HTTP boundaries."""

from datetime import timedelta
from typing import Literal

import sqlalchemy as sa

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, external_calls, reservations
from skriller.jobs.budget import DIMENSIONS, current_usage, locked_job, reconcile
from skriller.jobs.state import TERMINAL_STATES

RESUME_DIMENSIONS = {
    "planning": {"llm_calls", "tokens"},
    "discovering": {"search_calls", "candidates"},
    "collecting": {"fetch_attempts"},
    "extracting": {"llm_calls", "tokens"},
    "reporting": {"llm_calls", "tokens"},
}


def plan_for_job(session, job):
    revision = ConversationRepository.get_plan(session, job["plan_id"])
    if revision is None:
        raise LookupError("Plan unavailable")
    plan = SearchPlan.model_validate(revision["interpretation"])
    if (
        str(plan.workspace_id) != scope(session)
        or str(plan.conversation_id) != job["conversation_id"]
        or plan.revision != revision["revision"]
    ):
        raise ValueError("Plan scope mismatch")
    return plan


def remaining_seconds(session, job):
    plan = plan_for_job(session, job)
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    return max(
        0.0,
        (job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds) - now).total_seconds(),
    )


def permit_call(session, job_id):
    """Call immediately before IO; caller must bound IO to the returned deadline."""
    job = locked_job(session, job_id)
    if job["state"] not in {"queued", "running"}:
        return 0.0
    remaining = remaining_seconds(session, job)
    if not remaining:
        JobRepository.transition(session, job_id, "paused")
        JobRepository.event(session, job_id, "deadline:reached", "deadline_reached")
        return 0.0
    from skriller.entitlements import execution_allowed

    if not execution_allowed(session, job_id):
        return 0.0
    return remaining


def cancel(session, job_id):
    job = locked_job(session, job_id)
    if job["state"] in TERMINAL_STATES:
        return dict(job)
    now = sa.func.clock_timestamp()
    active = (
        session.execute(
            sa.select(attempts).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job_id,
                attempts.c.state.in_(["pending", "running"]),
            )
        )
        .mappings()
        .all()
    )
    for attempt in active:
        if attempt["reservation_id"]:
            row = (
                session.execute(
                    sa.select(reservations).where(
                        reservations.c.workspace_id == scope(session),
                        reservations.c.id == attempt["reservation_id"],
                    )
                )
                .mappings()
                .one()
            )
            if row["state"] == "held":
                # Once dispatch begins its charge is uncertain, not automatically refunded.
                reconcile(session, job_id, row["id"], status="estimated")
    session.execute(
        sa.update(attempts)
        .where(
            attempts.c.workspace_id == scope(session),
            attempts.c.job_id == job_id,
            attempts.c.state.in_(["pending", "running"]),
        )
        .values(state="cancelled", lease_expires_at=now, finished_at=now)
    )
    session.execute(
        sa.update(external_calls)
        .where(
            external_calls.c.workspace_id == scope(session),
            external_calls.c.job_id == job_id,
            external_calls.c.state == "in_flight",
        )
        .values(state="uncertain", finished_at=now)
    )
    result = JobRepository.transition(
        session, job_id, "cancelled", terminal_reason="user_cancelled"
    )
    JobRepository.event(session, job_id, "control:cancelled", "cancellation_requested")
    return result


ResumeStatus = Literal[
    "not_paused",
    "available",
    "new_prompt_required",
    "deadline_expired",
    "requires_reconciliation",
    "budget_exhausted",
]


def _resume_context(session, job):
    if job["state"] != "paused":
        return "not_paused", []
    if job["failure_code"] in {"clarification_required", "unsupported_criteria"}:
        return "new_prompt_required", []
    if remaining_seconds(session, job) <= 0:
        return "deadline_expired", []
    plan = plan_for_job(session, job)
    cost, counters = current_usage(session, job["id"])
    unfinished = (
        session.execute(
            sa.select(attempts).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job["id"],
                attempts.c.state != "succeeded",
            )
        )
        .mappings()
        .all()
    )
    # Retrying an uncertain source/model operation needs an explicit reconciliation route.
    # Resume must not silently reissue a call whose charge or output is unknown.
    if any(row["state"] in {"failed", "cancelled", "running"} for row in unfinished):
        return "requires_reconciliation", unfinished
    # Exhausting discovery's search quota must not prevent already-discovered
    # candidates from using their independent fetch quota. Every actual call
    # still acquires its own atomic reservation before dispatch.
    stages = {row["stage"] for row in unfinished} or {
        job["stage"]
        or {
            "planning": "planning",
            "followup": "reporting",
            "owner_summary": "reporting",
            "template_repair": "extracting",
        }.get(job["purpose"], "discovering")
    }
    required = set().union(*(RESUME_DIMENSIONS.get(stage, set()) for stage in stages))
    if cost > plan.limits.currency_cap or any(
        counters[name] >= getattr(plan.limits, DIMENSIONS[name])
        for name in required
        if counters[name] > 0
    ):
        return "budget_exhausted", unfinished
    return "available", unfinished


def resume_readiness(session, job) -> ResumeStatus:
    """Advisory status only; resume repeats this check while holding the job lock."""
    return _resume_context(session, job)[0]


def resume(session, job_id, request_key):
    """Requeue permitted unfinished work without resetting usage or the original deadline."""
    if not request_key or len(request_key) > 200:
        raise ValueError("Bounded resume request key required")
    job = locked_job(session, job_id)
    if job["state"] not in {"paused", "queued", "running"}:
        raise ValueError("Only a paused job can be resumed")
    if job["state"] != "paused":
        return dict(job)
    readiness, unfinished = _resume_context(session, job)
    if readiness != "available":
        raise ValueError("Resume blocked: " + readiness)
    result = JobRepository.transition(session, job_id, "queued")
    if unfinished:
        for attempt in unfinished:
            JobRepository.enqueue(
                session,
                job_id,
                f"resume:{request_key}:{attempt['id']}",
                topic="execute_attempt",
                attempt_id=attempt["id"],
            )
    else:
        JobRepository.enqueue(session, job_id, f"resume:{request_key}")
    JobRepository.event(session, job_id, f"control:resume:{request_key}", "resume_requested")
    return result
