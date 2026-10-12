from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db import Database
from skriller.db.repositories import ConversationRepository, JobRepository

pytestmark = pytest.mark.integration_db


def create_job(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Jobs")
    with database.tenant(actor, workspace["id"]) as session:
        conversation = ConversationRepository.create(session, "Research")
        plan = ConversationRepository.revise_plan(session, conversation["id"], {"query": "fintech"})
        job = JobRepository.create(session, conversation["id"], plan["id"], str(uuid4()))
    return actor, workspace["id"], job


def test_duplicate_workers_create_one_attempt_and_one_ledger_record(database):
    actor, workspace, job = create_job(database)
    concurrent_db = Database(database.engine.url, pool_size=2)
    try:

        def worker(_):
            with concurrent_db.tenant(actor, workspace) as session:
                attempt = JobRepository.attempt(session, job["id"], "collect:acme", "collecting")
                usage = JobRepository.usage(
                    session,
                    job["id"],
                    "usage:collect:acme",
                    "pages",
                    1,
                    "0.001",
                    attempt_id=attempt["id"],
                )
                return attempt["id"], usage["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        assert results[0] == results[1]
        with database.tenant(actor, workspace) as session:
            assert (
                session.execute(
                    sa.text("SELECT count(*) FROM attempts WHERE job_id=:j"), {"j": job["id"]}
                ).scalar_one()
                == 1
            )
            assert session.execute(
                sa.text("SELECT sum(cost_usd) FROM usage_records WHERE job_id=:j"), {"j": job["id"]}
            ).scalar_one() == Decimal("0.001")
            with pytest.raises(ValueError, match="different operation"):
                JobRepository.usage(
                    session,
                    job["id"],
                    "usage:collect:acme",
                    "pages",
                    100,
                    "1",
                    attempt_id=results[0][0],
                )
    finally:
        concurrent_db.dispose()


def test_job_and_outbox_recover_from_database_without_celery_cache(database):
    actor, workspace, job = create_job(database)
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, job["id"])["state"] == "planned"
        JobRepository.transition(session, job["id"], "queued", expected_state="planned")
        JobRepository.transition(session, job["id"], "running", stage="discovering")
        JobRepository.event(session, job["id"], "start", "started", {"stage": "discovering"})
        record = JobRepository.enqueue(session, job["id"], "dispatch")
        # Additional fields cannot enter the queue payload even if a caller adds them.
        payload = JobRepository.broker_payload(
            {**record, "content": "PRIVATE PAGE", "token": "SECRET"}
        )
        assert payload == {"workspace_id": workspace, "job_id": job["id"], "actor_id": actor}
        JobRepository.reserve(session, job["id"], "budget", "0.01")
    fresh = Database(database.engine.url)
    try:
        with fresh.tenant(actor, workspace) as session:
            recovered = JobRepository.get(session, job["id"])
            assert recovered["state"] == "running"
            assert recovered["stage"] == "discovering"
            assert recovered["plan_id"] == job["plan_id"]
            events = JobRepository.events_after(session, job["id"])
            assert [event["kind"] for event in events] == [
                "state_changed",
                "state_changed",
                "started",
            ]
            assert JobRepository.events_after(session, job["id"], events[-1]["sequence"]) == []
            JobRepository.transition(session, job["id"], "completed")
            with pytest.raises(ValueError, match="Invalid"):
                JobRepository.transition(session, job["id"], "running")
        with (
            pytest.raises(DBAPIError, match="Immutable"),
            fresh.tenant(actor, workspace) as session,
        ):
            session.execute(sa.text("DELETE FROM job_events WHERE job_id=:j"), {"j": job["id"]})
    finally:
        fresh.dispose()


def test_job_cannot_reference_other_workspace_plan(database):
    actor, _workspace, job = create_job(database)
    other = database.create_workspace(actor, "Other job workspace")
    with database.tenant(actor, other["id"]) as session:
        assert JobRepository.get(session, job["id"]) is None
        conversation = ConversationRepository.create(session, "Other research")
    with pytest.raises(DBAPIError), database.tenant(actor, other["id"]) as session:
        JobRepository.create(session, conversation["id"], job["plan_id"], "cross-tenant")
