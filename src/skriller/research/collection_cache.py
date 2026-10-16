"""Opt-in short-lived public HTTP replay using the copied scoped cache."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic

from skriller.connectors.cache import CacheKey, ScopedResponseCache
from skriller.connectors.classification import classify_page
from skriller.connectors.fetch import FetchArtifact, FetchUnavailable
from skriller.connectors.switches import is_disabled
from skriller.contracts import Failure
from skriller.jobs.control import permit_call


def cache_key(url, entity_type):
    return CacheKey(
        source="web",
        source_url=url,
        entity_type=entity_type,
        schema_hash=sha256(b"public-http-body-v1").hexdigest(),
        extractor_version="public-http-v1",
    )


def read_cached(database, storage, context, key):
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        if is_disabled(session, "web", "read") or permit_call(session, str(context.job_id)) <= 0:
            raise FetchUnavailable(
                Failure(code="access_denied", message="Job no longer permits cached reads")
            )
    hit = asyncio.run(
        ScopedResponseCache(storage).get(database, context.actor_id, str(context.workspace_id), key)
    )
    if hit is None:
        return None
    started = monotonic()
    content_type = next(
        (
            str(value).split(";", 1)[0].strip().lower()
            for name, value in hit.response.headers.items()
            if str(name).lower() == "content-type"
        ),
        "application/octet-stream",
    )
    classification = classify_page(
        hit.response.body, source="web", final_url=key.source_url, content_type=content_type
    )
    if not classification.accepts_content:
        raise FetchUnavailable(
            Failure(code="schema_invalid", message="Cached content is not a readable page")
        )
    return FetchArtifact(
        response=hit.response,
        source="web",
        requested_url=key.source_url,
        final_url=key.source_url,
        collected_at=hit.metadata.collected_at,
        content_type=content_type,
        content_hash=hit.metadata.content_hash,
        decoded_bytes=len(hit.response.body),
        network_seconds=0,
        parser_seconds=monotonic() - started,
        attempts=0,
        workspace_id=str(context.workspace_id),
        job_id=str(context.job_id),
        classification=classification,
        access_route="tenant_fresh_public_cache",
        cache_expires_at=hit.metadata.expires_at,
    )


def needs_revalidation(artifact):
    """Use validators in the second half of a fresh public entry's original TTL.

    Expired objects are never read for this purpose. A successful 304 retains the
    original body collection date and expiry; it does not refresh a role claim.
    """
    return (
        artifact.cache_expires_at is not None
        and datetime.now(UTC)
        >= artifact.collected_at + (artifact.cache_expires_at - artifact.collected_at) / 2
        and any(
            str(name).lower() in {"etag", "last-modified"} for name in artifact.response.headers
        )
    )


def write_cached(database, storage, context, key, artifact, ttl_seconds):
    # Redirects and browser renderings need distinct route/identity semantics.
    if (
        artifact.final_url != key.source_url
        or artifact.access_route != "scrapling_http_guarded_proxy"
        or not artifact.classification.accepts_content
    ):
        return
    asyncio.run(
        ScopedResponseCache(storage).put(
            database,
            context.actor_id,
            str(context.workspace_id),
            key,
            artifact.response,
            collected_at=artifact.collected_at,
            ttl_seconds=ttl_seconds,
            context=context,
        )
    )
