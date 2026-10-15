"""Actual copied replay cache plus PostgreSQL/private blob/access boundaries."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError
from scrapling.engines.toolbelt.custom import Response
from scrapling.spiders.cache import ResponseCacheManager

from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, ConnectionUnavailable, SecretPayload
from skriller.connectors.cache import CacheKey, ScopedResponseCache, claim_is_fresh
from skriller.storage import BlobIntegrityError, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


@pytest.fixture
def cache(tmp_path):
    return ScopedResponseCache(EvidenceStorage(LocalBlobBackend(tmp_path / "objects")))


def identity(database):
    actor = str(uuid4())
    return actor, database.create_workspace(actor, "Response cache")["id"]


def key(**kwargs):
    return CacheKey(
        source="linkedin",
        source_url="https://www.linkedin.com/posts/example",
        entity_type="person",
        schema_hash="a" * 64,
        extractor_version="v1",
        **kwargs,
    )


def response(body=b"<html><body>Historical post</body></html>"):
    return Response(
        url=key().source_url,
        content=body,
        status=200,
        reason="OK",
        encoding="utf-8",
        cookies={"session": "synthetic-secret"},
        headers={
            "etag": '"example"',
            "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "content-type": "text/html",
            "set-cookie": "session=synthetic-secret",
        },
        request_headers={"Authorization": "Bearer synthetic-secret"},
        method="GET",
    )


async def test_actual_copied_cache_roundtrip_is_private_and_preserves_dates(
    database, cache, monkeypatch
):
    counts = {"put": 0, "get": 0}
    original_put, original_get = ResponseCacheManager.put, ResponseCacheManager.get

    async def put(*args, **kwargs):
        counts["put"] += 1
        await original_put(*args, **kwargs)

    async def get(*args, **kwargs):
        counts["get"] += 1
        return await original_get(*args, **kwargs)

    monkeypatch.setattr(ResponseCacheManager, "put", put)
    monkeypatch.setattr(ResponseCacheManager, "get", get)
    actor, workspace = identity(database)
    collected = datetime.now(UTC) - timedelta(seconds=1)
    published = collected - timedelta(days=365)
    metadata = await cache.put(
        database,
        actor,
        workspace,
        key(),
        response(),
        collected_at=collected,
        published_at=published,
    )
    hit = await cache.get(database, actor, workspace, key())
    assert hit and hit.response.body == response().body and counts == {"put": 1, "get": 1}
    assert hit.metadata.collected_at == collected and hit.metadata.published_at == published
    assert hit.collected_since(collected - timedelta(seconds=1))
    assert hit.published_since(collected - timedelta(days=30)) is False
    assert hit.response.cookies == {} and not hit.response.request_headers
    assert "set-cookie" not in hit.response.headers
    with database.tenant(actor, workspace) as session:
        serialized = cache.storage.retrieve(session, str(metadata.evidence_id))
        assert b"synthetic-secret" not in serialized and b"Authorization" not in serialized
        assert cache.conditional_headers(session, key()) == {"If-None-Match": '"example"'}


async def test_workspace_connection_schema_and_version_namespaces(database, cache):
    actor, workspace = identity(database)
    other_actor, other_workspace = identity(database)
    await cache.put(database, actor, workspace, key(), response(), collected_at=datetime.now(UTC))
    assert await cache.get(database, other_actor, other_workspace, key()) is None
    assert (
        await cache.get(
            database, actor, workspace, key().model_copy(update={"schema_hash": "b" * 64})
        )
        is None
    )
    assert (
        await cache.get(
            database, actor, workspace, key().model_copy(update={"extractor_version": "v2"})
        )
        is None
    )
    assert (
        await cache.get(database, actor, workspace, key(), expected_content_hash="0" * 64) is None
    )
    assert await cache.get(
        database,
        actor,
        workspace,
        key(),
        expected_content_hash=hashlib.sha256(response().body).hexdigest(),
    )
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, workspace) as session:
        first = store.create(
            session,
            "linkedin",
            "session",
            SecretPayload(credentials={"session_cookie": "fixture"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        second = store.create(
            session,
            "linkedin",
            "session",
            SecretPayload(credentials={"session_cookie": "fixture"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    private = key(access_mode="connection", connection_ref=first.id)
    await cache.put(database, actor, workspace, private, response(), collected_at=datetime.now(UTC))
    assert await cache.get(database, actor, workspace, private)
    assert (
        await cache.get(
            database, actor, workspace, key(access_mode="connection", connection_ref=second.id)
        )
        is None
    )
    with database.tenant(actor, workspace) as session:
        store.revoke(session, first.id)
    with pytest.raises(ConnectionUnavailable):
        await cache.get(database, actor, workspace, private)
    with pytest.raises(ConnectionUnavailable):
        await cache.get(database, other_actor, other_workspace, private)


async def test_expired_cache_and_unknown_publication_do_not_refresh_old_role(database, cache):
    actor, workspace = identity(database)
    now = datetime.now(UTC)
    await cache.put(database, actor, workspace, key(), response(), collected_at=now, ttl_seconds=1)
    hit = await cache.get(database, actor, workspace, key())
    assert hit and hit.published_since(now - timedelta(days=1)) is None
    assert not claim_is_fresh(now - timedelta(days=90), max_age_seconds=86400, now=now)
    assert not claim_is_fresh(None, max_age_seconds=86400, now=now)
    assert claim_is_fresh(now - timedelta(seconds=10), max_age_seconds=86400, now=now)
    await asyncio.sleep(1.1)
    assert await cache.get(database, actor, workspace, key()) is None
    with database.tenant(actor, workspace) as session:
        assert cache.conditional_headers(session, key()) == {}


async def test_blob_tampering_fails_integrity_before_upstream_decode(database, cache):
    from skriller.db import ResearchRepository

    actor, workspace = identity(database)
    metadata = await cache.put(
        database, actor, workspace, key(), response(), collected_at=datetime.now(UTC)
    )
    with database.tenant(actor, workspace) as session:
        row = ResearchRepository.get_evidence(session, str(metadata.evidence_id))
        path = cache.storage.backend.directory / row["object_key"]
    path.write_bytes(b"corrupted")
    with pytest.raises(BlobIntegrityError):
        await cache.get(database, actor, workspace, key())


async def test_erasure_during_replay_hides_cached_bytes_and_validators(
    database, cache, monkeypatch
):
    from skriller.db import ResearchRepository
    from skriller.erasure import erase

    actor, workspace = identity(database)
    with database.tenant(actor, workspace) as session:
        target = ResearchRepository.entity(
            session, "person", "Synthetic subject", attributes={"url": key().source_url}
        )
    await cache.put(database, actor, workspace, key(), response(), collected_at=datetime.now(UTC))
    original = ResponseCacheManager.get

    async def erase_during_replay(*args, **kwargs):
        replay = await original(*args, **kwargs)
        with database.tenant(actor, workspace) as session:
            erase(session, cache.storage, target["id"], request_key="cache-replay-erasure")
        return replay

    monkeypatch.setattr(ResponseCacheManager, "get", erase_during_replay)
    assert await cache.get(database, actor, workspace, key()) is None
    with database.tenant(actor, workspace) as session:
        assert cache.conditional_headers(session, key()) == {}


def test_rejects_credential_urls_invalid_scope_and_naive_freshness():
    for updates in [
        {"source_url": "https://www.linkedin.com/posts/example?access_token=secret"},
        {"access_mode": "connection"},
        {"connection_ref": uuid4()},
        {"schema_hash": "invalid"},
    ]:
        with pytest.raises(ValidationError):
            CacheKey(**(key().model_dump() | updates))
    with pytest.raises(ValueError):
        claim_is_fresh(datetime.now(), max_age_seconds=86400)


async def test_late_older_collection_cannot_replace_newer_content(database, cache):
    actor, workspace = identity(database)
    now = datetime.now(UTC)
    await cache.put(database, actor, workspace, key(), response(b"new content"), collected_at=now)
    await cache.put(
        database,
        actor,
        workspace,
        key(),
        response(b"old content"),
        collected_at=now - timedelta(minutes=1),
    )
    hit = await cache.get(database, actor, workspace, key())
    assert hit and hit.response.body == b"new content" and hit.metadata.collected_at == now


async def test_connection_expiration_and_revocation_during_replay_are_rechecked(
    database, cache, monkeypatch
):
    import sqlalchemy as sa

    from skriller.connections.tables import connections

    actor, workspace = identity(database)
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, workspace) as session:
        reference = store.create(
            session,
            "linkedin",
            "session",
            SecretPayload(credentials={"session_cookie": "fixture"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    private = key(access_mode="connection", connection_ref=reference.id)
    await cache.put(database, actor, workspace, private, response(), collected_at=datetime.now(UTC))
    original = ResponseCacheManager.get

    async def revoke_during_replay(*args, **kwargs):
        replay = await original(*args, **kwargs)
        with database.tenant(actor, workspace) as session:
            store.revoke(session, reference.id)
        return replay

    monkeypatch.setattr(ResponseCacheManager, "get", revoke_during_replay)
    with pytest.raises(ConnectionUnavailable):
        await cache.get(database, actor, workspace, private)
    with database.tenant(actor, workspace) as session:
        expired = store.create(
            session,
            "linkedin",
            "session",
            SecretPayload(credentials={"session_cookie": "fixture"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.execute(
            sa.update(connections)
            .where(connections.c.id == str(expired.id))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with pytest.raises(ConnectionUnavailable):
        await cache.get(
            database, actor, workspace, key(access_mode="connection", connection_ref=expired.id)
        )
