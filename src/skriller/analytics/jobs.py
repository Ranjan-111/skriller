"""Private summary admission and opaque checkpoint orchestration.

Adapted from research.followups: shared job/outbox/budget machinery is retained;
private report requests and answers are stored only in the encrypted owner table.
"""

import asyncio
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import sqlalchemy as sa

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.private_jobs import PrivateSummaryStore
from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import attempts, jobs
from skriller.entitlements import policy_for, used_runs
from skriller.jobs.budget import locked_job
from skriller.jobs.control import cancel, permit_call, plan_for_job
from skriller.jobs.outbox import submit
from skriller.jobs.worker import TaskIdentity


def request_value(grant_id, request):
    return {"grant_id": str(grant_id), **request.model_dump(mode="json")}


def request_key(session, key):
    if not isinstance(key, str) or not 1 <= len(key) <= 170:
        raise ValueError("Bounded summary request key required")
    # Do not persist caller text in the workspace-visible job record.
    digest = sha256((session.info["actor_id"] + ":" + key).encode()).hexdigest()
    return "owner-summary:" + digest


def existing_summary(session, store, grant_id, request, key):
    require_owner(session)
    opaque = request_key(session, key)
    row = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session), jobs.c.idempotency_key == opaque
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    private = store.get(session, row["id"])
    if store._open(private).get("request") != request_value(grant_id, request):
        raise ValueError("Summary key belongs to another request")
    return dict(row)


def create_summary(session, store, verified, request, key):
    require_owner(session)
    opaque = request_key(session, key)
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": scope(session) + ":" + opaque},
    )
    existing = existing_summary(session, store, verified.report.grant_id, request, key)
    if existing:
        return existing
    policy = policy_for(session)
    if not policy["enabled"] or used_runs(session) >= policy["run_limit"]:
        raise AnalyticsUnavailable("analytics_run_allowance_exhausted")
    conversation = ConversationRepository.create(session, "Owner summary")
    plan = SearchPlan(
        workspace_id=UUID(scope(session)),
        conversation_id=UUID(conversation["id"]),
        revision=1,
        entity_type="creator",
        sources=[],
        limits=Limits(
            result_limit=1,
            search_calls=0,
            fetch_attempts=0,
            llm_calls=1,
            token_cap=4096,
            deadline_seconds=120,
        ),
    )
    revision = ConversationRepository.revise_plan(
        session, conversation["id"], plan.model_dump(mode="json")
    )
    job = submit(session, conversation["id"], revision["id"], opaque)
    session.execute(
        sa.update(jobs)
        .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
        .values(purpose="owner_summary")
    )
    store.save(
        session, job["id"], verified, request=request_value(verified.report.grant_id, request)
    )
    return {**job, "purpose": "owner_summary"}


def summary_view(session, store, job_id):
    result = store.result(session, job_id)
    job = JobRepository.get(session, str(job_id))
    return {
        "job_id": str(job_id),
        "state": job["state"],
        "summary_state": result["state"],
        "result": result["result"],
    }


def cancel_summary(session, store, job_id):
    # Check private ownership before mutating the shared accounting job.
    store.get(session, job_id)
    locked_job(session, str(job_id))
    store.cancel(session, job_id)
    cancel(session, str(job_id))
    return summary_view(session, store, job_id)


def execute_summary(database, payload, store: PrivateSummaryStore, *, model=None):
    """One bounded lease; replay never repeats an uncertain private model call."""
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Summary attempt required")
    workspace, job_id = str(identity.workspace_id), str(identity.job_id)
    with database.tenant(identity.actor_id, workspace) as session:
        job = locked_job(session, job_id)
        attempt = (
            session.execute(
                sa.select(attempts)
                .where(
                    attempts.c.workspace_id == workspace,
                    attempts.c.job_id == job_id,
                    attempts.c.id == str(identity.attempt_id),
                    attempts.c.stage == "reporting",
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            attempt is None
            or job["purpose"] != "owner_summary"
            or job["created_by"] != identity.actor_id
        ):
            return {"status": "not_dispatchable"}
        if attempt["state"] == "succeeded":
            return {"status": "checkpointed"}
        if job["state"] not in {"queued", "running"}:
            return {"status": "not_dispatchable"}
        current = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if attempt["state"] == "running":
            if attempt["lease_expires_at"] > current:
                return {"status": "leased"}
            store.discard(session, job_id)
            JobRepository.transition(session, job_id, "paused", failure_code="summary_interrupted")
            return {"status": "summary_interrupted"}
        if attempt["state"] != "pending" or not permit_call(session, job_id):
            return {"status": "not_dispatchable"}
        token = str(uuid4())
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == str(identity.attempt_id))
            .values(
                state="running",
                lease_owner=token,
                started_at=current,
                lease_expires_at=current + timedelta(seconds=115),
                generation=attempt["generation"] + 1,
            )
        )
        JobRepository.transition(session, job_id, "running", stage="reporting")
        plan = plan_for_job(session, job)
        context = ExecutionContext(
            workspace_id=identity.workspace_id,
            job_id=identity.job_id,
            actor_id=identity.actor_id,
            plan_revision=plan.revision,
            deadline=job["created_at"] + timedelta(seconds=120),
            attempt_budget=1,
        )
    try:
        state = asyncio.run(store.execute(database, context, model=model))
    except Exception:  # noqa: BLE001 - no model/report/secret details in durable diagnostics
        state = "failed"
    with database.tenant(identity.actor_id, workspace) as session:
        job = locked_job(session, job_id)
        attempt = (
            session.execute(
                sa.select(attempts)
                .where(
                    attempts.c.workspace_id == workspace, attempts.c.id == str(identity.attempt_id)
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if job["state"] not in {"queued", "running"}:
            store.discard(session, job_id)
            return {"status": "not_dispatchable"}
        if attempt["lease_owner"] != token:
            return {"status": "not_dispatchable"}
        if (
            state != "completed"
            or attempt["lease_expires_at"]
            <= session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        ):
            session.execute(
                sa.update(attempts)
                .where(attempts.c.id == str(identity.attempt_id))
                .values(state="failed", finished_at=sa.func.clock_timestamp())
            )
            store.discard(session, job_id)
            JobRepository.transition(session, job_id, "paused", failure_code="summary_interrupted")
            return {"status": "summary_interrupted"}
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == str(identity.attempt_id))
            .values(state="succeeded", finished_at=sa.func.clock_timestamp(), result_entity_ids=[])
        )
        JobRepository.transition(session, job_id, "completed", stage="reporting")
        return {"status": "checkpointed"}
