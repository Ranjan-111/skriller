"""Fenced PostgreSQL checkpoints around trusted bounded stage handlers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from celery import Celery
from pydantic import BaseModel, ConfigDict, Field

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import attempts, external_calls, reservations, stage_checkpoints
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile, reserve
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


class CheckpointWorker:
    def __init__(self, database, handlers):
        if any(stage not in STAGES for stage in handlers):
            raise ValueError("Unknown trusted stage")
        for handler in handlers.values():
            if not 1 <= handler.lease_seconds <= 120:
                raise ValueError("Stage lease must be bounded")
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
            attempt = JobRepository.attempt(
                session, job["id"], f"discovering:{plan.revision}", "discovering"
            )
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
        try:
            # No database transaction remains open during source/model IO.
            data, actual_cost, actual_dimensions = handler.run(plan)
        except Exception:  # noqa: BLE001 - never persist raw page/provider exceptions
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
            return {"status": "source_unavailable"}
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
            return {"status": "checkpointed", "entity_ids": entity_ids}


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
    app.task(name="skriller.jobs.execute_job")(worker.schedule)
    app.task(name="skriller.jobs.execute_attempt")(worker.execute)
    return app
