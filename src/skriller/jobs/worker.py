"""Fenced PostgreSQL checkpoints around trusted bounded stage handlers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from math import ceil, isfinite
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from celery import Celery
from pydantic import BaseModel, ConfigDict, Field

from skriller.contracts import Failure, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import attempts, external_calls, reservations, stage_checkpoints
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile, reserve
from skriller.jobs.capacity import CapacityUnavailable, acquire, release
from skriller.jobs.control import remaining_seconds
from skriller.jobs.state import STAGES


class TaskIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    job_id: UUID
    actor_id: str = Field(min_length=1, max_length=128)
    attempt_id: UUID | None = None


@dataclass(frozen=True)
class StageHandler:
    run: Callable
    persist: Callable
    maximum_cost: Decimal
    dimensions: dict
    lease_seconds: int = 120
    run_with_deadline: Callable | None = None
    capacity_kind: Literal["http", "browser", "model"] | None = None
    capacity_source: str = ""
    capacity_host: str = ""
    minimum_interval: float = 0
    feedback_failure: Callable | None = None


class CheckpointWorker:
    def __init__(self, database, handlers):
        if any(stage not in STAGES for stage in handlers):
            raise ValueError("Unknown trusted stage")
        for handler in handlers.values():
            if not 1 <= handler.lease_seconds <= 120:
                raise ValueError("Stage lease must be bounded")
            if handler.capacity_kind and (
                not handler.run_with_deadline
                or not handler.capacity_source
                or not handler.capacity_host
            ):
                raise ValueError("External stage capacity requires identity and deadline-aware I/O")
            if not isfinite(handler.minimum_interval) or not 0 <= handler.minimum_interval <= 86400:
                raise ValueError("Invalid source cadence")
        self.database, self.handlers = database, dict(handlers)

    def schedule(self, payload):
        identity = TaskIdentity.model_validate(payload)
        with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            plan = SearchPlan.model_validate(
                ConversationRepository.get_plan(session, job["plan_id"])["interpretation"]
            )
            if (
                str(plan.workspace_id) != scope(session)
                or str(plan.conversation_id) != job["conversation_id"]
            ):
                raise ValueError("Plan scope mismatch")
            if job["state"] != "queued":
                return {"status": "not_dispatchable"}
            stage = (
                "planning"
                if job["purpose"] == "planning"
                else "reporting"
                if job["purpose"] in {"followup", "owner_summary"}
                else "extracting"
                if job["purpose"] == "template_repair"
                else "discovering"
            )
            attempt = JobRepository.attempt(session, job["id"], f"{stage}:{plan.revision}", stage)
            JobRepository.enqueue(
                session,
                job["id"],
                f"attempt:{attempt['id']}",
                topic="execute_attempt",
                attempt_id=attempt["id"],
            )
            return {"status": "scheduled", "attempt_id": attempt["id"]}

    def execute(self, payload):
        identity = TaskIdentity.model_validate(payload)
        if identity.attempt_id is None:
            raise ValueError("Attempt identity required")
        with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            statement = sa.select(attempts).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job["id"],
                attempts.c.id == str(identity.attempt_id),
            )
            attempt = session.execute(statement.with_for_update()).mappings().one_or_none()
            if attempt is None:
                raise LookupError("Attempt unavailable")
            if attempt["state"] == "succeeded":
                return {"status": "checkpointed", "entity_ids": attempt["result_entity_ids"]}
            if job["state"] not in {"queued", "running"}:
                return {"status": "not_dispatchable"}
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            if attempt["state"] == "running" and attempt["lease_expires_at"] > now:
                return {"status": "leased"}
            handler = self.handlers.get(attempt["stage"])
            if handler is None:
                return {"status": "unsupported_operation"}
            if attempt["state"] in {"failed", "cancelled"}:
                return {"status": "not_dispatchable"}
            persisted = ConversationRepository.get_plan(session, job["plan_id"])
            plan = SearchPlan.model_validate(persisted["interpretation"])
            if (
                str(plan.workspace_id) != scope(session)
                or str(plan.conversation_id) != job["conversation_id"]
                or plan.revision != persisted["revision"]
            ):
                raise ValueError("Plan scope mismatch")
            if now >= job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds):
                JobRepository.transition(session, job["id"], "paused")
                return {"status": "deadline_exceeded"}
            from skriller.entitlements import execution_allowed

            if not execution_allowed(session, job["id"]):
                return {"status": "entitlement_blocked"}
            if attempt["reservation_id"]:
                previous = (
                    session.execute(
                        sa.select(reservations).where(
                            reservations.c.workspace_id == scope(session),
                            reservations.c.id == attempt["reservation_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                if previous["state"] == "held":
                    reconcile(session, job["id"], attempt["reservation_id"], status="estimated")
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.attempt_id == attempt["id"],
                        external_calls.c.state == "in_flight",
                    )
                    .values(state="uncertain", finished_at=now)
                )
            capacity = None
            if handler.capacity_kind:
                try:
                    capacity = acquire(
                        session,
                        job["id"],
                        kind=handler.capacity_kind,
                        source=handler.capacity_source,
                        host=handler.capacity_host,
                        ttl_seconds=min(
                            handler.lease_seconds, max(1, ceil(remaining_seconds(session, job)))
                        ),
                        minimum_interval=handler.minimum_interval,
                    )
                except CapacityUnavailable:
                    return {"status": "capacity_exhausted"}
            token = str(uuid4())
            generation = attempt["generation"] + 1
            try:
                reservation = reserve(
                    session,
                    job["id"],
                    f"attempt:{attempt['id']}:{token}",
                    handler.maximum_cost,
                    handler.dimensions,
                )
            except BudgetExhausted:
                if capacity:
                    release(session, capacity)
                JobRepository.transition(session, job["id"], "paused")
                return {"status": "budget_exhausted"}
            JobRepository.transition(session, job["id"], "running", stage=attempt["stage"])
            session.execute(
                sa.update(attempts)
                .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
                .values(
                    state="running",
                    lease_owner=token,
                    lease_expires_at=now + timedelta(seconds=handler.lease_seconds),
                    reservation_id=reservation["id"],
                    started_at=now,
                    generation=generation,
                )
            )
            call = insert_row(
                session,
                external_calls,
                job_id=job["id"],
                attempt_id=attempt["id"],
                generation=generation,
                operation_key="stage",
                reservation_id=reservation["id"],
                state="in_flight",
            )
            time_left = remaining_seconds(session, job)
        io_started = monotonic()
        io_ok = False
        stage_outcome = "succeeded"
        retry_headers = None
        try:
            # No database transaction remains open during source/model IO.
            if handler.run_with_deadline:
                timeout = min(time_left, handler.lease_seconds)
                if capacity:
                    timeout = min(timeout, capacity.deadline_monotonic - monotonic())
                if timeout <= 0:
                    raise TimeoutError("Execution window expired before source dispatch")
                data, actual_cost, actual_dimensions = handler.run_with_deadline(plan, timeout)
            else:
                data, actual_cost, actual_dimensions = handler.run(plan)
            io_ok = True
            if handler.feedback_failure:
                feedback = handler.feedback_failure(data)
                if isinstance(feedback, Failure):
                    io_ok = False
                    stage_outcome = feedback.code
                    if feedback.retry_after_seconds is not None:
                        retry_headers = {"Retry-After": str(feedback.retry_after_seconds)}
            io_elapsed = monotonic() - io_started
        except Exception as error:  # noqa: BLE001 - never persist raw page/provider exceptions
            io_elapsed = monotonic() - io_started
            failure = getattr(error, "failure", None)
            outcome = (
                failure.code
                if isinstance(failure, Failure)
                else "deadline_exceeded"
                if isinstance(error, TimeoutError)
                else "source_unavailable"
            )
            if isinstance(failure, Failure) and failure.retry_after_seconds is not None:
                retry_headers = {"Retry-After": str(failure.retry_after_seconds)}
            with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                locked_job(session, str(identity.job_id))
                reconcile(session, str(identity.job_id), reservation["id"], status="estimated")
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.id == call["id"],
                    )
                    .values(state="uncertain", finished_at=sa.func.clock_timestamp())
                )
                session.execute(
                    sa.update(attempts)
                    .where(
                        attempts.c.workspace_id == scope(session),
                        attempts.c.id == str(identity.attempt_id),
                        attempts.c.lease_owner == token,
                        attempts.c.state == "running",
                    )
                    .values(state="failed", finished_at=sa.func.clock_timestamp())
                )
                JobRepository.event(
                    session,
                    str(identity.job_id),
                    f"attempt:{token}:uncertain",
                    "external_call_uncertain",
                    {"attempt_id": str(identity.attempt_id), "reservation_id": reservation["id"]},
                )
                JobRepository.event(
                    session,
                    str(identity.job_id),
                    f"metrics:{identity.attempt_id}:{generation}",
                    "stage_observation",
                    {
                        "stage": attempt["stage"],
                        "source": handler.capacity_source,
                        "outcome": outcome,
                        "attempt_count": 1,
                        "attempt_id": str(identity.attempt_id),
                        "queue_wait_seconds": round(
                            max(0, (now - attempt["created_at"]).total_seconds()), 6
                        )
                        if generation == 1
                        else None,
                        "accepted_result_count": 0,
                        "stage_io_seconds": round(io_elapsed, 6),
                        "cost_usd": None,
                        "cost_status": "estimated",
                    },
                )
            return {"status": "source_unavailable"}
        finally:
            if capacity:
                with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                    release(
                        session,
                        capacity,
                        latency=monotonic() - io_started,
                        ok=io_ok,
                        headers=retry_headers,
                        minimum_interval=handler.minimum_interval,
                    )
        try:
            with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                job = locked_job(session, str(identity.job_id))
                row = session.execute(statement.with_for_update()).mappings().one()
                reconcile(
                    session,
                    job["id"],
                    reservation["id"],
                    status="confirmed",
                    cost=actual_cost,
                    actual_dimensions=actual_dimensions,
                )
                now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.id == call["id"],
                    )
                    .values(state="confirmed", finished_at=now)
                )
                if (
                    row["lease_owner"] != token
                    or row["lease_expires_at"] <= now
                    or job["state"] not in {"queued", "running"}
                ):
                    return {"status": "lease_lost"}
                if remaining_seconds(session, job) <= 0:
                    JobRepository.transition(session, job["id"], "paused")
                    session.execute(
                        sa.update(attempts)
                        .where(
                            attempts.c.workspace_id == scope(session), attempts.c.id == row["id"]
                        )
                        .values(state="failed", finished_at=now)
                    )
                    JobRepository.event(session, job["id"], "deadline:reached", "deadline_reached")
                    return {"status": "deadline_exceeded"}
                entity_ids = handler.persist(session, data)
                if (
                    not isinstance(entity_ids, list)
                    or len(entity_ids) > 300
                    or any(
                        ResearchRepository.get_entity(session, str(value)) is None
                        for value in entity_ids
                    )
                ):
                    raise ValueError("Checkpoint must reference bounded tenant-owned entities")
                entity_ids = [str(UUID(str(value))) for value in entity_ids]
                insert_row(
                    session,
                    stage_checkpoints,
                    job_id=job["id"],
                    attempt_id=row["id"],
                    generation=generation,
                    stage=row["stage"],
                    result_refs={"entity_ids": entity_ids},
                )
                session.execute(
                    sa.update(attempts)
                    .where(attempts.c.workspace_id == scope(session), attempts.c.id == row["id"])
                    .values(state="succeeded", result_entity_ids=entity_ids, finished_at=now)
                )
                JobRepository.event(
                    session,
                    job["id"],
                    f"attempt:{row['id']}:completed",
                    "stage_checkpointed",
                    {"attempt_id": row["id"], "entity_count": len(entity_ids)},
                )
                JobRepository.event(
                    session,
                    job["id"],
                    f"metrics:{row['id']}:{generation}",
                    "stage_observation",
                    {
                        "stage": row["stage"],
                        "source": handler.capacity_source,
                        "outcome": stage_outcome,
                        "attempt_count": 1,
                        "attempt_id": row["id"],
                        "queue_wait_seconds": round(
                            max(0, (now - attempt["created_at"]).total_seconds()), 6
                        )
                        if generation == 1
                        else None,
                        "accepted_result_count": len(entity_ids),
                        "stage_io_seconds": round(io_elapsed, 6),
                        "cost_usd": str(actual_cost),
                        "cost_status": "confirmed",
                    },
                )
                return {"status": "checkpointed", "entity_ids": entity_ids}

        except Exception:  # noqa: BLE001 - source/result errors must not enter diagnostics
            # Result persistence rolled back, but a completed external call still
            # consumed resources. Preserve that fact and stop automatic replay.
            # If commit actually succeeded before a transport error, return its
            # durable checkpoint rather than changing or charging it again.
            with self.database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                job = locked_job(session, str(identity.job_id))
                row = session.execute(statement.with_for_update()).mappings().one()
                if (
                    row["state"] == "succeeded"
                    and row["generation"] == generation
                    and row["lease_owner"] == token
                ):
                    return {"status": "checkpointed", "entity_ids": row["result_entity_ids"]}
                try:
                    receipt = reconcile(
                        session,
                        job["id"],
                        reservation["id"],
                        status="confirmed",
                        cost=actual_cost,
                        actual_dimensions=actual_dimensions,
                    )
                except (ValueError, TypeError, ArithmeticError):
                    # Invalid provider accounting cannot reduce the held ceiling.
                    receipt = reconcile(session, job["id"], reservation["id"], status="estimated")
                confirmed = receipt["reconciliation_status"] == "confirmed"
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.id == call["id"],
                    )
                    .values(
                        state="confirmed" if confirmed else "uncertain",
                        finished_at=sa.func.clock_timestamp(),
                    )
                )
                if row["lease_owner"] == token and row["state"] == "running":
                    session.execute(
                        sa.update(attempts)
                        .where(
                            attempts.c.id == row["id"], attempts.c.workspace_id == scope(session)
                        )
                        .values(state="failed", finished_at=sa.func.clock_timestamp())
                    )
                    if job["state"] in {"queued", "running"}:
                        JobRepository.transition(
                            session, job["id"], "paused", failure_code="checkpoint_failed"
                        )
                JobRepository.event(
                    session,
                    job["id"],
                    f"attempt:{token}:checkpoint_failed",
                    "checkpoint_failed",
                    {
                        "attempt_id": row["id"],
                        "reservation_id": reservation["id"],
                        "result_status": "not_committed",
                        "cost_status": "confirmed" if confirmed else "estimated",
                    },
                )
                JobRepository.event(
                    session,
                    job["id"],
                    f"metrics:{identity.attempt_id}:{generation}",
                    "stage_observation",
                    {
                        "stage": row["stage"],
                        "source": handler.capacity_source,
                        "outcome": "schema_invalid",
                        "attempt_count": 1,
                        "attempt_id": row["id"],
                        "accepted_result_count": 0,
                        "stage_io_seconds": round(io_elapsed, 6),
                        "cost_usd": str(receipt["actual_cost_usd"]) if confirmed else None,
                        "cost_status": "confirmed" if confirmed else "estimated",
                    },
                )
            return {"status": "checkpoint_failed"}


def create_worker_app(database, broker_url, handlers):
    worker = CheckpointWorker(database, handlers)
    app = Celery("skriller-worker", broker=broker_url)
    app.conf.update(
        task_default_queue="skriller.jobs",
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_enable_remote_control=False,
        worker_cancel_long_running_tasks_on_connection_loss=True,
        task_soft_time_limit=110,
        task_time_limit=120,
        broker_connection_retry_on_startup=False,
    )
    # These handlers belong to this configured app/database. Celery's default
    # shared lazy registration can copy generic handlers into another app and
    # overwrite the production research handlers during app finalization.
    app.task(name="skriller.jobs.execute_job", shared=False, lazy=False)(worker.schedule)
    app.task(name="skriller.jobs.execute_attempt", shared=False, lazy=False)(worker.execute)
    return app
