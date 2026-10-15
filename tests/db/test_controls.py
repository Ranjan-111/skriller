from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.schema import attempts, jobs
from skriller.jobs.budget import current_usage
from skriller.jobs.control import cancel, permit_call, resume
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker, StageHandler

pytestmark = pytest.mark.integration_db


def context(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Controls")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Controls")
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


def test_cancel_during_io_retains_charge_and_fences_result(database):
    payload = context(database)
    calls = []

    def run(plan):
        calls.append(plan.revision)
        with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
            assert cancel(session, payload["job_id"])["state"] == "cancelled"
        return "late", Decimal(0), {"llm_calls": 1, "tokens": 3}

    def persist(session, data):
        pytest.fail("Cancelled job persisted a late result")

    worker = CheckpointWorker(
        database,
        {"discovering": StageHandler(run, persist, Decimal(0), {"llm_calls": 1, "tokens": 10})},
    )
    assert worker.execute(payload)["status"] == "lease_lost"
    assert worker.execute(payload)["status"] == "not_dispatchable"
    assert calls == [1]
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 3
        assert JobRepository.get(session, payload["job_id"])["state"] == "cancelled"


def test_deadline_expiry_after_io_accounts_usage_without_output(database):
    payload = context(database)

    def run(_plan, timeout):
        assert 0 < timeout <= 120
        with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
            session.execute(
                sa.update(jobs)
                .where(jobs.c.id == payload["job_id"])
                .values(created_at=sa.func.now() - sa.text("interval '1 hour'"))
            )
        return "too late", 0, {"tokens": 4}

    worker = CheckpointWorker(
        database,
        {
            "discovering": StageHandler(
                lambda _: pytest.fail("Unbounded callback used"),
                lambda _s, _d: pytest.fail("Expired output persisted"),
                Decimal(0),
                {"tokens": 10},
                run_with_deadline=run,
            )
        },
    )
    assert worker.execute(payload)["status"] == "deadline_exceeded"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert permit_call(session, payload["job_id"]) == 0
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 4
        with pytest.raises(ValueError, match="deadline"):
            resume(session, payload["job_id"], "new")


def test_resume_pending_attempt_is_idempotent_and_keeps_checkpoint(database):
    payload = context(database)
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        entity = ResearchRepository.entity(session, "company", display_name="Retained")
        JobRepository.usage(session, payload["job_id"], "previous", "tokens", 3, 0)
        JobRepository.transition(session, payload["job_id"], "paused")
        assert resume(session, payload["job_id"], "request")["state"] == "queued"
        assert resume(session, payload["job_id"], "request")["state"] == "queued"
        assert ResearchRepository.get_entity(session, entity["id"])
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 3
        assert session.execute(sa.text("SELECT count(*) FROM outbox WHERE topic='execute_attempt'"))
        assert (
            ConversationRepository.get_plan(
                session, JobRepository.get(session, payload["job_id"])["plan_id"]
            )["revision"]
            == 1
        )


def test_uncertain_attempt_and_cross_tenant_resume_denied(database):
    payload = context(database)
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        session.execute(
            sa.update(attempts).where(attempts.c.id == payload["attempt_id"]).values(state="failed")
        )
        JobRepository.transition(session, payload["job_id"], "paused")
        with pytest.raises(ValueError, match="reconciliation"):
            resume(session, payload["job_id"], "retry")
    other = database.create_workspace("other-controls", "Other")["id"]
    with database.tenant("other-controls", other) as session, pytest.raises(LookupError):
        cancel(session, payload["job_id"])


def test_resume_collection_still_refuses_exhausted_fetch_quota(database):
    payload = context(database)
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        job = JobRepository.get(session, payload["job_id"])
        plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, job["plan_id"])["interpretation"]
        )
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == payload["attempt_id"])
            .values(state="succeeded")
        )
        JobRepository.attempt(session, job["id"], "collect:pending", "collecting")
        JobRepository.usage(
            session, job["id"], "spent-fetches", "fetch_attempts", plan.limits.fetch_attempts, 0
        )
        JobRepository.transition(session, job["id"], "paused", stage="collecting")
        with pytest.raises(ValueError, match="budget"):
            resume(session, job["id"], "cannot-expand-budget")
        assert JobRepository.get(session, job["id"])["state"] == "paused"


def test_personal_workspace_concurrent_creation_and_actor_lookup(database):
    actor = str(uuid4())
    engine = sa.create_engine(database.engine.url, pool_size=2, max_overflow=0)

    def personal():
        with Session(engine) as session, session.begin():
            session.execute(
                sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor}
            )
            return str(
                session.execute(
                    sa.text("SELECT id FROM get_or_create_personal_workspace()")
                ).scalar_one()
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: personal(), range(2)))
    finally:
        engine.dispose()
    assert first == second
    with Session(database.engine) as session, session.begin():
        session.execute(
            sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor}
        )
        assert (
            str(session.execute(sa.text("SELECT id FROM actor_workspaces()")).scalar_one()) == first
        )
        session.execute(
            sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": str(uuid4())}
        )
        assert session.execute(sa.text("SELECT id FROM actor_workspaces()")).all() == []
