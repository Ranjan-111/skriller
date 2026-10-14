"""One durable prompt-planning call before discovery, disabled by default.

The existing PromptPlanner and metered model own model I/O/accounting. A worker
lease fences plan writes. A lost call is surfaced for human review, never retried
with another model/provider or disguised as successful empty research.
"""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa

from skriller.contracts import ExecutionContext, SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import attempts, jobs, messages, reservations, stage_checkpoints
from skriller.extraction.models import ModelUnavailable
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile
from skriller.jobs.capacity import CapacityUnavailable
from skriller.jobs.control import permit_call
from skriller.jobs.worker import TaskIdentity
from skriller.research.planner import PlanningInvalid, PlanScope, PromptPlanner


def _attempt(session, identity):
    row = (
        session.execute(
            sa.select(attempts)
            .where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == str(identity.job_id),
                attempts.c.id == str(identity.attempt_id),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["stage"] != "planning":
        raise LookupError("Planning attempt unavailable")
    return row


def _summary(session, job_id, attempt_id, status):
    JobRepository.event(
        session, job_id, f"planning:{attempt_id}", "planning_summary", {"status": status}
    )


def execute_planning(database, payload, settings, model=None):
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Planning attempt identity required")
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = _attempt(session, identity)
        if attempt["state"] == "succeeded":
            return {"status": "checkpointed"}
        if job["purpose"] != "planning" or job["state"] not in {"queued", "running"}:
            return {"status": "not_dispatchable"}
        if not settings.enable_ai_planning:
            JobRepository.transition(session, job["id"], "paused", failure_code="planning_disabled")
            _summary(session, job["id"], attempt["id"], "planning_disabled")
            return {"status": "planning_disabled"}
        if not permit_call(session, job["id"]):
            return {"status": "deadline_exceeded"}
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if attempt["state"] == "running" and attempt["lease_expires_at"] > now:
            return {"status": "leased"}
        if attempt["state"] in {"failed", "cancelled"}:
            return {"status": "not_dispatchable"}
        operation_key = f"planning:{attempt['id']}"
        previous = (
            session.execute(
                sa.select(reservations).where(
                    reservations.c.workspace_id == scope(session),
                    reservations.c.job_id == job["id"],
                    reservations.c.idempotency_key == operation_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous:
            if previous["state"] == "held":
                reconcile(session, job["id"], previous["id"], status="estimated")
            JobRepository.transition(
                session, job["id"], "paused", failure_code="planning_interrupted"
            )
            _summary(session, job["id"], attempt["id"], "planning_interrupted")
            return {"status": "planning_interrupted"}
        parent = ConversationRepository.get_plan(session, job["plan_id"])
        seed = SearchPlan.model_validate(parent["interpretation"])
        if (
            seed.limits.llm_calls != 1
            or seed.limits.token_cap != 4096
            or seed.limits.fetch_attempts != 0
            or seed.limits.currency_cap != 0
        ):
            raise ValueError("Planning bootstrap requires explicit bounded server seed")
        prompt = session.execute(
            sa.select(messages.c.content)
            .where(
                messages.c.workspace_id == scope(session),
                messages.c.conversation_id == job["conversation_id"],
                messages.c.role == "user",
            )
            .order_by(messages.c.sequence)
            .limit(1)
        ).scalar_one()
        token, generation = str(uuid4()), attempt["generation"] + 1
        session.execute(
            sa.update(attempts)
            .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
            .values(
                state="running",
                lease_owner=token,
                lease_expires_at=now + timedelta(seconds=95),
                generation=generation,
                started_at=now,
            )
        )
        JobRepository.transition(session, job["id"], "running", stage="planning")
        context = ExecutionContext(
            workspace_id=identity.workspace_id,
            job_id=identity.job_id,
            actor_id=identity.actor_id,
            plan_revision=seed.revision,
            deadline=job["created_at"] + timedelta(seconds=seed.limits.deadline_seconds),
            attempt_budget=1,
        )
        server_scope = PlanScope(
            workspace_id=identity.workspace_id,
            conversation_id=UUID(job["conversation_id"]),
            revision=seed.revision + 1,
            limits=seed.limits,
            allowed_sources=seed.sources,
        )
    failure = None
    try:

        async def run():
            async with PromptPlanner(model, settings=settings) as planner:
                return await planner.interpret(
                    database, context, prompt, server_scope, operation_key=operation_key
                )

        plan = asyncio.run(run())
    except CapacityUnavailable:
        failure = "capacity_exhausted"
    except BudgetExhausted:
        failure = "budget_exhausted"
    except ModelUnavailable as exc:
        failure = exc.failure.code
    except PlanningInvalid as exc:
        failure = exc.reason
    except Exception:  # noqa: BLE001 - no provider prompts/details in durable diagnostics
        failure = "planning_interrupted"
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = _attempt(session, identity)
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            attempt["lease_owner"] != token
            or attempt["lease_expires_at"] <= now
            or job["state"] not in {"queued", "running"}
            or not permit_call(session, job["id"])
        ):
            return {"status": "lost_lease"}
        if failure == "capacity_exhausted":
            session.execute(
                sa.update(attempts)
                .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
                .values(state="pending", lease_owner=None, lease_expires_at=None)
            )
            return {"status": failure}
        if failure:
            session.execute(
                sa.update(attempts)
                .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
                .values(state="failed", finished_at=now)
            )
            JobRepository.transition(session, job["id"], "paused", failure_code=failure)
            _summary(session, job["id"], attempt["id"], failure)
            return {"status": failure}
        if job["plan_id"] != parent["id"]:
            raise ValueError("Planning parent changed during execution")
        revision = ConversationRepository.revise_plan(
            session, job["conversation_id"], plan.model_dump(mode="json"), parent_id=parent["id"]
        )
        session.execute(
            sa.update(jobs)
            .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
            .values(plan_id=revision["id"], purpose="research")
        )
        insert_row(
            session,
            stage_checkpoints,
            job_id=job["id"],
            attempt_id=attempt["id"],
            stage="planning",
            generation=generation,
            result_refs={"plan_id": revision["id"]},
        )
        session.execute(
            sa.update(attempts)
            .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
            .values(state="succeeded", finished_at=now, result_entity_ids=[])
        )
        status = (
            "clarification_required"
            if plan.clarification
            else "unsupported_criteria"
            if plan.unsupported_criteria
            else "ready"
        )
        _summary(session, job["id"], attempt["id"], status)
        if status != "ready":
            JobRepository.transition(
                session, job["id"], "paused", stage="planning", failure_code=status
            )
        else:
            JobRepository.transition(session, job["id"], "running", stage="discovering")
            next_attempt = JobRepository.attempt(
                session, job["id"], f"discovering:{plan.revision}", "discovering"
            )
            JobRepository.enqueue(
                session,
                job["id"],
                f"attempt:{next_attempt['id']}",
                topic="execute_attempt",
                attempt_id=next_attempt["id"],
            )
        return {"status": "checkpointed", "planning_status": status, "plan_id": revision["id"]}
