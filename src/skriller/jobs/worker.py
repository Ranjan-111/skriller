"""Short, generation-fenced stages with canonical PostgreSQL checkpoints.

Scrapling's supplied checkpoint/cache helpers were inspected: they persist pickled
requests or cookie-bearing disk responses, not transaction-scoped product records.
Existing vendor copies are preserved; this is new PostgreSQL integration glue.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from celery import Celery
from sqlalchemy.orm import Session

from skriller.contracts import ExecutionContext, SearchPlan
from skriller.db import Database
from skriller.db.repositories import (
    ConversationRepository,
    JobRepository,
    ResearchRepository,
    insert_row,
    scope,
)
from skriller.db.schema import attempts, external_calls, jobs, qualifications, stage_checkpoints
from skriller.jobs import budget
from skriller.jobs.state import TERMINAL_STATES, finish

STAGE_ORDER = ("discovering", "collecting", "extracting", "resolving", "qualifying")


class LeaseBusy(RuntimeError):
    """Another current worker owns this attempt."""


class LeaseLost(RuntimeError):
    """Expired or superseded worker must not write canonical results."""


class ExecutorUnavailable(RuntimeError):
    """No configured production source executor exists for this stage."""


class PreparedResult(Protocol):
    def commit(self, session: Session) -> dict[str, list[str]]: ...


class Executor(Protocol):
    def execute(self, context: "WorkerContext") -> PreparedResult: ...


@dataclass(frozen=True)
class Claim:
    context: ExecutionContext
    plan: SearchPlan
    attempt_id: str
    stage: str
    owner: str
    generation: int


@dataclass(frozen=True)
class ExternalResult:
    value: Any
    cost: Decimal
    dimensions: dict[str, int]


def payload_ids(payload: dict[str, str]) -> dict[str, str]:
    allowed = {"workspace_id", "job_id", "actor_id", "attempt_id"}
    if payload.keys() - allowed or not {"workspace_id", "job_id", "actor_id"} <= payload.keys():
        raise ValueError("Worker payload contains unsupported fields")
    actor = payload["actor_id"]
    if not isinstance(actor, str) or not actor or len(actor) > 128:
        raise ValueError("Verified actor identity required")
    return {key: actor if key == "actor_id" else str(UUID(value)) for key, value in payload.items()}


def _lock_attempt(session: Session, claim: Claim):
    job = budget.locked_job(session, str(claim.context.job_id))
    row = (
        session.execute(
            sa.select(attempts)
            .where(
                attempts.c.workspace_id == scope(session),
                attempts.c.id == claim.attempt_id,
                attempts.c.job_id == str(claim.context.job_id),
            )
            .with_for_update()
        )
        .mappings()
        .one()
    )
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if (
        job["state"] != "running"
        or row["state"] != "running"
        or row["generation"] != claim.generation
        or row["lease_owner"] != claim.owner
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= now
    ):
        raise LeaseLost("Worker lease no longer permits writes")
    return row


class WorkerContext:
    def __init__(self, worker: "StageWorker", claim: Claim):
        self.worker, self.claim = worker, claim
        self.plan, self.execution = claim.plan, claim.context

    def external_call(
        self,
        operation_key: str,
        maximum_cost: Decimal,
        dimensions: dict[str, int],
        call: Callable[[], ExternalResult],
    ) -> Any:
        """Reserve/audit before calling; unknown charges remain explicitly estimated."""
        if not operation_key or len(operation_key) > 200:
            raise ValueError("Bounded logical operation key required")
        claim = self.claim
        job_id = str(claim.context.job_id)
        with self.worker.database.tenant(
            claim.context.actor_id, str(claim.context.workspace_id)
        ) as session:
            _lock_attempt(session, claim)
            reservation = budget.reserve(
                session,
                job_id,
                f"call:{claim.attempt_id}:{claim.generation}:{operation_key}",
                maximum_cost,
                dimensions,
            )
            audit = insert_row(
                session,
                external_calls,
                job_id=job_id,
                attempt_id=claim.attempt_id,
                generation=claim.generation,
                operation_key=operation_key,
                reservation_id=reservation["id"],
                state="in_flight",
            )
        try:
            response = call()
        except BaseException:
            with self.worker.database.tenant(
                claim.context.actor_id, str(claim.context.workspace_id)
            ) as session:
                budget.reconcile(session, job_id, reservation["id"], status="estimated")
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.id == audit["id"],
                    )
                    .values(state="uncertain", finished_at=sa.func.now())
                )
            raise
        with self.worker.database.tenant(
            claim.context.actor_id, str(claim.context.workspace_id)
        ) as session:
            # Provider charges are recorded truthfully even if this worker's lease
            # expired during the call; canonical result writes remain separately fenced.
            budget.reconcile(
                session,
                job_id,
                reservation["id"],
                status="confirmed",
                cost=response.cost,
                actual_dimensions=response.dimensions,
            )
            session.execute(
                sa.update(external_calls)
                .where(
                    external_calls.c.workspace_id == scope(session),
                    external_calls.c.id == audit["id"],
                )
                .values(state="confirmed", finished_at=sa.func.now())
            )
        return response.value


class StageWorker:
    def __init__(
        self, database: Database, executors: dict[str, Executor], *, lease_seconds: int = 40
    ):
        if not 1 <= lease_seconds <= 60 or executors.keys() - set(STAGE_ORDER):
            raise ValueError("Bounded leases and known stage executors required")
        self.database, self.executors, self.lease_seconds = database, executors, lease_seconds

    def claim(self, payload: dict[str, str]) -> Claim | dict:
        ids = payload_ids(payload)
        with self.database.tenant(ids["actor_id"], ids["workspace_id"]) as session:
            job = budget.locked_job(session, ids["job_id"])
            if job["state"] in TERMINAL_STATES:
                return {"status": "terminal", "state": job["state"]}
            if job["state"] not in {"queued", "running"}:
                raise LeaseBusy("Job is paused or awaiting a connection")
            persisted = ConversationRepository.get_plan(session, job["plan_id"])
            plan = SearchPlan.model_validate(persisted["interpretation"])
            if (
                str(plan.workspace_id) != ids["workspace_id"]
                or str(plan.conversation_id) != job["conversation_id"]
                or plan.revision != persisted["revision"]
            ):
                raise ValueError("Immutable plan does not match job")
            if "attempt_id" in ids:
                attempt = (
                    session.execute(
                        sa.select(attempts)
                        .where(
                            attempts.c.workspace_id == scope(session),
                            attempts.c.job_id == job["id"],
                            attempts.c.id == ids["attempt_id"],
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if attempt is None:
                    raise LookupError("Attempt unavailable")
            else:
                stage = job["stage"] or STAGE_ORDER[0]
                attempt = JobRepository.attempt(session, job["id"], f"stage:{stage}", stage)
            checkpoint = (
                session.execute(
                    sa.select(stage_checkpoints).where(
                        stage_checkpoints.c.workspace_id == scope(session),
                        stage_checkpoints.c.attempt_id == attempt["id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if checkpoint:
                return {"status": "replayed", "result_refs": checkpoint["result_refs"]}
            stage = attempt["stage"]
            if stage != (job["stage"] or STAGE_ORDER[0]):
                raise LeaseLost("Attempt stage is no longer current")
            if stage not in self.executors:
                raise ExecutorUnavailable(f"No configured executor for {stage}")
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            deadline = job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds)
            if now >= deadline:
                retained = session.execute(
                    sa.select(sa.func.count())
                    .select_from(qualifications)
                    .where(
                        qualifications.c.workspace_id == scope(session),
                        qualifications.c.plan_id == job["plan_id"],
                    )
                ).scalar_one()
                finish(
                    session,
                    job["id"],
                    outcome="deadline_limit",
                    retained_results=retained,
                    expected_version=job["version"],
                )
                return {"status": "deadline_limit"}
            if attempt["lease_expires_at"] is not None and attempt["lease_expires_at"] > now:
                raise LeaseBusy("Attempt has an active lease")
            previous_calls = (
                session.execute(
                    sa.select(external_calls).where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.attempt_id == attempt["id"],
                        external_calls.c.state == "in_flight",
                    )
                )
                .mappings()
                .all()
            )
            for audit in previous_calls:
                budget.reconcile(session, job["id"], audit["reservation_id"], status="estimated")
                session.execute(
                    sa.update(external_calls)
                    .where(
                        external_calls.c.workspace_id == scope(session),
                        external_calls.c.id == audit["id"],
                    )
                    .values(state="uncertain", finished_at=sa.func.now())
                )
            owner, generation = str(uuid4()), attempt["generation"] + 1
            session.execute(
                sa.update(attempts)
                .where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.id == attempt["id"],
                )
                .values(
                    state="running",
                    lease_owner=owner,
                    generation=generation,
                    lease_expires_at=min(now + timedelta(seconds=self.lease_seconds), deadline),
                    started_at=sa.func.now(),
                    finished_at=None,
                )
            )
            JobRepository.transition(session, job["id"], "running", stage=stage)
            return Claim(
                ExecutionContext(
                    workspace_id=UUID(ids["workspace_id"]),
                    job_id=job["id"],
                    actor_id=ids["actor_id"],
                    plan_revision=plan.revision,
                    deadline=deadline,
                    attempt_budget=plan.limits.fetch_attempts,
                ),
                plan,
                attempt["id"],
                stage,
                owner,
                generation,
            )

    def recover_expired(self, actor_id: str, workspace_id: str, *, limit: int = 20) -> int:
        """Durably requeue expired leases; scheduler calls this per trusted tenant."""
        if not 1 <= limit <= 100:
            raise ValueError("Bounded recovery batch required")
        recovered = 0
        with self.database.tenant(actor_id, workspace_id) as session:
            candidates = session.execute(
                sa.select(attempts.c.id, attempts.c.job_id)
                .join(
                    jobs,
                    sa.and_(
                        jobs.c.workspace_id == attempts.c.workspace_id,
                        jobs.c.id == attempts.c.job_id,
                    ),
                )
                .where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.state == "running",
                    attempts.c.lease_expires_at <= sa.func.clock_timestamp(),
                    jobs.c.state == "running",
                )
                .limit(limit)
            ).all()
        for attempt_id, job_id in candidates:
            with self.database.tenant(actor_id, workspace_id) as session:
                job = budget.locked_job(session, job_id)
                row = (
                    session.execute(
                        sa.select(attempts)
                        .where(
                            attempts.c.workspace_id == scope(session),
                            attempts.c.id == attempt_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
                if (
                    job["state"] != "running"
                    or row["state"] != "running"
                    or (row["lease_expires_at"] is None or row["lease_expires_at"] > now)
                ):
                    continue
                JobRepository.enqueue(
                    session,
                    job_id,
                    f"lease:{attempt_id}:{row['generation']}",
                    topic="execute_attempt",
                    attempt_id=attempt_id,
                )
                JobRepository.event(
                    session,
                    job_id,
                    f"lease:{attempt_id}:{row['generation']}",
                    "lease_expired",
                    {"attempt_id": attempt_id, "generation": row["generation"]},
                )
                recovered += 1
        return recovered

    def complete(self, claim: Claim, result: PreparedResult) -> dict:
        with self.database.tenant(
            claim.context.actor_id, str(claim.context.workspace_id)
        ) as session:
            _lock_attempt(session, claim)
            refs = result.commit(session)
            if refs.keys() - {"entity_ids", "evidence_ids"} or sum(map(len, refs.values())) > 300:
                raise ValueError("Checkpoint requires bounded canonical result references")
            for name, lookup in (
                ("entity_ids", ResearchRepository.get_entity),
                ("evidence_ids", ResearchRepository.get_evidence),
            ):
                for reference in refs.get(name, []):
                    if lookup(session, str(UUID(reference))) is None:
                        raise ValueError("Checkpoint result reference unavailable")
            insert_row(
                session,
                stage_checkpoints,
                job_id=str(claim.context.job_id),
                attempt_id=claim.attempt_id,
                generation=claim.generation,
                stage=claim.stage,
                result_refs=refs,
            )
            session.execute(
                sa.update(attempts)
                .where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.id == claim.attempt_id,
                )
                .values(
                    state="succeeded",
                    finished_at=sa.func.now(),
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            JobRepository.event(
                session,
                str(claim.context.job_id),
                f"checkpoint:{claim.attempt_id}",
                "stage_completed",
                {"attempt_id": claim.attempt_id, "stage": claim.stage},
            )
            index = STAGE_ORDER.index(claim.stage)
            if index + 1 < len(STAGE_ORDER):
                following = STAGE_ORDER[index + 1]
                next_attempt = JobRepository.attempt(
                    session, str(claim.context.job_id), f"stage:{following}", following
                )
                JobRepository.transition(
                    session, str(claim.context.job_id), "running", stage=following
                )
                JobRepository.enqueue(
                    session,
                    str(claim.context.job_id),
                    f"stage:{next_attempt['id']}",
                    topic="execute_attempt",
                    attempt_id=next_attempt["id"],
                )
            else:
                current = JobRepository.get(session, str(claim.context.job_id))
                finish(
                    session,
                    str(claim.context.job_id),
                    outcome="source_exhausted",
                    retained_results=0,
                    expected_version=current["version"],
                )
            return {"status": "completed", "result_refs": refs}

    def execute(self, payload: dict[str, str]) -> dict:
        claim = self.claim(payload)
        if isinstance(claim, dict):
            return claim
        result = self.executors[claim.stage].execute(WorkerContext(self, claim))
        return self.complete(claim, result)


def register_tasks(app: Celery, worker: StageWorker) -> None:
    def execute(payload):
        try:
            return worker.execute(payload)
        except LeaseBusy:
            # Another delivery is running; persisted lease/outbox recovery owns retry.
            return {"status": "leased"}

    for name in ("skriller.jobs.execute_job", "skriller.jobs.execute_attempt"):
        app.task(
            name=name, acks_late=True, reject_on_worker_lost=True, soft_time_limit=30, time_limit=40
        )(execute)
