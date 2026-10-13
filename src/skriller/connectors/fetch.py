"""Bounded product glue around the copied Scrapling HTTP session and parser.

Public DNS pinning is enforced by the configured GuardedProxy; deployment must
also forbid a worker's alternative egress routes (SKR-027). No direct fallback.
"""

import ipaddress
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import get_args
from urllib.parse import urljoin, urlsplit

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from curl_cffi import CurlOpt
from scrapling.core.utils import log
from scrapling.engines.static import FetcherSession
from scrapling.engines.toolbelt.custom import Response
from scrapling.spiders.throttle import parse_retry_after

from skriller.connectors.classification import PageClassification, classify_page
from skriller.contracts import ExecutionContext, Failure, Source
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile, reserve
from skriller.jobs.capacity import CapacityUnavailable, acquire, release
from skriller.jobs.control import permit_call


class _EngineLogFilter(logging.Filter):
    def filter(self, record):
        # Copied engines log raw request URLs/errors. Product diagnostics below
        # carry typed outcomes and metrics instead, without query/header leakage.
        return record.pathname.rsplit("/", 1)[-1] not in {"static.py", "custom.py"}


log.addFilter(_EngineLogFilter())


class FetchUnavailable(RuntimeError):
    def __init__(self, failure: Failure, classification: PageClassification | None = None):
        self.classification = classification
        self.failure = failure
        super().__init__(failure.message)


@dataclass(frozen=True)
class FetchArtifact:
    response: Response
    source: Source
    requested_url: str
    final_url: str
    collected_at: datetime
    content_type: str
    content_hash: str
    decoded_bytes: int
    network_seconds: float
    parser_seconds: float
    attempts: int
    workspace_id: str
    job_id: str
    classification: PageClassification
    access_route: str = "scrapling_http_guarded_proxy"
    evidence_kind: str = "page_read"

    def persist(self, session, storage):
        """Persist raw bytes plus private JSON metadata referencing their evidence ID."""
        if not self.classification.accepts_content:
            raise _failure(
                "access_denied",
                "Blocked content cannot become read evidence",
                classification=self.classification,
            )
        if session.info["workspace_id"] != self.workspace_id:
            raise PermissionError("Artifact workspace differs from persistence scope")
        if permit_call(session, self.job_id) <= 0:
            raise _failure("deadline_exceeded", "Job no longer permits artifact writes")
        if sha256(self.response.body).hexdigest() != self.content_hash:
            raise ValueError("Artifact bytes changed after collection")
        record = storage.store(
            session,
            self.response.body,
            source_url=self.final_url,
            source_platform=self.source,
            collected_at=self.collected_at,
        )
        metadata = {
            "schema_version": 1,
            "body_evidence_id": record["id"],
            "raw_object_ref": record["object_key"],
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "source": self.source,
            "collected_at": self.collected_at.isoformat(),
            "content_type": self.content_type,
            "content_hash": self.content_hash,
            "decoded_bytes": self.decoded_bytes,
            "access_route": self.access_route,
            "evidence_kind": self.classification.evidence_kind,
            "classification": self.classification.status,
            "next_method": self.classification.next_method,
            "network_seconds": self.network_seconds,
            "parser_seconds": self.parser_seconds,
            "attempts": self.attempts,
        }
        try:
            metadata_record = storage.store(
                session,
                json.dumps(metadata, sort_keys=True).encode(),
                source_url=self.final_url,
                source_platform=self.source,
                collected_at=self.collected_at,
            )
        except BaseException:
            storage.backend.delete(self.workspace_id, record["object_key"])
            raise
        return {
            **record,
            "artifact_metadata": metadata,
            "metadata_evidence_id": metadata_record["id"],
        }


def _failure(code, message, retry=None, classification=None):
    return FetchUnavailable(
        Failure(code=code, message=message, retry_after_seconds=retry), classification
    )


def _public_url(value):
    value = normalize_public_http_url(value)
    parsed = urlsplit(value)
    if len(value) > 4096 or parsed.port not in (None, 80 if parsed.scheme == "http" else 443):
        raise ValueError("Unsupported public source URL")
    return value


