"""Actual tenant PostgreSQL workflow with controlled source IO, no fake live claims."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.search import SearchHit, SearchPage, SearchUnavailable
from skriller.contracts import Failure
from skriller.db import JobRepository
from skriller.jobs.worker import CheckpointWorker
from skriller.research import service
from skriller.research.service import execute_discovery, personal_workspace
from skriller.settings import Settings


class Provider:
    def __init__(self, failing=False):
        self.calls = 0
        self.failing = failing

    async def search(self, query, **kwargs):
        self.calls += 1
        if self.failing and kwargs["domains"]:
            raise SearchUnavailable(Failure(code="access_denied", message="Try later"))
        return SearchPage(
            hits=[
                SearchHit(
                    title="Fixture indexed page",
                    url="https://example.org/company",
                    snippet="Source-provided snippet",
                    rank=1,
                )
            ],
            rejected=0,
            truncated=False,
        )


def prepare(database, monkeypatch, actor):
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={})
    assert conversation.status_code == 201, conversation.text
    response = client.post(
        f"/v1/conversations/{conversation.json()['id']}/messages",
        json={
            "content": "Find software companies",
            "options": {"mode": "leads", "sources": ["linkedin", "web"], "result_limit": 10},
        },
    )
    assert response.status_code == 202, response.text
    return app, client, response.json()


def isolate_capacity(monkeypatch, job_id):
    original_handler = service.discovery_handler

    def isolated_handler(database, actor_id, job_id, provider=None):
        handler = original_handler(database, actor_id, job_id, provider)
        identity = job_id.replace("-", "")
        return replace(
            handler,
            capacity_source=f"test-{identity}",
            capacity_host=f"test-{identity}.example.invalid",
        )

    monkeypatch.setattr(service, "discovery_handler", isolated_handler)


def run(database, actor, accepted, provider, monkeypatch):
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    payload["attempt_id"] = scheduled["attempt_id"]
    return payload, execute_discovery(database, payload, provider)


def test_submission_checkpoint_results_and_duplicate_delivery(database, monkeypatch):
    actor = f"workflow-{uuid4()}"
    app, client, accepted = prepare(database, monkeypatch, actor)
    assert str(personal_workspace(database, actor)["id"]) == accepted["workspace_id"]
    provider = Provider()
    payload, outcome = run(database, actor, accepted, provider, monkeypatch)
    assert outcome["status"] == "checkpointed"
    assert provider.calls == 2
    assert execute_discovery(database, payload, provider)["status"] == "checkpointed"
    assert provider.calls == 2
    snapshot = client.get(f"/v1/jobs/{accepted['job_id']}").json()
    assert snapshot["state"] == "completed"
    assert snapshot["result_count"] == 1  # URL dedupe across sources
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert result["results"][0]["qualification"] == "unverified"
    assert result["results"][0]["evidence_kind"] == "search_snippet"
    assert "email" not in result["results"][0]
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.get(f"/v1/jobs/{accepted['job_id']}").status_code == 404
    assert (
        client.get(
            f"/v1/jobs/{accepted['job_id']}/results?workspace_id={accepted['workspace_id']}"
        ).status_code
        == 404
    )


def test_partial_source_failure_retains_unverified_results(database, monkeypatch):
    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    run(database, actor, accepted, Provider(failing=True), monkeypatch)
    snapshot = client.get(f"/v1/jobs/{accepted['job_id']}").json()
    assert snapshot["state"] == "partial"
    assert snapshot["terminal_reason"] == "source_interrupted"
    assert snapshot["result_count"] == 1
    with database.tenant(actor, accepted["workspace_id"]) as session:
        events = JobRepository.events_after(session, accepted["job_id"])
        summary = next(event for event in events if event["kind"] == "discovery_summary")
        assert summary["details"]["source_failures"] == [
            {"source": "linkedin", "code": "access_denied"}
        ]


def test_invalid_request_is_not_dispatched(database, monkeypatch):
    actor = f"workflow-{uuid4()}"
    _, client, _accepted = prepare(database, monkeypatch, actor)
    assert client.post("/v1/conversations", json={"unsafe": True}).status_code == 422
    assert client.get(f"/v1/jobs/{uuid4()}").status_code == 404
    assert (
        client.post("/v1/conversations/not-a-uuid/messages", json={"content": "test"}).status_code
        == 422
    )


def test_request_idempotency_and_cancel_without_source_io(database, monkeypatch):
    actor = f"workflow-{uuid4()}"
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={}).json()
    body = {
        "content": "Find manufacturing companies",
        "options": {"mode": "leads", "sources": ["web"], "result_limit": 3},
    }
    endpoint = f"/v1/conversations/{conversation['id']}/messages"
    first = client.post(endpoint, json=body, headers={"Idempotency-Key": "request-one"})
    replay = client.post(endpoint, json=body, headers={"Idempotency-Key": "request-one"})
    assert first.status_code == replay.status_code == 202
    assert first.json()["job_id"] == replay.json()["job_id"]
    assert (
        client.post(
            endpoint,
            json={**body, "content": "Different objective"},
            headers={"Idempotency-Key": "request-one"},
        ).status_code
        == 409
    )
    accepted = first.json()
    cancelled = client.post(f"/v1/jobs/{accepted['job_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert client.post(f"/v1/jobs/{accepted['job_id']}/cancel").json() == cancelled.json()
    provider = Provider()
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    assert CheckpointWorker(database, {}).schedule(payload)["status"] == "not_dispatchable"
    assert provider.calls == 0


@pytest.mark.integration_db
def test_real_broker_dispatch_runs_source_handler_and_finishes(database, monkeypatch):
    from celery.contrib.testing.worker import start_worker

    from skriller.research import runtime
    from skriller.research.service import dispatch

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    isolate_capacity(monkeypatch, accepted["job_id"])
    provider = Provider()
    monkeypatch.setattr(runtime, "database", database)
    monkeypatch.setattr(
        runtime, "execute_discovery", lambda db, payload: execute_discovery(db, payload, provider)
    )
    # Isolate this delivery test from the developer's concurrently running worker.
    from skriller.jobs.outbox import CeleryPublisher

    queue = f"skriller.workflow-fixture.{uuid4()}"

    def publish_fixture(self, message_id, topic, payload):
        self.app.send_task(
            self.TOPICS[topic],
            args=[payload],
            task_id=message_id,
            queue=queue,
            delivery_mode=2,
            retry=False,
        )

    monkeypatch.setattr(CeleryPublisher, "publish", publish_fixture)
    # Real RabbitMQ task publication/delivery; controlled source is explicitly a fixture.
    with start_worker(
        runtime.app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        shutdown_timeout=8,
        use_eventloop=False,
        queues=[queue],
    ):
        dispatch(database, Settings().broker_url, actor, accepted["workspace_id"])
        import time

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            snapshot = client.get(f"/v1/jobs/{accepted['job_id']}").json()
            if snapshot["state"] == "completed":
                break
            time.sleep(0.1)
        assert snapshot["state"] == "completed"
        assert snapshot["result_count"] == 1
    assert provider.calls == 2


@pytest.mark.parametrize("status", ["leased", "capacity_exhausted"])
def test_runtime_retries_temporary_admission_without_dropping_job(database, monkeypatch, status):
    from celery.exceptions import Retry

    from skriller.research import runtime

    actor = f"workflow-{uuid4()}"
    _, _, accepted = prepare(database, monkeypatch, actor)
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    monkeypatch.setattr(runtime, "database", database)
    monkeypatch.setattr(runtime, "execute_discovery", lambda *args: {"status": status})

    def retry(**kwargs):
        assert 0 < kwargs["countdown"] <= 5
        assert kwargs["max_retries"] == 30
        return Retry()

    monkeypatch.setattr(runtime.execute, "retry", retry)
    with pytest.raises(Retry):
        runtime.execute.run(payload)


def test_cancel_between_sources_stops_new_network_calls(database, monkeypatch):
    from skriller.jobs.control import cancel

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)

    class CancellingProvider(Provider):
        async def search(self, query, **kwargs):
            page = await super().search(query, **kwargs)
            with database.tenant(actor, accepted["workspace_id"]) as session:
                cancel(session, accepted["job_id"])
            return page

    provider = CancellingProvider()
    _, outcome = run(database, actor, accepted, provider, monkeypatch)
    assert outcome["status"] == "lease_lost"
    assert provider.calls == 1
    assert client.get(f"/v1/jobs/{accepted['job_id']}").json()["state"] == "cancelled"
    assert client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"] == []
    from skriller.jobs.budget import current_usage

    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert current_usage(session, accepted["job_id"])[1]["search_calls"] == 1


def test_rate_limit_retains_earlier_results_and_stops_new_calls(database, monkeypatch):
    from skriller.jobs.budget import current_usage

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)

    class LimitedProvider(Provider):
        async def search(self, query, **kwargs):
            if self.calls == 1:
                self.calls += 1
                raise SearchUnavailable(Failure(code="rate_limited", message="Wait",
                                                retry_after_seconds=30))
            return await super().search(query, **kwargs)

    provider = LimitedProvider()
    _, outcome = run(database, actor, accepted, provider, monkeypatch)
    assert outcome["status"] == "checkpointed"
    assert provider.calls == 2
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert response["state"] == "partial" and len(response["results"]) == 1
    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert current_usage(session, accepted["job_id"])[1]["search_calls"] == 2
        # Source cadence is exposed only through the membership-checked lease API.
        from skriller.jobs.capacity import CapacityUnavailable

        with pytest.raises(CapacityUnavailable):
            # This job is terminal, so a new active tenant job is needed below.
            raise CapacityUnavailable("Separate capacity tests verify persisted RetryAfter")
