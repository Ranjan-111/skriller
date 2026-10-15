from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa

from skriller.contracts import Failure, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.schema import attempts
from skriller.jobs.budget import current_usage
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker, StageHandler

pytestmark = pytest.mark.integration_db


def context(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Worker")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Work")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        attempt = JobRepository.attempt(session, job["id"], "discover:1", "discovering")
    return {
        "actor_id": actor,
        "workspace_id": workspace,
        "job_id": job["id"],
        "attempt_id": attempt["id"],
    }


def handler(run):
    def persist(session, data):
        return [ResearchRepository.entity(session, "company", display_name=data)["id"]]

    return StageHandler(run, persist, Decimal(0), {"llm_calls": 1, "tokens": 10})


def test_redelivery_after_checkpoint_before_ack_never_duplicates_results(database):
    payload = context(database)
    calls = []

    def run(plan):
        calls.append(plan.revision)
        return "Aurora", 0, {"llm_calls": 1, "tokens": 5}

    worker = CheckpointWorker(database, {"discovering": handler(run)})
    first = worker.execute(payload)
    assert first["status"] == "checkpointed"
    assert worker.execute(payload) == first
    assert calls == [1]
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 1
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 5
        metrics = [
            row
            for row in JobRepository.events_after(session, payload["job_id"])
            if row["kind"] == "stage_observation"
        ]
        assert len(metrics) == 1
        assert metrics[0]["details"]["outcome"] == "succeeded"
        assert metrics[0]["details"]["attempt_count"] == 1
        assert metrics[0]["details"]["accepted_result_count"] == 1
        assert metrics[0]["details"]["cost_usd"] == "0"
        assert metrics[0]["details"]["attempt_id"] == payload["attempt_id"]
        assert metrics[0]["details"]["queue_wait_seconds"] >= 0


def test_expired_owner_recovery_fences_old_work_and_accounts_uncertainty(database):
    payload = context(database)
    from skriller.jobs.budget import reserve

    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        reservation = reserve(
            session, payload["job_id"], "dead-owner", 0, {"llm_calls": 1, "tokens": 10}
        )

        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == payload["attempt_id"])
            .values(
                state="running",
                lease_owner=str(uuid4()),
                lease_expires_at=sa.func.now() - sa.text("interval '1 second'"),
                reservation_id=reservation["id"],
            )
        )
    worker = CheckpointWorker(
        database,
        {"discovering": handler(lambda _: ("Recovered", 0, {"llm_calls": 1, "tokens": 3}))},
    )
    assert worker.execute(payload)["status"] == "checkpointed"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        cost, counters = current_usage(session, payload["job_id"])
        assert cost == 0 and counters["tokens"] == 13
        assert any(
            row["kind"] == "usage_reconciled" and row["details"]["status"] == "estimated"
            for row in JobRepository.events_after(session, payload["job_id"])
        )


def test_worker_metric_preserves_typed_block_category(database):
    payload = context(database)
    work = handler(lambda _: ("blocked", 0, {"search_calls": 1}))
    work = replace(
        work,
        feedback_failure=lambda _result: Failure(
            code="rate_limited", message="Provider asked us to slow down"
        ),
    )
    worker = CheckpointWorker(database, {"discovering": work})
    assert worker.execute(payload)["status"] == "checkpointed"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        event = next(
            row
            for row in JobRepository.events_after(session, payload["job_id"])
            if row["kind"] == "stage_observation"
        )
    assert event["details"]["outcome"] == "rate_limited"
    assert event["details"]["attempt_id"] == payload["attempt_id"]


def test_interrupted_external_call_is_estimated_and_not_blindly_repeated(database):
    payload = context(database)

    def fail(_plan):
        raise TimeoutError("sensitive source body")

    worker = CheckpointWorker(database, {"discovering": handler(fail)})
    assert worker.execute(payload) == {"status": "source_unavailable"}
    assert worker.execute(payload) == {"status": "not_dispatchable"}
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 10
        events = JobRepository.events_after(session, payload["job_id"])
        assert "sensitive source body" not in str(events)
        assert any(row["kind"] == "external_call_uncertain" for row in events)
        metrics = [row for row in events if row["kind"] == "stage_observation"]
        assert len(metrics) == 1
        assert metrics[0]["details"]["outcome"] == "deadline_exceeded"
        assert metrics[0]["details"]["attempt_id"] == payload["attempt_id"]
        assert metrics[0]["details"]["accepted_result_count"] == 0
        assert metrics[0]["details"]["cost_status"] == "estimated"
        assert "sensitive source body" not in str(metrics[0]["details"])


def test_missing_executor_and_untrusted_task_input_fail_closed(database):
    payload = context(database)
    worker = CheckpointWorker(database, {})
    assert worker.execute(payload) == {"status": "unsupported_operation"}
    with pytest.raises(ValueError):
        worker.execute({**payload, "session_cookie": "secret"})
    other = database.create_workspace("other", "Other")["id"]
    with pytest.raises(PermissionError):
        worker.execute({**payload, "workspace_id": other})


