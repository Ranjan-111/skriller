from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db import Database
from skriller.db.repositories import ConversationRepository, JobRepository, ResearchRepository
from skriller.jobs import finish

pytestmark = pytest.mark.integration_db


def running_job(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "State machine")
    with database.tenant(actor, workspace["id"]) as session:
        conversation = ConversationRepository.create(session, "Research")
        plan = ConversationRepository.revise_plan(
            session, conversation["id"], {"industry": "fintech"}
        )
        job = JobRepository.create(session, conversation["id"], plan["id"], str(uuid4()))
        JobRepository.transition(session, job["id"], "queued", expected_version=1)
        job = JobRepository.transition(session, job["id"], "running", stage="qualifying")
    return actor, workspace["id"], job


def test_limit_preserves_results_stage_terminal_reason_and_atomic_events(database):
    actor, workspace, job = running_job(database)
    with database.tenant(actor, workspace) as session:
        entity = ResearchRepository.entity(session, "company", "Acme")
        result = ResearchRepository.qualify(
            session,
            entity["id"],
            job["plan_id"],
            "fintech",
            "unknown",
            reason="Needs evidence",
        )
        final = finish(
            session,
            job["id"],
            outcome="budget_limit",
            retained_results=1,
            expected_version=job["version"],
        )
        assert final["state"] == "partial"
        assert final["terminal_reason"] == "budget_limit"
        assert final["stage"] == "qualifying"
        assert final["completed_at"] is not None
        events = JobRepository.events_after(session, job["id"])
        assert [event["details"]["version"] for event in events] == [2, 3, 4]
        assert events[-1]["details"]["terminal_reason"] == "budget_limit"
        assert JobRepository.transition(session, job["id"], "partial")["version"] == 4
        with pytest.raises(ValueError, match="Invalid"):
            JobRepository.transition(session, job["id"], "running")
    with database.tenant(actor, workspace) as session:
        assert (
            str(
                session.execute(
                    sa.text("SELECT id FROM qualifications WHERE id=:id"), {"id": result["id"]}
                ).scalar_one()
            )
            == result["id"]
        )
    with (
        pytest.raises(DBAPIError, match="Terminal job"),
        database.tenant(actor, workspace) as session,
    ):
        session.execute(
            sa.text("UPDATE jobs SET state='running', terminal_reason=NULL WHERE id=:id"),
            {"id": job["id"]},
        )


def test_exhausted_sources_complete_but_interruption_without_results_fails(database):
    for outcome, expected in (("source_exhausted", "completed"), ("deadline_limit", "failed")):
        actor, workspace, job = running_job(database)
        with database.tenant(actor, workspace) as session:
            final = finish(
                session,
                job["id"],
                outcome=outcome,
                retained_results=0,
                expected_version=job["version"],
            )
            assert final["state"] == expected
            assert final["terminal_reason"] == outcome


def test_concurrent_terminal_decisions_have_one_winner_and_one_event(database):
    actor, workspace, job = running_job(database)
    parallel_db = Database(database.engine.url, pool_size=2)
    try:

        def worker(outcome):
            try:
                with parallel_db.tenant(actor, workspace) as session:
                    finish(
                        session,
                        job["id"],
                        outcome=outcome,
                        retained_results=1,
                        expected_version=job["version"],
                    )
                return "committed"
            except ValueError as error:
                assert "concurrently" in str(error)
                return "stale"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(worker, ("source_exhausted", "budget_limit"))) == [
                "committed",
                "stale",
            ]
        with database.tenant(actor, workspace) as session:
            assert len(JobRepository.events_after(session, job["id"])) == 3
            assert JobRepository.get(session, job["id"])["version"] == 4
    finally:
        parallel_db.dispose()


def test_state_event_rollback_is_atomic_and_same_state_stage_advances(database):
    actor, workspace, job = running_job(database)
    with pytest.raises(RuntimeError), database.tenant(actor, workspace) as session:
        JobRepository.transition(session, job["id"], "completed", terminal_reason="target_met")
        raise RuntimeError("crash before commit")
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, job["id"])["state"] == "running"
        assert len(JobRepository.events_after(session, job["id"])) == 2
        advanced = JobRepository.transition(session, job["id"], "running", stage="extracting")
        assert advanced["stage"] == "extracting"
        assert advanced["version"] == job["version"] + 1


def test_terminal_reasons_cannot_be_missing_or_replaced(database):
    actor, workspace, job = running_job(database)
    with (
        pytest.raises(DBAPIError, match="terminal_reason_required"),
        database.tenant(actor, workspace) as session,
    ):
        session.execute(
            sa.text("UPDATE jobs SET state='completed' WHERE id=:id"), {"id": job["id"]}
        )
    with database.tenant(actor, workspace) as session:
        final = JobRepository.transition(
            session, job["id"], "completed", terminal_reason="target_met"
        )
        assert (
            JobRepository.transition(session, job["id"], "completed")["version"] == final["version"]
        )
        with pytest.raises(ValueError, match="outcome"):
            JobRepository.transition(
                session, job["id"], "completed", terminal_reason="source_exhausted"
            )
