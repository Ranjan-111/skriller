"""Access-scoped freshness around the actual copied Scrapling response cache.

Upstream get/put are reused for serialization/replay, exclusively in private
short-lived staging. Canonical immutable bytes and mutable cache pointers use existing
EvidenceStorage and tenant entities. No credentials enter the replay envelope.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scrapling.core.utils import log
from scrapling.engines.toolbelt.custom import Response
from scrapling.spiders.cache import ResponseCacheManager
from sqlalchemy.dialects.postgresql import insert

from skriller.connections.store import ConnectionStore, ConnectionUnavailable
from skriller.connectors.fetch import _EngineLogFilter
from skriller.contracts import Source
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.storage import BlobUnavailable, EvidenceStorage

# Reuse the reviewed product guard: replay constructors must not log private URLs.
log.addFilter(_EngineLogFilter())


class CacheKey(BaseModel):
    """Trusted adapter identity; never accept private/public routing from a browser."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Source
    source_url: str = Field(max_length=4096)
    entity_type: Literal["person", "company", "creator", "discussion"]
    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_version: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    access_mode: Literal["public", "connection"] = "public"
    connection_ref: UUID | None = None

    @model_validator(mode="after")
    def validate_access(self):
        normalized = normalize_public_http_url(self.source_url)
        if normalized != self.source_url:
            raise ValueError("Cache URL must be canonical public HTTP URL")
        if any(
            name.casefold() in {"token", "access_token", "api_key", "password", "cookie", "key"}
            for name, _ in parse_qsl(urlsplit(self.source_url).query)
        ):
            raise ValueError("Cache URL cannot contain credentials")
        if (self.access_mode == "connection") != (self.connection_ref is not None):
            raise ValueError("Connection cache requires an opaque access reference")
        return self

    def fingerprint(self, workspace_id: str) -> bytes:
        return hashlib.sha256(
            json.dumps(
                [1, str(UUID(workspace_id)), self.model_dump(mode="json")],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).digest()


class CacheMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    evidence_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    collected_at: datetime
    expires_at: datetime
    published_at: datetime | None = None
    etag: str | None = Field(default=None, max_length=1024)
    last_modified: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def aware_dates(self):
        if (
            any(
                value.tzinfo is None
                for value in (
                    self.collected_at,
                    self.expires_at,
                    *([self.published_at] if self.published_at else []),
                )
            )
            or self.expires_at <= self.collected_at
        ):
            raise ValueError("Cache timestamps require valid timezone-aware intervals")
        if any(
            value and ("\r" in value or "\n" in value) for value in (self.etag, self.last_modified)
        ):
            raise ValueError("Invalid conditional response validator")
        return self


@dataclass(frozen=True)
class CacheHit:
    response: Response
    metadata: CacheMetadata

    def published_since(self, threshold: datetime) -> bool | None:
        if threshold.tzinfo is None:
            raise ValueError("Publication threshold requires timezone")
        if self.metadata.published_at is None:
            return None
        return self.metadata.published_at >= threshold

    def collected_since(self, threshold: datetime) -> bool:
        if threshold.tzinfo is None:
            raise ValueError("Collection threshold requires timezone")
        return self.metadata.collected_at >= threshold


class ScopedResponseCache:
    def __init__(self, storage: EvidenceStorage, *, max_body_bytes: int = 2 * 1024 * 1024):
        if not 1 <= max_body_bytes <= 2 * 1024 * 1024:
            raise ValueError("Cache body limit exceeds supported bounds")
        self.storage = storage
        self.max_body_bytes = max_body_bytes
        self.connections = ConnectionStore(None)

    def _access(self, session, key: CacheKey):
        workspace = scope(session)
        if key.connection_ref is not None:
            reference = self.connections.metadata(session, key.connection_ref)
            if (
                reference.state != "active"
                or reference.source != key.source
                or "read" not in reference.scopes
            ):
                raise ConnectionUnavailable()
        return workspace

    def _latest(self, session, key: CacheKey):
        workspace = self._access(session, key)
        canonical = "response-cache:" + key.fingerprint(workspace).hex()
        row = session.execute(
            sa.select(entities.c.attributes)
            .where(
                entities.c.workspace_id == workspace,
                entities.c.kind == "other",
                entities.c.canonical_key == canonical,
            )
            .order_by(
                entities.c.attributes["collected_at"]
                .as_string()
                .cast(sa.DateTime(timezone=True))
                .desc(),
                entities.c.created_at.desc(),
                entities.c.id.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        return CacheMetadata.model_validate(row) if row is not None else None

    async def put(
        self,
        database,
        actor_id: str,
        workspace_id: str,
        key: CacheKey,
        response: Response,
        *,
        ttl_seconds: int = 3600,
        collected_at: datetime,
        published_at: datetime | None = None,
    ):
        now = datetime.now(UTC)
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= 86400
        ):
            raise ValueError("Cache TTL must be 1–86400 seconds")
        if (
            collected_at.tzinfo is None
            or collected_at > now
            or collected_at + timedelta(seconds=ttl_seconds) <= now
        ):
            raise ValueError("Cache collection time must be recent and timezone-aware")
        if (
            len(response.body) > self.max_body_bytes
            or response.status != 200
            or response.url != key.source_url
        ):
            raise ValueError("Only matching bounded successful responses are cacheable")
        headers = {
            str(name).lower(): str(value)
            for name, value in response.headers.items()
            if str(name).lower() in {"etag", "last-modified", "content-type"}
        }
        if any(len(value) > 1024 or "\r" in value or "\n" in value for value in headers.values()):
            raise ValueError("Invalid bounded cache response headers")
        # The copied cache otherwise persists session cookies and request headers.
        # Clear these BEFORE upstream serialization, not by post-hoc redaction.
        safe = Response(
            url=key.source_url,
            content=response.body,
            status=200,
            reason="OK",
            encoding=response.encoding,
            cookies={},
            headers=headers,
            request_headers={},
            method="GET",
        )
        fingerprint = key.fingerprint(workspace_id)
        with TemporaryDirectory(prefix="skriller-response-cache-") as directory:
            manager = ResponseCacheManager(directory)
            await manager.put(fingerprint, safe)
            path = Path(directory) / (fingerprint.hex() + ".json")
            if not path.exists():
                raise BlobUnavailable("Cache serialization unavailable")
            serialized = path.read_bytes()

        def persist():
            with database.tenant(actor_id, workspace_id) as session:
                from skriller.erasure import privacy_lock, suppressed

                privacy_lock(session)

                if suppressed(session, url=key.source_url):
                    raise BlobUnavailable("Suppressed response cannot be cached")
                workspace = self._access(session, key)
                metadata = CacheMetadata(
                    evidence_id=UUID(int=0),
                    content_hash=hashlib.sha256(response.body).hexdigest(),
                    collected_at=collected_at,
                    expires_at=collected_at + timedelta(seconds=ttl_seconds),
                    published_at=published_at,
                    etag=headers.get("etag"),
                    last_modified=headers.get("last-modified"),
                )
                record = self.storage.store(
                    session,
                    serialized,
                    source_url=key.source_url,
                    source_platform=key.source,
                    collected_at=collected_at,
                    expires_at=metadata.expires_at,
                )
                metadata = metadata.model_copy(update={"evidence_id": UUID(record["id"])})
                statement = insert(entities).values(
                    workspace_id=workspace,
                    id=str(uuid4()),
                    kind="other",
                    canonical_key="response-cache:" + fingerprint.hex(),
                    attributes=metadata.model_dump(mode="json"),
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["workspace_id", "kind", "canonical_key"],
                        set_={"attributes": statement.excluded.attributes},
                        where=entities.c.attributes["collected_at"]
                        .as_string()
                        .cast(sa.DateTime(timezone=True))
                        < collected_at,
                    )
                )
                return metadata

        return await asyncio.to_thread(persist)

    async def get(
        self,
        database,
        actor_id: str,
        workspace_id: str,
        key: CacheKey,
        *,
        expected_content_hash: str | None = None,
    ) -> CacheHit | None:
        def load():
            with database.tenant(actor_id, workspace_id) as session:
                from skriller.erasure import suppressed

                if suppressed(session, url=key.source_url):
                    return None
                metadata = self._latest(session, key)
                if metadata is None or metadata.expires_at <= datetime.now(UTC):
                    return None
                if (
                    expected_content_hash is not None
                    and metadata.content_hash != expected_content_hash
                ):
                    return None
                return metadata, self.storage.retrieve(session, str(metadata.evidence_id))

        loaded = await asyncio.to_thread(load)
        if loaded is None:
            return None
        metadata, serialized = loaded
        if len(serialized) > 3 * 1024 * 1024:
            raise BlobUnavailable("Cache serialization exceeds supported bounds")
        fingerprint = key.fingerprint(workspace_id)
        with TemporaryDirectory(prefix="skriller-response-cache-") as directory:
            (Path(directory) / (fingerprint.hex() + ".json")).write_bytes(serialized)
            response = await ResponseCacheManager(directory).get(fingerprint)
        if (
            response is None
            or response.url != key.source_url
            or response.status != 200
            or response.cookies
            or response.request_headers
        ):
            raise BlobUnavailable("Cache response unavailable")
        if (
            len(response.body) > self.max_body_bytes
            or hashlib.sha256(response.body).hexdigest() != metadata.content_hash
        ):
            raise BlobUnavailable("Cache response digest mismatch")

        # Recheck revocation after staging before returning previously private bytes.
        def check_access():
            with database.tenant(actor_id, workspace_id) as session:
                self._access(session, key)

        await asyncio.to_thread(check_access)
        if metadata.expires_at <= datetime.now(UTC):
            return None
        return CacheHit(response, metadata)

    def conditional_headers(self, session, key: CacheKey) -> dict[str, str]:
        metadata = self._latest(session, key)
        if metadata is None or metadata.expires_at <= datetime.now(UTC):
            return {}
        if metadata.etag:
            return {"If-None-Match": metadata.etag}
        return {"If-Modified-Since": metadata.last_modified} if metadata.last_modified else {}


def claim_is_fresh(
    verified_at: datetime | None, *, max_age_seconds: int, now: datetime | None = None
) -> bool:
    """A cache hit/retrieval time cannot renew a claim's independent verification."""
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int)
        or not 1 <= max_age_seconds <= 86400 * 365
    ):
        raise ValueError("Claim freshness window must be bounded")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or (verified_at is not None and verified_at.tzinfo is None):
        raise ValueError("Claim verification timestamps require timezone")
    return (
        verified_at is not None
        and current - timedelta(seconds=max_age_seconds) <= verified_at <= current
    )