class HTTPFetcher:
    def __init__(
        self,
        database,
        *,
        trusted_proxy_url: str,
        max_body_bytes=5 * 1024 * 1024,
        timeout_seconds=20,
        max_redirects=2,
    ):
        parsed = urlsplit(trusted_proxy_url)
        # The proxy address is operator configuration, never a target URL option.
        if (
            parsed.scheme != "http"
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not parsed.port
        ):
            raise ValueError("Explicit trusted HTTP proxy endpoint required")
        if not parsed.hostname:
            raise ValueError("Trusted proxy hostname required")
        if parsed.hostname not in {"localhost", "egress-proxy"}:
            try:
                if not ipaddress.ip_address(parsed.hostname).is_loopback:
                    raise ValueError("Only the configured local guarded proxy is permitted")
            except ValueError as error:
                raise ValueError("Only the configured local guarded proxy is permitted") from error
        if (
            not 1 <= max_body_bytes <= 5 * 1024 * 1024
            or not 0 < timeout_seconds <= 20
            or not 0 <= max_redirects <= 2
        ):
            raise ValueError("Fetch limits exceed pilot bounds")
        self.database = database
        self.proxy = trusted_proxy_url
        self.max_body_bytes, self.timeout_seconds, self.max_redirects = (
            max_body_bytes,
            timeout_seconds,
            max_redirects,
        )

    def fetch(
        self,
        context: ExecutionContext,
        url: str,
        *,
        source: Source,
        operation_key: str,
        minimum_interval: float = 0,
    ) -> FetchArtifact:
        if source not in get_args(Source):
            raise ValueError("Unsupported source identity")
        if context.connection_ref is not None:
            raise _failure(
                "unsupported_operation", "This adapter only supports public source reads"
            )
        if context.reservation_id is not None:
            raise ValueError(
                "HTTP fetch owns its per-attempt budget; do not double-reserve a stage"
            )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", operation_key):
            raise ValueError("Bounded fetch operation identity required")
        try:
            requested = _public_url(url)
        except ValueError:
            raise _failure("access_denied", "Source is outside public HTTP policy") from None
        if context.attempt_budget < 1:
            raise _failure("budget_exhausted", "No fetch attempts remain")
        current, network_seconds, attempts_used = requested, 0.0, 0
        # Reuse one copied connection/session across bounded manual redirect hops.
        with FetcherSession(
            proxy=self.proxy,
            impersonate=None,
            stealthy_headers=False,
            follow_redirects=False,
            retries=0,
            verify=True,
            selector_config={"adaptive": False},
        ) as engine:
            engine._curl_session.trust_env = False
            engine._curl_session.curl_options[CurlOpt.NOPROXY] = ""
            engine._curl_session.curl_options[CurlOpt.MAXFILESIZE_LARGE] = self.max_body_bytes
            for hop in range(self.max_redirects + 1):
                remaining = (context.deadline - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    raise _failure("deadline_exceeded", "Fetch deadline reached")
                if attempts_used >= context.attempt_budget:
                    raise _failure("budget_exhausted", "Fetch attempts exhausted")
                # Commit persisted deadline/state control before an expected
                # refusal is raised, so the tenant transaction cannot undo it.
                with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    permitted = permit_call(session, str(context.job_id))
                if permitted <= 0:
                    raise _failure("deadline_exceeded", "Job no longer permits source reads")
                remaining = min(remaining, permitted)
                digest = sha256(current.encode()).hexdigest()
                prefix = f"fetch:{digest}:"
                key = f"{prefix}{operation_key}:{hop}"
                with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    job = locked_job(session, str(context.job_id))
                    plan = ConversationRepository.get_plan(session, job["plan_id"])
                    if source not in plan["interpretation"]["sources"]:
                        raise _failure("access_denied", "Source was not approved by this plan")
                    if plan["revision"] != context.plan_revision:
                        raise ValueError("Fetch plan revision mismatch")
                    remaining = min(remaining, permit_call(session, job["id"]))
                    if remaining <= 0:
                        raise _failure("deadline_exceeded", "Job no longer permits source reads")
                    existing = session.execute(
                        sa.select(reservations.c.id).where(
                            reservations.c.workspace_id == str(context.workspace_id),
                            reservations.c.job_id == job["id"],
                            reservations.c.idempotency_key == key,
                        )
                    ).first()
                    if existing:
                        raise _failure(
                            "access_denied", "Fetch operation has already been accounted"
                        )
                    count = session.execute(
                        sa.select(sa.func.count())
                        .select_from(reservations)
                        .where(
                            reservations.c.workspace_id == str(context.workspace_id),
                            reservations.c.job_id == job["id"],
                            reservations.c.idempotency_key.startswith(prefix),
                        )
                    ).scalar_one()
                    if count >= 3:
                        raise _failure("budget_exhausted", "Per-URL fetch attempt limit reached")
                    try:
                        lease = acquire(
                            session,
                            job["id"],
                            kind="http",
                            source=source,
                            host=urlsplit(current).hostname,
                            ttl_seconds=max(1, math.ceil(min(remaining, self.timeout_seconds))),
                            minimum_interval=minimum_interval,
                        )
                        reservation = reserve(session, job["id"], key, 0, {"fetch_attempts": 1})
                    except CapacityUnavailable:
                        raise _failure(
                            "rate_limited", "Source capacity or cadence is occupied"
                        ) from None
                    except BudgetExhausted:
                        release(session, lease)
                        raise _failure("budget_exhausted", "Job fetch budget exhausted") from None
                buffer = bytearray()
                oversized = False

                def consume(chunk, target=buffer):
                    nonlocal oversized
                    if len(target) + len(chunk) > self.max_body_bytes:
                        oversized = True
                        return 0
                    target.extend(chunk)
                    return len(chunk)

                started = monotonic()
                succeeded, headers, reply = False, {}, None
                attempts_used += 1
                try:
                    timeout = min(
                        remaining, self.timeout_seconds, lease.deadline_monotonic - monotonic()
                    )
                    if timeout <= 0:
                        raise TimeoutError("Dispatch window expired")
                    reply = engine.get(
                        current,
                        timeout=timeout,
                        follow_redirects=False,
                        retries=0,
                        content_callback=consume,
                        discard_cookies=True,
                        headers={"Accept": "text/html,application/xhtml+xml,text/plain"},
                    )
                    headers = {str(k).lower(): str(v) for k, v in reply.headers.items()}
                    succeeded = True
                except Exception as error:  # noqa: BLE001 - redact source URL/provider exceptions
                    if oversized or getattr(error, "code", None) == 63:
                        raise _failure(
                            "budget_exhausted", "Decoded source exceeds body budget"
                        ) from None
                    raise _failure(
                        "source_unavailable", "Source request could not complete within its limits"
                    ) from None
                finally:
                    elapsed = monotonic() - started
                    network_seconds += elapsed
                    with self.database.tenant(
                        context.actor_id, str(context.workspace_id)
                    ) as session:
                        locked_job(session, str(context.job_id))
                        reconcile(
                            session,
                            str(context.job_id),
                            reservation["id"],
                            status="confirmed" if succeeded else "estimated",
                            cost=0,
                            actual_dimensions={"fetch_attempts": 1} if succeeded else None,
                        )
                        release(
                            session,
                            lease,
                            latency=None
                            if reply is not None and reply.status in {301, 302, 303, 307, 308}
                            else elapsed,
                            ok=succeeded and reply is not None and reply.status < 400,
                            headers=headers,
                            minimum_interval=minimum_interval,
                        )
                if reply.status in {301, 302, 303, 307, 308}:
                    if hop == self.max_redirects or not headers.get("location"):
                        raise _failure("source_unavailable", "Redirect budget exhausted")
                    try:
                        current = _public_url(urljoin(current, headers["location"]))
                    except ValueError:
                        raise _failure(
                            "access_denied", "Redirect target is outside public HTTP policy"
                        ) from None
                    continue
                if reply.status == 429:
                    delay = parse_retry_after(headers)
                    delay = (
                        min(math.ceil(delay), 86400)
                        if delay is not None and math.isfinite(delay)
                        else None
                    )
                    classification = classify_page(
                        bytes(buffer), source=source, final_url=current, status=reply.status
                    )
                    raise _failure(
                        "rate_limited", "Source requested backoff", delay, classification
                    )
                if reply.status in {401, 403}:
                    classification = classify_page(
                        bytes(buffer), source=source, final_url=current, status=reply.status
                    )
                    raise _failure(
                        "auth_required" if reply.status == 401 else "access_denied",
                        "Source denied this read",
                        classification=classification,
                    )
                if reply.status == 404:
                    raise _failure("not_found", "Source page was not found")
                if not 200 <= reply.status < 300:
                    raise _failure("source_unavailable", "Source returned an unavailable response")
                content_type = headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise _failure("unsupported_operation", "Source content type is not supported")
                raw = bytes(buffer)
                with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    if (
                        permit_call(session, str(context.job_id)) <= 0
                        or datetime.now(UTC) >= context.deadline
                    ):
                        raise _failure(
                            "deadline_exceeded", "Read finished after its execution window"
                        )
                parse_started = monotonic()
                parsed_response = Response(
                    current,
                    raw,
                    reply.status,
                    reply.reason,
                    {},
                    dict(reply.headers),
                    {},
                    adaptive=False,
                )
                classification = classify_page(
                    raw,
                    source=source,
                    final_url=current,
                    status=reply.status,
                    content_type=content_type,
                    document=parsed_response,
                )
                if not classification.accepts_content:
                    code = {
                        "challenge": "challenge_detected",
                        "auth_required": "auth_required",
                        "access_denied": "access_denied",
                        "rate_limited": "rate_limited",
                        "unsupported": "unsupported_operation",
                    }.get(classification.status, "source_unavailable")
                    raise _failure(
                        code,
                        "Source content is not ready for extraction",
                        classification=classification,
                    )
                return FetchArtifact(
                    parsed_response,
                    source,
                    requested,
                    current,
                    datetime.now(UTC),
                    content_type,
                    sha256(raw).hexdigest(),
                    len(raw),
                    network_seconds,
                    monotonic() - parse_started,
                    attempts_used,
                    str(context.workspace_id),
                    str(context.job_id),
                    classification,
                    evidence_kind=classification.evidence_kind,
                )
        raise _failure("source_unavailable", "Source read did not complete")
