"""Product diagnostics without host account discovery or secret probe output.

The independent per-channel loop/exception boundary is adapted from the supplied
Agent-Reach doctor.check_all (third_party/agent-reach/agent_reach/doctor.py).
Upstream check/config discovery is replaced with trusted operation metadata;
exception messages are discarded entirely, rather than merely URL-scrubbed.
"""

from typing import Literal, get_args
from uuid import UUID

import sqlalchemy as sa
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


def default_registry(
    workspace_id: UUID,
    *,
    youtube_image: str | None = None,
    x_image: str | None = None,
    reddit_image: str | None = None,
    linkedin_image: str | None = None,
    social_image: str | None = None,
    database=None,
    connection_store=None,
) -> ConnectorRegistry:
    # The running search service provides public indexed discovery, not logged-in
    # platform access. No synthetic adapter registration or live proof is added.
    from skriller.connectors.github import public_github_binding
    from skriller.connectors.rss import public_rss_binding
    from skriller.connectors.youtube_executor import ConcreteYouTubeExecutor, public_youtube_binding

    registry = ConnectorRegistry(workspace_id)
    if linkedin_image and database is not None and connection_store is not None:
        from skriller.connectors.linkedin_executor import (
            ConcreteLinkedInExecutor,
            linkedin_read_binding,
            public_linkedin_binding,
        )

        registry.register_adapter(
            public_linkedin_binding(
                ConcreteLinkedInExecutor(linkedin_image), database=database, store=connection_store
            )
        )
        registry.register_adapter(
            linkedin_read_binding(
                ConcreteLinkedInExecutor(linkedin_image), database=database, store=connection_store
            )
        )
    if social_image and database is not None and connection_store is not None:
        from skriller.connectors.social_executor import (
            ConcreteSocialExecutor,
            social_binding,
        )

        for source in ("instagram", "facebook"):
            for operation in ("discover", "read"):
                registry.register_adapter(
                    social_binding(
                        source,
                        ConcreteSocialExecutor(source, social_image),
                        database=database,
                        store=connection_store,
                        operation=operation,
                    )
                )
    registry.register_adapter(public_github_binding())
    registry.register_adapter(public_rss_binding())
    registry.register_adapter(
        public_youtube_binding(ConcreteYouTubeExecutor(youtube_image) if youtube_image else None)
    )
    if x_image and database is not None and connection_store is not None:
        from skriller.connectors.x_executor import ConcreteXExecutor, public_x_binding

        registry.register_adapter(
            public_x_binding(ConcreteXExecutor(x_image), database=database, store=connection_store)
        )
    if reddit_image and database is not None and connection_store is not None:
        from skriller.connectors.reddit_executor import (
            ConcreteRedditExecutor,
            public_reddit_binding,
            reddit_read_binding,
        )

        registry.register_adapter(
            public_reddit_binding(
                ConcreteRedditExecutor(reddit_image), database=database, store=connection_store
            )
        )
        registry.register_adapter(
            reddit_read_binding(
                ConcreteRedditExecutor(reddit_image), database=database, store=connection_store
            )
        )
    return registry


def diagnose(
    session,
    registry: ConnectorRegistry | None = None,
    *,
    search_enabled: bool = True,
    youtube_image: str | None = None,
    x_image: str | None = None,
    reddit_image: str | None = None,
    linkedin_image: str | None = None,
    social_image: str | None = None,
    database=None,
    connection_store=None,
) -> list[SourceDiagnostic]:
    from skriller.db.repositories import scope

    registry = registry or default_registry(
        UUID(scope(session)),
        youtube_image=youtube_image,
        x_image=x_image,
        reddit_image=reddit_image,
        linkedin_image=linkedin_image,
        social_image=social_image,
        database=database,
        connection_store=connection_store,
    )
    if str(registry.workspace_id) != scope(session):
        raise ValueError("Diagnostic registry belongs to another workspace")
    connected: set[Source] = set()
    social_discover: set[Source] = set()
    configured: tuple[tuple[Source, str | None], ...] = (
        ("x", x_image),
        ("reddit", reddit_image),
        ("linkedin", linkedin_image),
        ("instagram", social_image),
        ("facebook", social_image),
    )
    for source, image in configured:
        if image and database is not None and connection_store is not None:
            from skriller.connections.tables import connections

            rows = (
                session.execute(
                    sa.select(connections.c.scopes).where(
                        connections.c.workspace_id == scope(session),
                        connections.c.source == source,
                        connections.c.auth_kind
                        == (
                            "session"
                            if source in {"linkedin", "instagram", "facebook"}
                            else "oauth"
                        ),
                        connections.c.state == "active",
                        connections.c.expires_at > sa.func.clock_timestamp(),
                        *(
                            [connections.c.created_by == session.info["actor_id"]]
                            if source in {"linkedin", "instagram", "facebook"}
                            else []
                        ),
                    )
                )
                .scalars()
                .all()
            )
            if any({"read", "discover"} <= set(value) for value in rows):
                connected.add(source)
                if source in {"instagram", "facebook"}:
                    social_discover.add(source)
            elif source in {"instagram", "facebook"} and any("read" in value for value in rows):
                connected.add(source)
    registry.connected_sources = registry.connected_sources | frozenset(connected)
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
                if (
                    social_image
                    and source in {"instagram", "facebook"}
                    and operation == "discover"
                    and source not in social_discover
                ):
                    capability.operational_status = "needs_connection"
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
