"""Owner summary APIs and real opaque scheduler/executor under database budgets."""

import json
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
import sqlalchemy as sa
from test_youtube_analytics_reports import REQUEST, ReportsProvider, SummaryStub, connected

from skriller.analytics.jobs import execute_summary
from skriller.analytics.private_jobs import PrivateSummaryStore
from skriller.db import WorkspaceRepository
from skriller.db.schema import job_events, messages, outbox, plans
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.worker import CheckpointWorker

pytestmark = pytest.mark.integration_db


def submit(client, path, grant, key="fixture"):
    return client.post(
        path + "/summary-jobs",
        json={"grant_id": grant, "report": REQUEST},
        headers={"Idempotency-Key": key},
    )


def test_summary_api_admission_scheduler_execution_idempotency_privacy(database, monkeypatch):
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    provider = ReportsProvider()
    actor, workspace, app, client, path, grant = connected(database, provider)
    submitted = submit(client, path, grant)
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["job_id"]
    assert submitted.json()["summary_state"] == "queued"
    assert submit(client, path, grant).json()["job_id"] == job_id
    assert provider.report_calls == 1
    other = "other-owner-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, "owner")
        private = PrivateSummaryStore(app.state.analytics_store)
        report = private.report(session, job_id).report
        for table in (messages, plans, job_events, outbox):
            rows = (
                session.execute(sa.select(table).where(table.c.workspace_id == workspace))
                .mappings()
                .all()
            )
            serialized = json.dumps([dict(row) for row in rows], default=str)
            assert report.summary[0] not in serialized
            assert "2026-01-01" not in serialized
            assert "SENTINEL" not in serialized
    route = path + "/summary-jobs/" + job_id
    for method, url in ((client.get, route), (client.post, route + "/cancel")):
        assert method(url, headers={"Authorization": "Bearer " + other}).status_code == 409
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job_id}
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    assert scheduled["status"] == "scheduled"
    payload["attempt_id"] = scheduled["attempt_id"]
    stub = SummaryStub(str(uuid5(NAMESPACE_URL, report.response_sha256 + ":0")), report.summary[0])
    assert (
        execute_summary(
            database, payload, private, model=LocalStructuredModel(model_instance=stub)
        )["status"]
        == "checkpointed"
    )
    assert (
        execute_summary(
            database, payload, private, model=LocalStructuredModel(model_instance=stub)
        )["status"]
        == "checkpointed"
    )
    assert stub.calls == 1
    response = client.get(route)
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["state"] == "completed"
    assert response.json()["result"]["observations"][0]["quote"] == report.summary[0]
    assert submit(client, path, grant).json()["job_id"] == job_id
    assert provider.report_calls == 1
    conflict = client.post(
        path + "/summary-jobs",
        json={"grant_id": grant, "report": {**REQUEST, "metrics": ["views"]}},
        headers={"Idempotency-Key": "fixture"},
    )
    assert conflict.status_code == 422


def test_cancel_before_dispatch_and_api_validation(database, monkeypatch):
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    actor, workspace, _app, client, path, grant = connected(database, ReportsProvider())
    response = submit(client, path, grant)
    assert response.status_code == 202
    job = response.json()["job_id"]
    cancelled = client.post(path + "/summary-jobs/" + job + "/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["summary_state"] == "cancelled"
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["result"] is None
    assert (
        CheckpointWorker(database, {}).schedule(
            {"actor_id": actor, "workspace_id": workspace, "job_id": job}
        )["status"]
        == "not_dispatchable"
    )
    missing_key = client.post(path + "/summary-jobs", json={"grant_id": grant, "report": REQUEST})
    assert missing_key.status_code == 422
    assert "SENTINEL" not in missing_key.text


def test_worker_failure_redacts_and_never_replays_model(database, monkeypatch):
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    actor, workspace, app, client, path, grant = connected(database, ReportsProvider())
    job = submit(client, path, grant).json()["job_id"]
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job}
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    private = PrivateSummaryStore(app.state.analytics_store)

    class Broken:
        calls = 0

        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("SENTINEL_PRIVATE_PROVIDER_ERROR")

    broken = Broken()
    # The copied graph turns transport errors into an unknown answer; it must
    # still be metered once and never expose provider exception text.
    first = execute_summary(
        database, payload, private, model=LocalStructuredModel(model_instance=broken)
    )
    second = execute_summary(
        database, payload, private, model=LocalStructuredModel(model_instance=broken)
    )
    assert first["status"] == second["status"] == "checkpointed"
    assert broken.calls == 1
    response = client.get(path + "/summary-jobs/" + job)
    assert "SENTINEL" not in response.text
    assert response.json()["result"]["status"] == "unknown"


def test_expired_worker_lease_does_not_repeat_private_execution(database, monkeypatch):
    from skriller.db.schema import attempts

    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    actor, workspace, app, client, path, grant = connected(database, ReportsProvider())
    job = submit(client, path, grant).json()["job_id"]
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": job}
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == payload["attempt_id"])
            .values(
                state="running",
                lease_owner=str(uuid4()),
                lease_expires_at=sa.func.now() - sa.text("interval '1 second'"),
            )
        )
    outcome = execute_summary(database, payload, PrivateSummaryStore(app.state.analytics_store))
    assert outcome["status"] == "summary_interrupted"
    response = client.get(path + "/summary-jobs/" + job)
    assert response.json()["state"] == "paused"
    assert response.json()["summary_state"] == "failed"
    assert response.json()["result"] is None


def test_disabled_workspace_stops_summary_before_provider_io(database, monkeypatch):
    from skriller.entitlements import policies

    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    provider = ReportsProvider()
    actor, workspace, _, client, path, grant = connected(database, provider)
    assert submit(client, path, grant).status_code == 202
    assert provider.report_calls == 1
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(policies).where(policies.c.workspace_id == workspace).values(enabled=False)
        )
    denied = submit(client, path, grant, key="new-request")
    assert denied.status_code == 429
    assert denied.json()["detail"]["code"] == "analytics_run_allowance_exhausted"
    assert provider.report_calls == 1
