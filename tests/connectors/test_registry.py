from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_reach.channels import get_all_channels

from skriller.connectors import (
    AdapterBinding,
    ConnectorRegistry,
    OperationVerification,
    RouteSelection,
)
from skriller.contracts import Capability, Failure


def binding(source="web", operation="read", auth_kind="none", status="available"):
    return AdapterBinding(
        Capability(
            source=source,
            operation=operation,
            engineering_status="tested",
            operational_status=status,
            access_route="fixture-only reviewed adapter",
            auth_kind=auth_kind,
            version="fixture-1",
        ),
        "fixture",
        lambda context, target: target,
    )


def verify(registry, adapter, **overrides):
    now = datetime.now(UTC)
    fields = {
        "workspace_id": registry.workspace_id,
        "source": adapter.capability.source,
        "operation": adapter.capability.operation,
        "backend": adapter.backend,
        "checked_at": now - timedelta(seconds=1),
        "expires_at": now + timedelta(minutes=1),
        "passed": True,
    }
    fields.update(overrides)
    registry.record_verification(OperationVerification(**fields))


def test_channels_are_fresh_copied_classes_with_upstream_order():
    registry = ConnectorRegistry(uuid4())
    upstream = {ch.name: ch for ch in get_all_channels()}
    for source in ("linkedin", "reddit", "rss", "github", "youtube", "web"):
        channel = registry.channel(source)
        assert type(channel) is type(upstream[source])
        assert channel is not upstream[source]
        assert channel.backends == upstream[source].backends
        assert channel.backends is not upstream[source].backends
        assert channel.active_backend is None
    assert [c.source for c in registry.capabilities()][-1] == "web"


def test_tenant_backend_preferences_and_active_state_do_not_leak():
    first = ConnectorRegistry(uuid4(), backend_preferences={"reddit": "rdt-cli"})
    second = ConnectorRegistry(uuid4(), backend_preferences={"reddit": "OpenCLI"})
    assert first.ordered_backends("reddit") == ["rdt-cli", "OpenCLI"]
    assert second.ordered_backends("reddit") == ["OpenCLI", "rdt-cli"]
    first.channel("reddit").active_backend = "rdt-cli"
    first.channel("reddit").backends.clear()
    assert second.channel("reddit").active_backend is None
    assert second.ordered_backends("reddit") == ["OpenCLI", "rdt-cli"]
    assert next(ch for ch in get_all_channels() if ch.name == "reddit").backends


def test_diagnostics_do_not_claim_real_read_or_discover():
    registry = ConnectorRegistry(uuid4(), connected_sources=frozenset({"linkedin", "reddit"}))
    for source in ("linkedin", "reddit", "rss", "github", "youtube", "web"):
        for operation in ("read", "discover", "analytics"):
            capability = registry.capability(source, operation)
            assert capability.engineering_status == "planned"
            assert capability.operational_status != "available"
            failure = registry.select(operation, source=source)
            assert isinstance(failure, Failure)
            assert failure.code == "unsupported_operation"


def test_known_platform_does_not_fallback_to_available_web_reader():
    registry = ConnectorRegistry(uuid4())
    adapter = binding()
    registry.register_adapter(adapter)
    verify(registry, adapter)
    selected = registry.select("read", url="https://example.com")
    assert isinstance(selected, RouteSelection) and selected.source == "web"
    failure = registry.select("read", url="https://linkedin.com/in/someone")
    assert isinstance(failure, Failure) and failure.code == "unsupported_operation"
    failure = registry.select("read", url="https://reddit.com/r/python")
    assert isinstance(failure, Failure) and failure.code == "unsupported_operation"


def test_configuration_and_adapter_claim_do_not_imply_readiness():
    registry = ConnectorRegistry(uuid4(), connected_sources=frozenset({"reddit"}))
    adapter = binding("reddit", auth_kind="session")
    registry.register_adapter(adapter)
    assert registry.capability("reddit", "read").operational_status == "experimental"
    assert registry.select("read", source="reddit").code == "source_unavailable"
    verify(registry, adapter)
    assert isinstance(registry.select("read", source="reddit"), RouteSelection)
    assert registry.select("discover", source="reddit").code == "unsupported_operation"


def test_connection_missing_even_when_operation_verification_exists():
    registry = ConnectorRegistry(uuid4())
    adapter = binding("reddit", auth_kind="session")
    registry.register_adapter(adapter)
    verify(registry, adapter)
    assert registry.select("read", source="reddit").code == "auth_required"


@pytest.mark.parametrize("kind", ["expired", "future", "failed", "naive"])
def test_unusable_verification_never_sets_available(kind):
    registry = ConnectorRegistry(uuid4())
    adapter = binding()
    registry.register_adapter(adapter)
    now = datetime.now(UTC)
    changes = {
        "expired": {"expires_at": now - timedelta(seconds=1)},
        "future": {"checked_at": now + timedelta(seconds=10)},
        "failed": {"passed": False},
        "naive": {"checked_at": datetime.now()},
    }
    verify(registry, adapter, **changes[kind])
    assert registry.capability("web", "read").operational_status == "experimental"


def test_other_tenant_or_backend_verification_is_rejected():
    registry = ConnectorRegistry(uuid4())
    adapter = binding()
    registry.register_adapter(adapter)
    with pytest.raises(ValueError, match="context"):
        verify(registry, adapter, workspace_id=uuid4())
    with pytest.raises(ValueError, match="backend"):
        verify(registry, adapter, backend="different")


def test_adapter_caller_mutation_duplicate_and_planned_rejected():
    registry = ConnectorRegistry(uuid4())
    adapter = binding()
    registry.register_adapter(adapter)
    adapter.capability.access_route = "changed outside registry"
    assert registry.capability("web", "read").access_route != "changed outside registry"
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register_adapter(adapter)
    planned = binding("github")
    planned.capability.engineering_status = "planned"
    with pytest.raises(ValueError, match="planned"):
        registry.register_adapter(planned)


@pytest.mark.parametrize(
    "status,code",
    [
        ("rate_limited", "rate_limited"),
        ("needs_access_agreement", "access_denied"),
        ("unavailable", "source_unavailable"),
    ],
)
def test_operator_source_state_overrides_successful_verification(status, code):
    registry = ConnectorRegistry(uuid4())
    adapter = binding(status=status)
    registry.register_adapter(adapter)
    verify(registry, adapter)
    assert registry.select("read", source="web").code == code


def test_explicit_source_url_mismatch_and_lookalike_hosts():
    registry = ConnectorRegistry(uuid4())
    adapter = binding("linkedin")
    registry.register_adapter(adapter)
    verify(registry, adapter)
    failure = registry.select(
        "read", source="linkedin", url="https://linkedin.com.evil.test/in/user"
    )
    assert failure.code == "unsupported_operation"
    assert registry.select("read").code == "unsupported_operation"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://127.0.0.1", "http://user:secret@example.com"]
)
def test_unsafe_url_never_reaches_generic_fallback(url):
    registry = ConnectorRegistry(uuid4())
    adapter = binding()
    registry.register_adapter(adapter)
    verify(registry, adapter)
    failure = registry.select("read", url=url)
    assert isinstance(failure, Failure)
    assert failure.code == "access_denied"
