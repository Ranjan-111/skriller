"""Actual tenant PostgreSQL workflow with controlled source IO, no fake live claims."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.search import SearchHit, SearchPage, SearchUnavailable
from skriller.contracts import Failure
from skriller.db import JobRepository
from skriller.db.schema import entities
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


def prepare(database, monkeypatch, actor, *, settings=None, sources=None, result_limit=10):
    app = create_app(settings or Settings())
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
            "options": {
                "mode": "leads",
                "sources": sources or ["linkedin", "web"],
                "result_limit": result_limit,
            },
        },
    )
    assert response.status_code == 202, response.text
    return app, client, response.json()


def isolate_capacity(monkeypatch, job_id):
    original_handler = service.discovery_handler
    original_acquire = service.acquire

    def isolated_acquire(session, requested_job, **kwargs):
        if requested_job == job_id and kwargs.get("source") in {
            "x",
            "reddit",
            "linkedin",
            "instagram",
            "facebook",
        }:
            label = f"test-{kwargs['source']}-{job_id.replace('-', '')}"
            kwargs.update(source=label, host=label + ".example.invalid")
        return original_acquire(session, requested_job, **kwargs)

    monkeypatch.setattr(service, "acquire", isolated_acquire)

    def isolated_handler(database, actor_id, job_id, provider=None, **kwargs):
        handler = original_handler(database, actor_id, job_id, provider, **kwargs)
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


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/feed/update/urn:li:activity:123456789/",
        "https://www.reddit.com/r/software/comments/abc123/anonymous_discussion/",
    ],
)
def test_indexed_discussion_reference_does_not_invent_author_or_named_lead(
    database, monkeypatch, url
):
    actor = f"discussion-reference-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)

    class DiscussionProvider:
        async def search(self, query, **kwargs):
            return SearchPage(
                hits=[
                    SearchHit(
                        title="Anonymous discussion",
                        url=url,
                        snippet="Founder discusses hiring",
                        rank=1,
                    )
                ],
                rejected=0,
                truncated=False,
            )

    run(database, actor, accepted, DiscussionProvider(), monkeypatch)
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results")
    assert response.status_code == 200, response.text
    record = response.json()["results"][0]
    assert record["discussion"] == {
        "resource_kind": "post",
        "evidence_kind": "indexed_reference",
        "author_handle": None,
        "author_identity": "unknown",
    }
    assert record["qualification"] == "unverified" and record["fit"]["status"] != "confirmed"
    assert record["platform_reference"]["resource_kind"] == "post"
    assert record["platform_reference"]["access"] == "indexed_reference_only"
    assert record["platform_reference"]["direct_read_status"] == "not_attempted"
    assert record["platform_reference"]["subject_identity"] == "unknown"


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


@pytest.mark.parametrize(
    "source,provider,url,native",
    [
        (
            "x",
            "x_api_v2",
            "https://x.com/founder/status/123456",
            {"namespace": "x_post", "id": "123456"},
        ),
        (
            "reddit",
            "reddit_oauth",
            "https://www.reddit.com/r/startups/comments/abc123/fixture/",
            {"namespace": "reddit_post", "id": "abc123"},
        ),
    ],
)
def test_connected_posts_enter_durable_discovery_with_post_provenance(
    database, monkeypatch, source, provider, url, native
):
    actor = f"x-discovery-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor, sources=[source])
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, accepted["workspace_id"]) as session:
        reference = store.create(
            session,
            source,
            "oauth",
            SecretPayload(credentials={"access_token": "synthetic-x-oauth-token"}),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            scopes=("read", "discover"),
        )

    class XReader:
        def search_page(self, query, **kwargs):
            assert kwargs["context"].connection_ref == reference.id
            assert not query.startswith(source + " ")
            runner = "x_read" if source == "x" else "reddit_oauth_search"
            with database.tenant(actor, accepted["workspace_id"]) as session:
                material = store.load_for_runner(session, kwargs["context"], runner)
                assert material.injection() == {
                    "X_ACCESS_TOKEN"
                    if source == "x"
                    else "REDDIT_ACCESS_TOKEN": "synthetic-x-oauth-token"
                }
                assert store.runner_current(session, kwargs["context"], material)
            return SearchPage(
                hits=[
                    SearchHit(
                        title="@founder",
                        url=url,
                        snippet="We are hiring a product engineer",
                        provider=provider,
                        evidence_kind="public_post",
                        rank=1,
                    )
                ],
                rejected=0,
                truncated=False,
                query=query,
            )

    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    payload["attempt_id"] = scheduled["attempt_id"]
    outcome = execute_discovery(
        database,
        payload,
        Provider(),
        **{("x_reader" if source == "x" else "reddit_reader"): XReader()},
        connection_store=store,
    )
    assert outcome["status"] == "checkpointed"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        row = (
            session.execute(sa.select(entities).where(entities.c.id == outcome["entity_ids"][0]))
            .mappings()
            .one()
        )
        assert row["attributes"]["provider"] == provider
        assert row["attributes"]["evidence_kind"] == "public_post"
        assert row["attributes"]["_source_native_id"] == native
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"][0]
    assert result["evidence_kind"] == "public_post"
    assert result["qualification"] == "unverified"
    assert result.get("platform_reference") is None
    assert result.get("discussion") is None


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


@pytest.mark.parametrize("source", ["x", "reddit"])
def test_connected_timeout_holds_capacity_until_blocking_reader_has_stopped(
    database, monkeypatch, source
):
    import threading
    import time

    from skriller.contracts import SearchPlan
    from skriller.db import ConversationRepository

    actor = f"x-timeout-{uuid4()}"
    _, _, accepted = prepare(database, monkeypatch, actor, sources=[source])
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, accepted["workspace_id"]) as session:
        store.create(
            session,
            source,
            "oauth",
            SecretPayload(credentials={"access_token": "synthetic-x-token"}),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            scopes=("read", "discover"),
        )
        job = JobRepository.get(session, accepted["job_id"])
        plan = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, job["plan_id"])["interpretation"]
        )
    stopped = threading.Event()
    releases = []

    class BlockingReader:
        def search_page(self, query, **kwargs):
            time.sleep(0.15)
            stopped.set()
            return SearchPage(hits=[], rejected=0, truncated=False, query=query)

    monkeypatch.setattr(service, "permit_call", lambda *args: 10)
    monkeypatch.setattr(service, "acquire", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        service, "release", lambda *args, **kwargs: releases.append(stopped.is_set())
    )
    handler = service.discovery_handler(
        database,
        actor,
        accepted["job_id"],
        Provider(),
        **{("x_reader" if source == "x" else "reddit_reader"): BlockingReader()},
        connection_store=store,
    )
    data, _, _ = handler.run_with_deadline(plan, 0.05)
    assert releases == [True]
    assert stopped.is_set() and data[0]["error"] == "deadline_exceeded"
    assert data[0]["page"] is None


def test_query_stop_is_visible_failure_without_provider_io(database, monkeypatch):
    from skriller.research.queries import build_queries as original

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    monkeypatch.setattr(
        service,
        "build_queries",
        lambda *args: replace(
            original(*args), variants=(), stop_reason="provider_objective_bound_exceeded"
        ),
    )
    provider = Provider()
    run(database, actor, accepted, provider, monkeypatch)
    assert provider.calls == 0
    snapshot = client.get(f"/v1/jobs/{accepted['job_id']}").json()
    assert snapshot["state"] == "failed"
    assert snapshot["result_count"] == 0
    assert any(
        "provider objective bound exceeded" in item
        for item in client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["limitations"]
    )


def test_cancel_interrupts_active_async_source_and_preserves_uncertain_charge(
    database, monkeypatch
):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import sqlalchemy as sa

    from skriller.db.schema import external_calls, reservations

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    started, stopped = threading.Event(), threading.Event()

    class WaitingProvider(Provider):
        async def search(self, query, **kwargs):
            self.calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    provider = WaitingProvider()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run, database, actor, accepted, provider, monkeypatch)
        assert started.wait(2)
        response = client.post(f"/v1/jobs/{accepted['job_id']}/cancel")
        assert response.status_code == 200
        assert response.json()["state"] == "cancelled"
        assert stopped.wait(3)
        assert future.result(timeout=3)[1]["status"] == "source_unavailable"
    assert provider.calls == 1
    with database.tenant(actor, accepted["workspace_id"]) as session:
        call = (
            session.execute(
                sa.select(external_calls).where(external_calls.c.job_id == accepted["job_id"])
            )
            .mappings()
            .one()
        )
        reservation = (
            session.execute(
                sa.select(reservations).where(reservations.c.id == call["reservation_id"])
            )
            .mappings()
            .one()
        )
        assert call["state"] == "uncertain"
        assert reservation["state"] == "committed"
        assert reservation["reconciliation_status"] == "estimated"
    assert client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"] == []


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
        runtime,
        "execute_discovery",
        lambda db, payload, **kwargs: execute_discovery(db, payload, provider, **kwargs),
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
    assert runtime.app.tasks["skriller.jobs.execute_attempt"].run.__module__ == runtime.__name__
    # Real RabbitMQ task publication/delivery; controlled source is explicitly a fixture.
    with start_worker(
        runtime.app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        shutdown_timeout=8,
        loglevel="INFO",
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
    monkeypatch.setattr(runtime, "dispatch", lambda *args: None)
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    monkeypatch.setattr(runtime, "execute_discovery", lambda *args, **kwargs: {"status": status})

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
                raise SearchUnavailable(
                    Failure(code="rate_limited", message="Wait", retry_after_seconds=30)
                )
            return await super().search(query, **kwargs)

    provider = LimitedProvider()
    _, outcome = run(database, actor, accepted, provider, monkeypatch)
    assert outcome["status"] == "checkpointed"
    assert provider.calls == 2
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert response["state"] == "partial" and len(response["results"]) == 1
    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert current_usage(session, accepted["job_id"])[1]["search_calls"] == 2


def test_queued_source_disable_skips_io_retains_results_and_reenable_allows_new_job(
    database, monkeypatch
):
    from skriller.connectors.switches import set_disabled

    actor = f"workflow-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        set_disabled(session, "linkedin", "discover", True)
    provider = Provider()
    run(database, actor, accepted, provider, monkeypatch)
    assert provider.calls == 1
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert len(result["results"]) == 1
    assert result["results"][0]["source"] == "web"
    assert any("source disabled" in item for item in result["limitations"])
    with database.tenant(actor, accepted["workspace_id"]) as session:
        set_disabled(session, "linkedin", "discover", False)
    assert (
        client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"] == result["results"]
    )
    _, _, next_accepted = prepare(database, monkeypatch, actor)
    next_provider = Provider()
    run(database, actor, next_accepted, next_provider, monkeypatch)
    assert next_provider.calls == 2
