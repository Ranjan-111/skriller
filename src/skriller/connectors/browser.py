"""Copied dynamic engine boundary; production requires an isolated executor.

No host-browser/CDP fallback is provided. The injection point is trusted worker
configuration, never request data. The container image/network gate is SKR-027.
"""

import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit

import sqlalchemy as sa
from scrapling.fetchers.chrome import DynamicFetcher
from scrapling.fetchers.stealth_chrome import StealthyFetcher

from skriller.connectors.classification import PageClassification, classify_page
from skriller.connectors.fetch import FetchUnavailable, _failure, _public_url
from skriller.connectors.switches import is_disabled
from skriller.contracts import ExecutionContext, Failure, Source
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.jobs.budget import BudgetExhausted, locked_job, reconcile, reserve
from skriller.jobs.capacity import CapacityUnavailable, acquire, release
from skriller.jobs.control import permit_call


@dataclass(frozen=True)
class BrowserRequest:
    url: str
    readiness_selector: str
    timeout_seconds: float
    max_requests: int
    max_body_bytes: int = 2 * 1024 * 1024
    engine: str = "dynamic"
    solve_challenge: bool = False

    def __post_init__(self):
        if not isinstance(self.url, str) or not isinstance(self.readiness_selector, str):
            raise TypeError("Typed public URL and readiness selector required")
        _public_url(self.url)
        if self.engine not in {"dynamic", "stealth"} or not isinstance(self.solve_challenge, bool):
            raise ValueError("Supported typed browser engine required")
        if self.solve_challenge and self.engine != "stealth":
            raise ValueError("Challenge solving requires the copied stealth engine")
        if not self.readiness_selector or len(self.readiness_selector) > 500:
            raise ValueError("Bounded readiness selector required")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (float, int))
            or not math.isfinite(self.timeout_seconds)
            or isinstance(self.max_requests, bool)
            or not isinstance(self.max_requests, int)
            or isinstance(self.max_body_bytes, bool)
            or not isinstance(self.max_body_bytes, int)
            or not 0 < self.timeout_seconds <= 45
            or not 1 <= self.max_requests <= 64
            or not 1 <= self.max_body_bytes <= 2 * 1024 * 1024
        ):
            raise ValueError("Browser limits exceed pilot bounds")


