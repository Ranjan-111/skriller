from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from skriller.contracts import SearchPlan
from skriller.db import Database
from skriller.db.repositories import ConversationRepository
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher, submit

pytestmark = pytest.mark.integration_db


def planned(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Outbox")
    with database.tenant(actor, workspace["id"]) as session:
        conversation = ConversationRepository.create(session, "Research")
        interpretation = SearchPlan(
            workspace_id=workspace["id"],
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
        ).model_dump(mode="json")
        plan = ConversationRepository.revise_plan(session, conversation["id"], interpretation)
    return actor, workspace["id"], conversation["id"], plan["id"]


def test_committed_run_before_publish_recovers_through_actual_kombu_memory(database):
    actor, workspace, conversation, plan = planned(database)
    with database.tenant(actor, workspace) as session:
        job = submit(session, conversation, plan, "request")
    # No publisher was running at commit, reproducing the DB/broker gap.
    publisher = CeleryPublisher("memory://", allow_memory=True)
    with publisher.app.connection_for_read() as connection:
        queue = connection.SimpleQueue("skriller.jobs")
        queue.clear()
        dispatcher = OutboxDispatcher(database, publisher)
        message_id = dispatcher.dispatch_one(DispatchScope(actor, workspace))
        message = queue.get(block=False)
        assert message.headers["id"] == message_id
        assert message.payload[0] == [
            {"workspace_id": workspace, "job_id": job["id"], "actor_id": actor}
        ]
        message.ack()
        assert dispatcher.dispatch_one(DispatchScope(actor, workspace)) is None
        queue.close()
    with database.tenant(actor, workspace) as session:
        assert (
            session.execute(
                sa.text("SELECT published_at FROM outbox WHERE job_id=:job"), {"job": job["id"]}
            ).scalar_one()
            is not None
        )


def test_concurrent_duplicate_submission_returns_one_logical_run(database):
    actor, workspace, conversation, plan = planned(database)
    parallel = Database(database.engine.url, pool_size=2)
    try:

        def worker(_):
            with parallel.tenant(actor, workspace) as session:
                return submit(session, conversation, plan, "duplicate")["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(worker, range(2)))
        assert result[0] == result[1]
        with database.tenant(actor, workspace) as session:
            assert session.execute(sa.text("SELECT count(*) FROM jobs")).scalar_one() == 1
            assert session.execute(sa.text("SELECT count(*) FROM outbox")).scalar_one() == 1
            assert session.execute(sa.text("SELECT count(*) FROM job_events")).scalar_one() == 1
    finally:
        parallel.dispose()


def test_submission_rollback_does_not_leave_job_or_outbox(database):
    actor, workspace, conversation, plan = planned(database)
    with pytest.raises(RuntimeError), database.tenant(actor, workspace) as session:
        submit(session, conversation, plan, "rollback")
        raise RuntimeError("crash before DB commit")
    with database.tenant(actor, workspace) as session:
        assert session.execute(sa.text("SELECT count(*) FROM jobs")).scalar_one() == 0
        assert session.execute(sa.text("SELECT count(*) FROM outbox")).scalar_one() == 0


def test_crash_after_publish_replays_same_message_id(database):
    actor, workspace, conversation, plan = planned(database)
    with database.tenant(actor, workspace) as session:
        submit(session, conversation, plan, "crash")
    actual = CeleryPublisher("memory://", allow_memory=True)

    class PublishThenCrash:
        def publish(self, message_id, topic, payload):
            actual.publish(message_id, topic, payload)
            raise RuntimeError("process died after broker confirmation before commit")

    with actual.app.connection_for_read() as connection:
        queue = connection.SimpleQueue("skriller.jobs")
        queue.clear()
        with pytest.raises(RuntimeError, match="process died"):
            OutboxDispatcher(database, PublishThenCrash()).dispatch_one(
                DispatchScope(actor, workspace)
            )
        first = queue.get(block=False)
        OutboxDispatcher(database, actual).dispatch_one(DispatchScope(actor, workspace))
        second = queue.get(block=False)
        assert first.headers["id"] == second.headers["id"]
        assert first.payload == second.payload
        first.ack()
        second.ack()
        queue.close()


def test_unvalidated_or_wrong_scope_plan_cannot_submit(database):
    actor, workspace, _conversation, plan = planned(database)
    with database.tenant(actor, workspace) as session:
        other = ConversationRepository.create(session, "Invalid")
        invalid = ConversationRepository.revise_plan(session, other["id"], {"unbounded": True})
        with pytest.raises(ValidationError):
            submit(session, other["id"], invalid["id"], "invalid")
        with pytest.raises(ValueError, match="scope"):
            submit(session, other["id"], plan, "wrong scope")
        assert session.execute(sa.text("SELECT count(*) FROM jobs")).scalar_one() == 0


def test_concurrent_dispatcher_skips_locked_row_without_duplicate_publication(database):
    from threading import Event

    actor, workspace, conversation, plan = planned(database)
    with database.tenant(actor, workspace) as session:
        submit(session, conversation, plan, "parallel dispatch")
    parallel = Database(database.engine.url, pool_size=2)
    publishing, release = Event(), Event()
    actual = CeleryPublisher("memory://", allow_memory=True)

    class BoundedPublisher:
        def publish(self, message_id, topic, payload):
            publishing.set()
            assert release.wait(timeout=5)
            actual.publish(message_id, topic, payload)

    try:
        with actual.app.connection_for_read() as connection:
            queue = connection.SimpleQueue("skriller.jobs")
            queue.clear()
            identity = DispatchScope(actor, workspace)
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    OutboxDispatcher(parallel, BoundedPublisher()).dispatch_one, identity
                )
                try:
                    assert publishing.wait(timeout=5)
                    second = pool.submit(OutboxDispatcher(parallel, actual).dispatch_one, identity)
                    assert second.result(timeout=5) is None
                finally:
                    release.set()
                message_id = first.result(timeout=5)
            message = queue.get(block=False)
            assert message.headers["id"] == message_id
            message.ack()
            with pytest.raises(queue.Empty):
                queue.get(block=False)
            queue.close()
    finally:
        parallel.dispose()