def test_late_owner_records_actual_charge_without_committing_stale_results(database):
    payload = context(database)

    def late(_plan):
        with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
            session.execute(
                sa.update(attempts)
                .where(attempts.c.id == payload["attempt_id"])
                .values(lease_expires_at=sa.func.now() - sa.text("interval '1 second'"))
            )
        return "stale output", 0, {"llm_calls": 1, "tokens": 4}

    worker = CheckpointWorker(database, {"discovering": handler(late)})
    assert worker.execute(payload) == {"status": "lease_lost"}
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 0
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 4


def test_actual_rabbitmq_celery_delivery_commits_checkpoint(database):
    import time

    from celery.contrib.testing.worker import TestWorkController, start_worker

    from skriller.jobs.outbox import CeleryPublisher
    from skriller.jobs.worker import create_worker_app
    from skriller.settings import Settings

    payload = context(database)
    app = create_worker_app(
        database,
        Settings().broker_url,
        {"discovering": handler(lambda _: ("Queue result", 0, {"llm_calls": 1, "tokens": 2}))},
    )
    queue_name = f"skriller.worker-fixture.{uuid4()}"

    class BoundedController(TestWorkController):
        def ensure_started(self):
            if not self._on_started.wait(8):
                raise RuntimeError("Local Celery worker did not become ready within8seconds")

    with start_worker(
        app,
        pool="solo",
        perform_ping_check=False,
        shutdown_timeout=8,
        WorkController=BoundedController,
        use_eventloop=False,
        logfile=".runtime/worker-test.log",
        loglevel="INFO",
        queues=[queue_name],
    ):
        publisher = CeleryPublisher(Settings().broker_url)
        publisher.app.send_task(
            publisher.TOPICS["execute_attempt"],
            args=[payload],
            task_id=str(uuid4()),
            queue=queue_name,
            delivery_mode=2,
            retry=False,
        )
        for _ in range(100):
            with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
                state = session.execute(
                    sa.select(attempts.c.state).where(attempts.c.id == payload["attempt_id"])
                ).scalar_one()
            if state == "succeeded":
                break
            time.sleep(0.05)
        assert state == "succeeded"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM stage_checkpoints")).scalar_one() == 1
        assert (
            session.execute(sa.text("SELECT state FROM external_calls")).scalar_one() == "confirmed"
        )


def test_process_killed_after_checkpoint_before_ack_replays_once(database):
    import select
    import subprocess
    import sys

    from skriller.jobs.outbox import CeleryPublisher
    from skriller.settings import Settings

    payload = context(database)
    publisher = CeleryPublisher(Settings().broker_url)
    message_id = str(uuid4())
    queue_name = f"skriller.crash-fixture.{uuid4()}"
    publisher.app.send_task(
        publisher.TOPICS["execute_attempt"],
        args=[payload],
        task_id=message_id,
        queue=queue_name,
        delivery_mode=2,
        retry=False,
    )
    child_source = """
import signal,sys
from decimal import Decimal
from skriller.db import Database, ResearchRepository
from skriller.jobs.outbox import CeleryPublisher
from skriller.jobs.worker import CheckpointWorker, StageHandler
from skriller.settings import Settings
settings=Settings()
db=Database(settings.application_database_url)
def persist(session,data):
    return [ResearchRepository.entity(session,"company",display_name=data)["id"]]
handler=StageHandler(lambda _: ("Crash proof",0,{"llm_calls":1,"tokens":2}),persist,Decimal(0),{"llm_calls":1,"tokens":10})
with CeleryPublisher(settings.broker_url).app.connection_for_read() as connection:
    queue=connection.SimpleQueue(sys.argv[1])
    message=queue.get(block=True,timeout=5)
    assert CheckpointWorker(db,{"discovering":handler}).execute(message.payload[0][0])["status"]=="checkpointed"
    print("CHECKPOINT COMMITTED",flush=True)
    signal.pause()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", child_source, queue_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        ready, _, _ = select.select([child.stdout], [], [], 10)
        assert ready and child.stdout.readline().strip() == "CHECKPOINT COMMITTED"
    finally:
        child.kill()
        child.communicate(timeout=5)
    with publisher.app.connection_for_read() as connection:
        queue = connection.SimpleQueue(queue_name)
        message = queue.get(block=True, timeout=5)
        try:
            assert message.headers["id"] == message_id
            assert message.delivery_info["redelivered"] is True
            worker = CheckpointWorker(
                database,
                {
                    "discovering": handler(
                        lambda _: (_ for _ in ()).throw(AssertionError("must not repeat call"))
                    )
                },
            )
            assert worker.execute(message.payload[0][0])["status"] == "checkpointed"
        finally:
            message.ack()
            queue.close()
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 1
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 2
