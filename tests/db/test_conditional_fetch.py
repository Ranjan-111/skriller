"""Real copied HTTP engine, guarded loopback proxy and immutable cached evidence."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_fetch
from scrapling.engines.toolbelt.custom import Response
from test_collection_workflow import discover
from test_fetch import ctx

from skriller.connectors.cache import ScopedResponseCache
from skriller.connectors.fetch import FetchUnavailable, HTTPFetcher
from skriller.db import ResearchRepository
from skriller.jobs.budget import current_usage
from skriller.research.collection import execute_collection
from skriller.research.collection_cache import cache_key, needs_revalidation, read_cached
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def cached(database, context, storage, body, path="conditional"):
    key = cache_key(f"http://example.com/{path}", "person")
    original = datetime.now(UTC) - timedelta(seconds=200)
    response = Response(
        key.source_url,
        body,
        200,
        "OK",
        {},
        {"Content-Type": "text/html", "ETag": '"fixture-v1"'},
        {},
        adaptive=False,
    )
    metadata = asyncio.run(
        ScopedResponseCache(storage).put(
            database,
            context.actor_id,
            str(context.workspace_id),
            key,
            response,
            collected_at=original,
            ttl_seconds=300,
        )
    )
    artifact = read_cached(database, storage, context, key)
    assert artifact is not None and needs_revalidation(artifact)
    return key, metadata, artifact


def test_304_uses_verified_body_and_original_dates_with_one_accounted_request(
    database, proxy, tmp_path
):
    endpoint, requests, body = proxy
    context = ctx(database)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    key, metadata, hit = cached(database, context, storage, body)
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context,
        key.source_url,
        source="web",
        operation_key=uuid4().hex,
        revalidation=hit,
    )
    assert artifact.response.body == body and artifact.response.status == 200
    assert artifact.collected_at == hit.collected_at
    assert artifact.cache_expires_at == metadata.expires_at
    assert artifact.revalidated_at > artifact.collected_at
    assert artifact.access_route == "scrapling_http_conditional" and artifact.attempts == 1
    assert requests == ["/conditional"]
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 1
        persisted = artifact.persist(session, storage)
        body_record = ResearchRepository.get_evidence(session, persisted["id"])
        assert body_record["expires_at"] == metadata.expires_at
        assert (
            persisted["artifact_metadata"]["revalidated_at"] == artifact.revalidated_at.isoformat()
        )
    current = read_cached(database, storage, context, key)
    assert (
        current.collected_at == hit.collected_at and current.cache_expires_at == metadata.expires_at
    )


def test_changed_200_replaces_body_instead_of_reusing_cached_representation(
    database, proxy, tmp_path
):
    endpoint, _, body = proxy
    context = ctx(database)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    key, _, hit = cached(database, context, storage, body, "conditional-changed")
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context,
        key.source_url,
        source="web",
        operation_key=uuid4().hex,
        revalidation=hit,
    )
    assert artifact.response.body.endswith(b"<!-- new representation -->")
    assert artifact.collected_at > hit.collected_at and artifact.revalidated_at is None
    assert artifact.access_route == "scrapling_http_guarded_proxy"


@pytest.mark.parametrize("case", ["mismatch", "expired_during_read", "unsolicited"])
def test_unbound_or_expired_304_never_returns_cached_body(database, proxy, tmp_path, case):
    endpoint, _, body = proxy
    context = ctx(database)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    path = {
        "mismatch": "conditional-mismatch",
        "expired_during_read": "conditional-late",
        "unsolicited": "unsolicited304",
    }[case]
    key, _, hit = cached(database, context, storage, body, path)
    if case == "expired_during_read":
        hit = replace(hit, cache_expires_at=datetime.now(UTC) + timedelta(seconds=0.15))
    with pytest.raises(FetchUnavailable, match="Conditional source evidence"):
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            context,
            key.source_url,
            source="web",
            operation_key=uuid4().hex,
            revalidation=None if case == "unsolicited" else hit,
        )
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 1


def test_foreign_or_tampered_cache_refused_before_request(database, proxy, tmp_path):
    endpoint, requests, body = proxy
    context = ctx(database)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    key, _, hit = cached(database, context, storage, body)
    for altered in [replace(hit, workspace_id=str(uuid4())), replace(hit, content_hash="0" * 64)]:
        with pytest.raises(ValueError, match="matching scoped cache"):
            HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
                context,
                key.source_url,
                source="web",
                operation_key=uuid4().hex,
                revalidation=altered,
            )
    assert requests == []


def test_collector_revalidates_second_half_ttl_without_renewing_cached_evidence(
    database, monkeypatch, proxy, tmp_path
):
    from skriller.contracts import ExecutionContext
    from skriller.jobs.worker import TaskIdentity

    endpoint, requests, body = proxy
    actor = f"conditional-collection-{uuid4()}"
    client, accepted, _, tasks, _ = discover(
        database, monkeypatch, actor, endpoint, ["conditional"]
    )
    identity = TaskIdentity.model_validate(tasks[0])
    context = ExecutionContext(
        actor_id=actor,
        workspace_id=identity.workspace_id,
        job_id=identity.job_id,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=20),
        attempt_budget=3,
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    key, metadata, _ = cached(database, context, storage, body)
    assert (
        execute_collection(database, tasks[0], endpoint, storage=storage, cache_ttl_seconds=300)[
            "status"
        ]
        == "checkpointed"
    )
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert result["results"][0]["collection"]["status"] == "read"
    assert requests == ["/conditional"]
    current = asyncio.run(
        ScopedResponseCache(storage).get(database, actor, accepted["workspace_id"], key)
    )
    assert current.metadata.evidence_id == metadata.evidence_id
    assert current.metadata.collected_at == metadata.collected_at
    assert current.metadata.expires_at == metadata.expires_at
