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
from skriller.db.schema import attempts, job_events, jobs, messages, reservations, stage_checkpoints
from skriller.extraction.models import ModelUnavailable
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile
from skriller.jobs.capacity import CapacityUnavailable
from skriller.jobs.control import permit_call
from skriller.jobs.outbox import submit
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


def create_clarification_job(session, source_job_id, answer, request_key):
    """Queue a new bounded planner attempt while retaining both user messages."""
    from hashlib import sha256

    from skriller.db.repositories import scope

    if not isinstance(answer, str) or not 1 <= len(answer.strip()) <= 500:
        raise ValueError("A clarification answer of 1–500 characters is required")
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 170:
        raise ValueError("Invalid clarification request key")
    key = "clarify:" + request_key
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "clarify:" + scope(session) + ":" + key},
    )
    digest = sha256(answer.strip().encode()).hexdigest()
    existing = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session), jobs.c.idempotency_key == key
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        details = session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.workspace_id == scope(session),
                job_events.c.job_id == existing["id"],
                job_events.c.event_key == "clarification_request",
            )
        ).scalar_one_or_none()
        if existing["created_by"] != session.info["actor_id"] or details != {
            "source_job_id": source_job_id,
            "answer_sha256": digest,
        }:
            raise ValueError("Clarification request key belongs to another answer")
        return dict(existing)
    source = JobRepository.get(session, source_job_id)
    if source is None:
        raise LookupError("Research run unavailable")
    if source["state"] != "paused" or source["failure_code"] != "clarification_required":
        raise ValueError("This run is not waiting for clarification")
    parent = ConversationRepository.get_plan(session, source["plan_id"])
    original = SearchPlan.model_validate(parent["interpretation"])
    if not original.clarification:
        raise ValueError("This plan has no outstanding clarification")
    messages_in_conversation = (
        session.execute(
            sa.select(messages.c.content)
            .where(
                messages.c.workspace_id == scope(session),
                messages.c.conversation_id == source["conversation_id"],
                messages.c.role == "user",
            )
            .order_by(messages.c.sequence)
        )
        .scalars()
        .all()
    )
    if not messages_in_conversation or len(messages_in_conversation) >= 4:
        raise ValueError("Clarification history exceeds the supported round limit")
    prompt_bytes = sum(len(item.encode()) for item in messages_in_conversation) + len(
        answer.strip().encode()
    )
    if (
        prompt_bytes > 3500
        or sum(len(item) for item in messages_in_conversation) + len(answer.strip()) > 3500
    ):
        raise ValueError("Clarification context exceeds the planner input limit")
    seed_limits = original.limits.model_copy(
        update={"llm_calls": 1, "token_cap": 4096, "fetch_attempts": 0}
    )
    seed = original.model_copy(
        update={
            "revision": original.revision + 1,
            "clarification": None,
            "limits": seed_limits,
        }
    )
    revision = ConversationRepository.revise_plan(
        session, source["conversation_id"], seed.model_dump(mode="json"), parent_id=parent["id"]
    )
    ConversationRepository.add_message(session, source["conversation_id"], "user", answer.strip())
    job = submit(session, source["conversation_id"], revision["id"], key)
    session.execute(
        sa.update(jobs)
        .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
        .values(purpose="planning")
    )
    JobRepository.event(
        session,
        job["id"],
        "clarification_request",
        "planning_clarification",
        {"source_job_id": source_job_id, "answer_sha256": digest},
    )
    for event_key in ("source_refinement", "refinement_context"):
        details = session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.workspace_id == scope(session),
                job_events.c.job_id == source_job_id,
                job_events.c.event_key == event_key,
            )
        ).scalar_one_or_none()
        if details is not None:
            JobRepository.event(session, job["id"], event_key, event_key, details)
    return {**job, "purpose": "planning"}


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
        prompt_messages = (
            session.execute(
                sa.select(messages.c.content)
                .where(
                    messages.c.workspace_id == scope(session),
                    messages.c.conversation_id == job["conversation_id"],
                    messages.c.role == "user",
                )
                .order_by(messages.c.sequence)
            )
            .scalars()
            .all()
        )
        prompt = "\n\n".join(prompt_messages)
        from skriller.research.refinements import model_context

        refinement = model_context(session, job["id"])
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
            attempt_id=identity.attempt_id,
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
                if refinement is not None:
                    from skriller.research.refinements import interpret_refinement

                    original, amendment = refinement
                    return await interpret_refinement(
                        planner,
                        database,
                        context,
                        original,
                        amendment,
                        server_scope.revision,
                        operation_key,
                    )
                return await planner.interpret(
                    database, context, prompt, server_scope, operation_key=operation_key
                )

        plan = asyncio.run(run())
        if settings.enable_page_extraction and refinement is None:
            plan = plan.model_copy(
                update={
                    "limits": plan.limits.model_copy(
                        update={
                            "fetch_attempts": min(30, plan.limits.result_limit * 3)
                            if settings.public_collection_proxy_url
                            else 0,
                            "llm_calls": min(10, plan.limits.result_limit * 2),
                            "token_cap": 40960,
                        }
                    )
                }
            )
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
