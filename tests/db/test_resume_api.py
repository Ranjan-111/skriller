from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_research_workflow import prepare

from skriller.auth import Identity, require_identity
from skriller.db import JobRepository
from skriller.db.schema import jobs, outbox
from skriller.jobs.budget import current_usage, reconcile, reserve
from skriller.jobs.worker import CheckpointWorker
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def test_resume_api_preserves_plan_deadline_usage_and_is_idempotent(database, monkeypatch):
    actor = f"resume-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        original = JobRepository.get(session, accepted["job_id"])
        reservation = reserve(session, original["id"], "previous-call", 0, {"search_calls": 1})
        reconcile(
            session,
            original["id"],
            reservation["id"],
            status="confirmed",
            cost=0,
            actual_dimensions={"search_calls": 1},
        )
        JobRepository.transition(session, original["id"], "paused")
    endpoint = f"/v1/jobs/{accepted['job_id']}/resume"
    assert (
        client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["resume_status"] == "available"
    )
    response = client.post(endpoint, headers={"Idempotency-Key": "resume-one"})
    assert response.status_code == 200 and response.json()["state"] == "queued"
    assert (
        client.post(endpoint, headers={"Idempotency-Key": "resume-one"}).json() == response.json()
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        job = JobRepository.get(session, accepted["job_id"])
        assert job["plan_id"] == original["plan_id"] and job["created_at"] == original["created_at"]
        assert current_usage(session, job["id"])[1]["search_calls"] == 1
        assert (
            session.execute(
                sa.select(sa.func.count()).select_from(outbox).where(outbox.c.job_id == job["id"])
            ).scalar_one()
            == 2
        )


@pytest.mark.parametrize("reason", ["expired", "clarification", "unsupported", "cancelled"])
def test_resume_api_rejects_work_that_requires_new_plan_or_deadline(database, monkeypatch, reason):
    actor = f"resume-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        if reason == "cancelled":
            from skriller.jobs.control import cancel

            cancel(session, accepted["job_id"])
        else:
            JobRepository.transition(
                session,
                accepted["job_id"],
                "paused",
                failure_code={
                    "clarification": "clarification_required",
                    "unsupported": "unsupported_criteria",
                }.get(reason),
            )
            if reason == "expired":
                session.execute(
                    sa.update(jobs)
                    .where(jobs.c.id == accepted["job_id"])
                    .values(created_at=datetime.now(UTC) - timedelta(hours=1))
                )
    readiness = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["resume_status"]
    assert (
        readiness
        == {
            "expired": "deadline_expired",
            "clarification": "new_prompt_required",
            "unsupported": "new_prompt_required",
            "cancelled": "not_paused",
        }[reason]
    )
    response = client.post(
        f"/v1/jobs/{accepted['job_id']}/resume", headers={"Idempotency-Key": "resume-one"}
    )
    assert response.status_code == 409


def test_checkpoint_failure_reports_reconciliation_without_enabling_resume(database, monkeypatch):
    from dataclasses import replace

    from test_worker import handler

    actor = f"checkpoint-failure-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    payload = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]

    def fail(_session, _data):
        raise RuntimeError("private source error")

    work = replace(
        handler(lambda _: ("source fact", 0, {"search_calls": 1})),
        persist=fail,
        dimensions={"search_calls": 1},
    )
    assert CheckpointWorker(database, {"discovering": work}).execute(payload) == {
        "status": "checkpoint_failed"
    }
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results")
    assert response.status_code == 200
    assert response.json()["resume_status"] == "requires_reconciliation"
    assert any("usage is retained" in item for item in response.json()["limitations"])
    assert "private source error" not in response.text
    assert (
        client.post(
            f"/v1/jobs/{accepted['job_id']}/resume", headers={"Idempotency-Key": "no-replay"}
        ).status_code
        == 409
    )


def test_resume_api_requires_identity_scope_key_and_enabled_provider(database, monkeypatch):
    actor = f"resume-{uuid4()}"
    app, client, accepted = prepare(database, monkeypatch, actor)
    endpoint = f"/v1/jobs/{accepted['job_id']}/resume"
    assert client.post(endpoint).status_code == 422
    app.state.search_provider = None
    assert client.post(endpoint, headers={"Idempotency-Key": "r"}).status_code == 503
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.post(endpoint, headers={"Idempotency-Key": "r"}).status_code == 404


def test_disabled_search_pauses_existing_task_without_io(database, monkeypatch):
    from skriller.research import runtime

    actor = f"disabled-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    payload = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    monkeypatch.setattr(runtime, "database", database)
    monkeypatch.setattr(runtime, "settings", Settings(search_provider="disabled"))
    monkeypatch.setattr(
        runtime, "execute_discovery", lambda *_: pytest.fail("Disabled source dispatched")
    )
    assert runtime.execute.run(payload)["status"] == "source_disabled"
    assert client.get(f"/v1/jobs/{accepted['job_id']}").json()["state"] == "paused"
    assert any(
        "source disabled" in item
        for item in client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["limitations"]
    )