@dataclass(frozen=True)
class BrowserResult:
    content: bytes
    final_url: str
    status: int
    request_count: int
    elapsed_seconds: float
    classification: PageClassification | None = None

    def __post_init__(self):
        if not isinstance(self.content, bytes) or len(self.content) > 2 * 1024 * 1024:
            raise ValueError("Browser output bytes exceed bounds")
        if (
            not isinstance(self.request_count, int)
            or isinstance(self.request_count, bool)
            or not 0 <= self.request_count <= 10000
        ):
            raise ValueError("Browser request count must be bounded and integral")
        if (
            not isinstance(self.status, int)
            or not 100 <= self.status <= 599
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("Invalid browser status or timing")


class IsolatedBrowserExecutor(Protocol):
    """Must enforce hard child/container timeout and confirm descendant cleanup."""

    def execute(
        self, request: BrowserRequest, *, cancel_check: Callable[[], bool] | None = None
    ) -> BrowserResult: ...


def copied_engine_options(request: BrowserRequest, page_setup: Callable) -> dict:
    return {
        "headless": True,
        "real_chrome": False,
        "cdp_url": None,
        "cookies": [],
        "user_data_dir": "/tmp/skriller-browser-profile",
        "max_pages": 1,
        "proxy": "http://172.29.0.2:8080",
        "dns_over_https": False,
        "extra_flags": [
            "--disable-quic",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 172.29.0.2",
            "--proxy-bypass-list=<-loopback>",
        ],
        "additional_args": {"service_workers": "block", "accept_downloads": False},
        "timeout": max(1, math.floor(request.timeout_seconds * 1000)),
        "wait_selector": request.readiness_selector,
        "wait_selector_state": "attached",
        "page_setup": page_setup,
        "network_idle": False,
        # Copied browser config's retries count includes the initial attempt.
        "retries": 1,
        "solve_cloudflare": request.solve_challenge,
        "google_search": False,
        "load_dom": True,
        "selector_config": {"adaptive": False},
    }


def run_copied_browser_in_container(request: BrowserRequest) -> BrowserResult:
    """Child entry point: never launch on the developer host or an existing profile.

    Worker isolation is an execution gate, not established by this environment
    check. The trusted executor must additionally attest reviewed image/firewall,
    tmpfs profile, resource limits and process-group/container cleanup.
    """
    if os.environ.get("SKRILLER_BROWSER_WORKER") != "isolated" or not Path("/.dockerenv").is_file():
        raise RuntimeError("Dynamic engine requires the isolated browser worker")
    count = 0

    def setup(page):
        def route(interception):
            nonlocal count
            count += 1
            if count > request.max_requests:
                interception.abort()
                return
            try:
                _public_url(interception.request.url)
            except ValueError:
                interception.abort()
                return
            # Socket DNS/IP enforcement remains the mandatory guarded proxy and
            # worker firewall. Local/data/file URLs and downloads never navigate.
            if interception.request.resource_type in {"image", "media", "font"}:
                interception.abort()
            else:
                interception.continue_()

        page.route("**/*", route)
        page.on("download", lambda download: download.cancel())

    started = monotonic()
    with TemporaryDirectory(prefix="skriller-browser-", dir="/tmp") as profile:
        options = copied_engine_options(request, setup)
        options["user_data_dir"] = profile
        engine = StealthyFetcher if request.engine == "stealth" else DynamicFetcher
        response = engine.fetch(request.url, **options)
    if not response.css(request.readiness_selector):
        raise _failure("source_unavailable", "Rendered page did not meet readiness")
    raw = response.body
    if len(raw) > request.max_body_bytes:
        raise _failure("budget_exhausted", "Rendered page exceeds output budget")
    return BrowserResult(raw, response.url, response.status, count, monotonic() - started)


class DynamicBrowserAdapter:
    def __init__(
        self,
        database,
        *,
        executor: IsolatedBrowserExecutor | None = None,
        isolation_verified: bool = False,
        stealth: bool = False,
    ):
        self.database, self.executor = database, executor
        self.isolation_verified = isolation_verified
        if not isinstance(stealth, bool):
            raise TypeError("Trusted stealth flag must be boolean")
        self.stealth = stealth

    def fetch(
        self,
        context: ExecutionContext,
        url: str,
        *,
        source: Source,
        readiness_selector: str,
        operation_key: str,
        max_requests: int = 32,
    ) -> BrowserResult:
        if not self.isolation_verified or self.executor is None:
            raise _failure("unsupported_operation", "Isolated browser execution is not configured")
        if context.connection_ref is not None or context.reservation_id is not None:
            raise ValueError("Dynamic public read requires its own bounded attempt reservation")
        from skriller.connectors.proxies import require_unconfigured_provider
        from skriller.security.urls import EgressDenied

        try:
            require_unconfigured_provider(self.database, context, source=source)
        except EgressDenied:
            raise _failure(
                "unsupported_operation",
                "Configured provider routes require isolated browser gateway integration",
            ) from None
        url = _public_url(url)
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", operation_key):
            raise ValueError("Bounded browser operation identity required")
        prefix = f"fetch:{sha256(url.encode()).hexdigest()}:"
        key = prefix + operation_key + ":browser"
        with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
            if is_disabled(session, source, "read"):
                raise _failure("unsupported_operation", "Source reads are disabled")
            remaining = permit_call(session, str(context.job_id))
        remaining = min(remaining, (context.deadline - datetime.now(UTC)).total_seconds(), 45)
        if remaining <= 0 or context.attempt_budget < 1:
            raise _failure("deadline_exceeded", "Browser dispatch window is closed")
        request = BrowserRequest(
            url,
            readiness_selector,
            remaining,
            min(max_requests, context.attempt_budget),
            engine="stealth" if self.stealth else "dynamic",
            solve_challenge=self.stealth,
        )
        with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
            job = locked_job(session, str(context.job_id))
            plan = ConversationRepository.get_plan(session, job["plan_id"])
            if (
                plan["revision"] != context.plan_revision
                or source not in plan["interpretation"]["sources"]
            ):
                raise ValueError("Browser plan revision/source differs from execution")
            used = session.execute(
                sa.select(sa.func.count())
                .select_from(reservations)
                .where(
                    reservations.c.workspace_id == str(context.workspace_id),
                    reservations.c.job_id == job["id"],
                    reservations.c.idempotency_key.startswith(prefix),
                )
            ).scalar_one()
            replay = session.execute(
                sa.select(reservations.c.id).where(
                    reservations.c.workspace_id == str(context.workspace_id),
                    reservations.c.job_id == job["id"],
                    reservations.c.idempotency_key == key,
                )
            ).first()
            if used >= 3 or replay:
                raise _failure("budget_exhausted", "Shared URL attempts already consumed")
            try:
                lease = acquire(
                    session,
                    job["id"],
                    kind="browser",
                    source=source,
                    host=urlsplit(url).hostname or "",
                    ttl_seconds=math.ceil(remaining),
                )
                reservation = reserve(
                    session, job["id"], key, 0, {"fetch_attempts": request.max_requests}
                )
            except CapacityUnavailable:
                raise _failure(
                    "rate_limited", "Shared browser/source capacity is occupied"
                ) from None
            except BudgetExhausted:
                release(session, lease)
                raise _failure("budget_exhausted", "Browser request budget exhausted") from None
        result = None
        started = monotonic()
        stop_reason = None

        def cancelled():
            nonlocal stop_reason
            with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                allowed = permit_call(session, str(context.job_id))
                if is_disabled(session, source, "read"):
                    stop_reason = "unsupported_operation"
                elif allowed <= 0 or datetime.now(UTC) >= context.deadline:
                    from skriller.db import JobRepository

                    state = JobRepository.get(session, str(context.job_id))["state"]
                    stop_reason = "cancelled" if state == "cancelled" else "deadline_exceeded"
            return stop_reason is not None

        try:
            timeout = min(request.timeout_seconds, lease.deadline_monotonic - monotonic())
            if timeout <= 0:
                raise TimeoutError("Browser execution window expired")
            bounded = BrowserRequest(
                url,
                readiness_selector,
                timeout,
                request.max_requests,
                engine=request.engine,
                solve_challenge=request.solve_challenge,
            )
            candidate = self.executor.execute(bounded, cancel_check=cancelled)
            if (
                not 0 <= candidate.request_count <= request.max_requests
                or len(candidate.content) > request.max_body_bytes
            ):
                raise _failure("budget_exhausted", "Browser worker exceeded response limits")
            _public_url(candidate.final_url)
            result = candidate
        except FetchUnavailable:
            if stop_reason:
                raise _failure(stop_reason, "Browser execution was stopped") from None
            raise
        except Exception:  # noqa: BLE001 - redact raw page/process errors
            raise _failure(
                "source_unavailable", "Isolated browser execution did not complete"
            ) from None
        finally:
            try:
                with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    locked_job(session, str(context.job_id))
                    reconcile(
                        session,
                        str(context.job_id),
                        reservation["id"],
                        status="confirmed" if result is not None else "estimated",
                        cost=0,
                        actual_dimensions={"fetch_attempts": max(1, result.request_count)}
                        if result is not None
                        else None,
                    )
            finally:
                with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    release(
                        session,
                        lease,
                        latency=monotonic() - started,
                        ok=result is not None and result.status < 400,
                    )
        classification = classify_page(
            result.content, source=source, final_url=result.final_url, status=result.status
        )
        if not classification.accepts_content:
            raise FetchUnavailable(
                Failure(
                    code="source_unavailable",
                    message="Rendered content is not accepted for extraction",
                ),
                classification,
            )
        with self.database.tenant(context.actor_id, str(context.workspace_id)) as session:
            permitted = permit_call(session, str(context.job_id))
        if permitted <= 0 or datetime.now(UTC) >= context.deadline:
            raise _failure(
                "deadline_exceeded", "Browser result arrived after execution was stopped"
            )
        return BrowserResult(
            result.content,
            result.final_url,
            result.status,
            result.request_count,
            result.elapsed_seconds,
            classification,
        )
