"""Product diagnostics without host account discovery or secret probe output.

The independent per-channel loop/exception boundary is adapted from the supplied
Agent-Reach doctor.check_all (third_party/agent-reach/agent_reach/doctor.py).
Upstream check/config discovery is replaced with trusted operation metadata;
exception messages are discarded entirely, rather than merely URL-scrubbed.
"""

from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from skriller.connectors.registry import ConnectorRegistry, Operation
from skriller.connectors.switches import disabled_operations
from skriller.contracts import Capability, Source


class SourceDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: Capability
    disabled: bool
    setup_state: Literal[
        "disabled",
        "unavailable",
        "needs_connection",
        "experimental",
        "ready",
        "diagnostic_error",
        "needs_access_agreement",
        "rate_limited",
    ]
    evidence_scope: Literal["public_indexed_references", "dedicated_adapter"]
    credential_validation: Literal["not_performed"] = "not_performed"


def default_registry(workspace_id: UUID) -> ConnectorRegistry:
    # The running search service provides public indexed discovery, not logged-in
    # platform access. No synthetic adapter registration or live proof is added.
    return ConnectorRegistry(workspace_id)


def diagnose(
    session, registry: ConnectorRegistry | None = None, *, search_enabled: bool = True
) -> list[SourceDiagnostic]:
    from skriller.db.repositories import scope

    registry = registry or default_registry(UUID(scope(session)))
    if str(registry.workspace_id) != scope(session):
        raise ValueError("Diagnostic registry belongs to another workspace")
    disabled = disabled_operations(session)
    results = []
    for source in get_args(Source):
        for operation in get_args(Operation):
            state: Literal[
                "ready",
                "experimental",
                "needs_connection",
                "needs_access_agreement",
                "rate_limited",
                "unavailable",
                "diagnostic_error",
            ]
            try:
                capability = registry.capability(source, operation)
                evidence_scope: Literal["public_indexed_references", "dedicated_adapter"] = (
                    "dedicated_adapter"
                )
                # Exa discovery is a separate product search service, not an
                # Agent-Reach channel implementation. It has no per-workspace
                # current live verification, so available is never implied.
                if operation == "discover" and capability.engineering_status == "planned":
                    capability = Capability(
                        source=source,
                        operation=operation,
                        engineering_status="tested",
                        operational_status="experimental" if search_enabled else "unavailable",
                        auth_kind="none",
                        access_route="Exa keyless public indexed references; not direct platform access",
                        version="exa_keyless_v1",
                        allowed_fields=["title", "url", "snippet"],
                    )
                    evidence_scope = "public_indexed_references"
                state = (
                    "ready"
                    if capability.operational_status == "available"
                    else capability.operational_status
                )
            except Exception:  # noqa: BLE001 - one broken operation must not hide other diagnostics
                capability = Capability(
                    source=source,
                    operation=operation,
                    engineering_status="planned",
                    operational_status="unavailable",
                    access_route="Diagnostic unavailable",
                    auth_kind="none",
                    version="unknown",
                )
                state = "diagnostic_error"
                evidence_scope = "dedicated_adapter"
            blocked = (source, operation) in disabled
            results.append(
                SourceDiagnostic(
                    capability=capability,
                    disabled=blocked,
                    setup_state="disabled" if blocked else state,
                    evidence_scope=evidence_scope,
                )
            )
    return results
