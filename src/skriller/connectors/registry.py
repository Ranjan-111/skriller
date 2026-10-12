"""Reuse upstream Channel routing without global mutable backend state.

Agent-Reach's ordered registry and Channel implementations are copied, attributed
in third_party/agent-reach/PROVENANCE.json, and used directly. Their host-wide
check/read methods are deliberately not invoked here: a product operation needs
its own reviewed adapter, isolated execution, and explicit operation verification.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, get_args
from uuid import UUID

from agent_reach.channels import get_all_channels
from agent_reach.channels.base import Channel
from agent_reach.utils.url import normalize_public_http_url

from skriller.contracts import Capability, ExecutionContext, Failure, Source

Operation = Literal["discover", "read", "analytics"]
_SOURCE_NAMES: dict[str, Source] = {source: source for source in get_args(Source)}
_SOURCE_NAMES["twitter"] = "x"
_SESSION_SOURCES = {"linkedin", "reddit", "x", "instagram", "facebook"}


@dataclass(frozen=True)
class AdapterBinding:
    """Trusted application registration; callers cannot supply executable code."""

    capability: Capability
    backend: str
    execute: Callable[[ExecutionContext, str], object]


@dataclass(frozen=True)
class OperationVerification:
    """Trusted worker's successful live operation, scoped to one context/backend."""

    workspace_id: UUID
    source: Source
    operation: Operation
    backend: str
    checked_at: datetime
    expires_at: datetime
    passed: bool

    def current(self, now: datetime) -> bool:
        if self.checked_at.tzinfo is None or self.expires_at.tzinfo is None:
            return False
        return self.passed and self.checked_at <= now < self.expires_at


@dataclass(frozen=True)
class RouteSelection:
    source: Source
    operation: Operation
    backend: str
    capability: Capability
    adapter: AdapterBinding


class ConnectorRegistry:
    def __init__(
        self,
        workspace_id: UUID,
        *,
        backend_preferences: Mapping[Source, str] | None = None,
        connected_sources: frozenset[Source] = frozenset(),
    ):
        self.workspace_id = workspace_id
        self.connected_sources = connected_sources
        self._preferences = dict(backend_preferences or {})
        self._channels: dict[Source, Channel] = {}
        # Reuse upstream ordering and classes, never upstream singleton objects.
        for upstream in get_all_channels():
            source = _SOURCE_NAMES.get(upstream.name)
            if source is None:
                continue
            channel = type(upstream)()
            channel.backends = list(upstream.backends)
            channel.active_backend = None
            self._channels[source] = channel
        self._adapters: dict[tuple[Source, Operation], AdapterBinding] = {}
        self._verified: dict[tuple[Source, Operation], OperationVerification] = {}

    def channel(self, source: Source) -> Channel:
        """Context-local diagnostic channel; never a host-global singleton."""
        return self._channels[source]

    def ordered_backends(self, source: Source) -> list[str]:
        channel = self.channel(source)
        # Reuse Channel.ordered_backends rather than reimplement its precedence.
        return channel.ordered_backends({f"{channel.name}_backend": self._preferences.get(source)})

    def register_adapter(self, binding: AdapterBinding) -> None:
        cap = binding.capability
        if cap.engineering_status == "planned":
            raise ValueError("A planned capability cannot register executable code")
        if not binding.backend or not callable(binding.execute):
            raise ValueError("Adapter needs a named reviewed backend and callable")
        key = (cap.source, cap.operation)
        if key in self._adapters:
            raise ValueError("Duplicate source operation registration")
        # Copy the mutable Pydantic model; later caller edits cannot alter routing.
        self._adapters[key] = AdapterBinding(
            cap.model_copy(deep=True), binding.backend, binding.execute
        )

    def record_verification(self, result: OperationVerification) -> None:
        key = (result.source, result.operation)
        adapter = self._adapters.get(key)
        if result.workspace_id != self.workspace_id or adapter is None:
            raise ValueError("Verification belongs to another context or unregistered operation")
        if result.backend != adapter.backend:
            raise ValueError("Verification backend differs from registered operation")
        self._verified[key] = result

    def capability(
        self, source: Source, operation: Operation, *, now: datetime | None = None
    ) -> Capability:
        now = now or datetime.now(UTC)
        binding = self._adapters.get((source, operation))
        if binding is None:
            return Capability(
                source=source,
                operation=operation,
                engineering_status="planned",
                operational_status="needs_connection"
                if source in _SESSION_SOURCES
                else "unavailable",
                access_route="Dedicated adapter not implemented; upstream channel is diagnostic only",
                auth_kind="session" if source in _SESSION_SOURCES else "none",
                version="unimplemented",
            )
        cap = binding.capability.model_copy(deep=True)
        if cap.auth_kind != "none" and source not in self.connected_sources:
            cap.operational_status = "needs_connection"
        elif cap.operational_status in {"rate_limited", "needs_access_agreement", "unavailable"}:
            pass
        else:
            verification = self._verified.get((source, operation))
            cap.operational_status = (
                "available" if verification and verification.current(now) else "experimental"
            )
        return cap

    def capabilities(self) -> list[Capability]:
        return [
            self.capability(source, operation)
            for source in self._channels
            for operation in ("discover", "read", "analytics")
        ]

    def select(
        self, operation: Operation, *, source: Source | None = None, url: str | None = None
    ) -> RouteSelection | Failure:
        if url is not None:
            try:
                url = normalize_public_http_url(url)
            except ValueError:
                return Failure(
                    code="access_denied", message="Source URL is not a public HTTP(S) target"
                )
        if source is None:
            if not url:
                return Failure(code="unsupported_operation", message="A source or URL is required")
            # Upstream ordering puts generic web last. Known platforms therefore
            # never silently drop into the web adapter when their operation fails.
            source = next(
                (name for name, channel in self._channels.items() if channel.can_handle(url)), None
            )
        if source is None or source not in self._channels:
            return Failure(code="unsupported_operation", message="Source is not registered")
        if url and source != "web" and not self.channel(source).can_handle(url):
            return Failure(
                code="unsupported_operation", message="URL does not belong to selected source"
            )
        binding = self._adapters.get((source, operation))
        if binding is None:
            return Failure(
                code="unsupported_operation", message="No implemented adapter for source operation"
            )
        cap = self.capability(source, operation)
        if cap.operational_status == "needs_connection":
            return Failure(
                code="auth_required", message="Connect this source in the current workspace"
            )
        if cap.operational_status == "rate_limited":
            return Failure(code="rate_limited", message="Source operation is rate limited")
        if cap.operational_status == "needs_access_agreement":
            return Failure(
                code="access_denied", message="Source operation requires approved access"
            )
        if cap.operational_status != "available":
            return Failure(
                code="source_unavailable",
                message="Source operation has no current live verification",
            )
        return RouteSelection(source, operation, binding.backend, cap, binding)
