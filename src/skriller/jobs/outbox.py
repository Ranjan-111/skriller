"""ID-only transactional submissions and at-least-once confirmed publication."""

from dataclasses import dataclass
from typing import ClassVar, Protocol
from urllib.parse import urlsplit

import sqlalchemy as sa
from celery import Celery
from sqlalchemy.orm import Session

from skriller.contracts import SearchPlan
from skriller.db import Database
from skriller.db.repositories import JobRepository, scope
from skriller.db.schema import outbox


class Publisher(Protocol):
    def publish(self, message_id: str, topic: str, payload: dict[str, str]) -> None: ...


class CeleryPublisher:
    """Bounded broker publication, durable queue, RabbitMQ publisher confirms.

    The memory transport is useful for local protocol tests but offers no durable
    broker guarantee. Production requires an actual RabbitMQ transport.
    """

    TOPICS: ClassVar[dict[str, str]] = {
        "execute_job": "skriller.jobs.execute_job",
        "execute_attempt": "skriller.jobs.execute_attempt",
        "cancel_job": "skriller.jobs.cancel_job",
    }

    def __init__(self, broker_url: str, *, allow_memory: bool = False):
        if urlsplit(broker_url).scheme not in {"amqp", "amqps", "memory"}:
            raise ValueError("Publisher requires RabbitMQ transport")
        if broker_url.startswith("memory:") and not allow_memory:
            raise ValueError("Memory transport requires explicit test opt-in")
        # Publishing from inside a worker must not replace its current Celery
        # app: task deserialization would then resolve against a publisher-only
        # task registry (or an unrelated generic handler).
        self.app = Celery("skriller-dispatch", broker=broker_url, set_as_current=False)
        self.app.conf.update(
            task_default_queue="skriller.jobs",
            task_default_delivery_mode="persistent",
            broker_connection_timeout=5,
            broker_transport_options={"confirm_publish": True, "write_timeout": 5},
            task_publish_retry=False,
            task_serializer="json",
            accept_content=["json"],
        )

    def publish(self, message_id: str, topic: str, payload: dict[str, str]) -> None:
        if topic not in self.TOPICS:
            raise ValueError("Unsupported outbox topic")
        allowed = {"workspace_id", "job_id", "actor_id", "attempt_id"}
        if not {"workspace_id", "job_id", "actor_id"} <= payload.keys() or payload.keys() - allowed:
            raise ValueError("Broker payload must contain only required opaque IDs")
        # With RabbitMQ confirm_publish, send_task returns after broker confirmation;
        # any publish failure propagates before the PostgreSQL published_at write.
        self.app.send_task(
            self.TOPICS[topic],
            args=[payload],
            task_id=message_id,
            queue="skriller.jobs",
            delivery_mode=2,
            retry=False,
        )


def submit(session: Session, conversation_id: str, plan_id: str, request_key: str) -> dict:
    """Caller commits job, queued-state event, and outbox in one tenant transaction."""
    if not request_key or len(request_key) > 200:
        raise ValueError("Request idempotency key must contain 1–200 characters")
    from skriller.db.repositories import ConversationRepository

    revision = ConversationRepository.get_plan(session, plan_id)
    if revision is None:
        raise LookupError("Plan unavailable")
    plan = SearchPlan.model_validate(revision["interpretation"])
    if str(plan.workspace_id) != scope(session) or str(plan.conversation_id) != conversation_id:
        raise ValueError("Plan scope does not match submission")
    if plan.revision != revision["revision"]:
        raise ValueError("Plan revision does not match immutable record")
    job = JobRepository.create(session, conversation_id, plan_id, request_key)
    if job["state"] == "planned":
        job = JobRepository.transition(
            session, job["id"], "queued", expected_version=job["version"]
        )
    JobRepository.enqueue(session, job["id"], f"run:{job['id']}")
    return job


@dataclass(frozen=True)
class DispatchScope:
    actor_id: str
    workspace_id: str


class OutboxDispatcher:
    """One bounded publication per PostgreSQL transaction with SKIP LOCKED.

    A crash after broker confirmation but before commit replays the same message ID.
    Workers must therefore deduplicate delivery/checkpointing (SKR-022).
    Dispatcher receives trusted tenant scopes; no owner-role bypass is used.
    """

    def __init__(self, database: Database, publisher: Publisher):
        self.database, self.publisher = database, publisher

    def dispatch_one(self, identity: DispatchScope) -> str | None:
        with self.database.tenant(identity.actor_id, identity.workspace_id) as session:
            row = (
                session.execute(
                    sa.select(outbox)
                    .where(
                        outbox.c.workspace_id == scope(session),
                        outbox.c.published_at.is_(None),
                        outbox.c.discarded_at.is_(None),
                    )
                    .order_by(outbox.c.created_at, outbox.c.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            if row["topic"] in {"execute_job", "execute_attempt"}:
                from skriller.entitlements import execution_allowed
                from skriller.jobs.budget import locked_job

                job = locked_job(session, row["job_id"])
                if job["state"] not in {"queued", "running"} or not execution_allowed(
                    session, row["job_id"]
                ):
                    session.execute(
                        sa.update(outbox)
                        .where(outbox.c.workspace_id == scope(session), outbox.c.id == row["id"])
                        .values(discarded_at=sa.func.clock_timestamp())
                    )
                    return str(row["id"])
            self.publisher.publish(str(row["id"]), row["topic"], JobRepository.broker_payload(row))
            session.execute(
                sa.update(outbox)
                .where(
                    outbox.c.workspace_id == scope(session),
                    outbox.c.id == row["id"],
                )
                .values(published_at=sa.func.now())
            )
            return str(row["id"])

    def dispatch_batch(self, identity: DispatchScope, *, limit: int = 20) -> int:
        """Count processed records, including explicit nonpublished discards."""
        if not 1 <= limit <= 100:
            raise ValueError("Publication batch must contain 1–100 messages")
        count = 0
        for _ in range(limit):
            if self.dispatch_one(identity) is None:
                break
            count += 1
        return count
