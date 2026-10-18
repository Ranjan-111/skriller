"""Tenant-owned LinkedIn search through the existing isolated runner."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from skriller.connections.execution import run_connected
from skriller.connections.store import ConnectionUnavailable
from skriller.connectors.linkedin_discovery import LinkedInSearch, parse_search_response
from skriller.connectors.linkedin_read import LinkedInRead, parse_read_response
from skriller.connectors.search import SearchHit, SearchPage
from skriller.security.runner import IsolatedRunner


class LinkedInUnavailable(ValueError):
    code = "source_unavailable"
    retry_after_seconds = None

    def __init__(self, code="source_unavailable"):
        self.code = (
            code
            if code
            in {
                "source_unavailable",
                "auth_required",
                "auth_expired",
                "access_denied",
                "not_found",
                "rate_limited",
            }
            else "source_unavailable"
        )
        super().__init__("Connected LinkedIn operation did not complete")


class ConcreteLinkedInExecutor:
    def __init__(self, image: str, *, docker: Path = Path("/usr/local/bin/docker")):
        self.runner = IsolatedRunner(image, docker=docker)

    def execute(
        self,
        request: LinkedInSearch,
        *,
        database,
        store,
        context,
        timeout=40,
        expected_credential_ref=None,
    ):
        if not isinstance(request, LinkedInSearch) or not 0 < timeout <= 45:
            raise ValueError("A bounded LinkedIn search request is required")
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            "linkedin_search",
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_048_576,
            expected_credential_ref=expected_credential_ref,
        )
        if result.status != "completed":
            raise LinkedInUnavailable()
        try:
            return parse_search_response(
                json.loads(result.stdout), request, observed_at=datetime.now(UTC)
            )
        except (TypeError, ValueError):
            raise LinkedInUnavailable() from None

    def read(
        self,
        request: LinkedInRead,
        *,
        database,
        store,
        context,
        timeout=40,
        expected_credential_ref: UUID | None = None,
    ):
        if not isinstance(request, LinkedInRead) or not 0 < timeout <= 45:
            raise ValueError("A bounded LinkedIn resource request is required")
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            "linkedin_resource_read",
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_048_576,
            expected_credential_ref=expected_credential_ref,
        )
        if result.status != "completed":
            raise LinkedInUnavailable(
                "auth_required" if result.status == "needs_connection" else "source_unavailable"
            )
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict) and "_skriller_error" in payload:
                code = payload["_skriller_error"]
                raise LinkedInUnavailable(
                    code
                    if code
                    in {
                        "auth_expired",
                        "access_denied",
                        "rate_limited",
                        "not_found",
                        "source_unavailable",
                    }
                    else "source_unavailable"
                )
            return parse_read_response(payload, request, observed_at=datetime.now(UTC))
        except LinkedInUnavailable:
            raise
        except (TypeError, ValueError):
            raise LinkedInUnavailable() from None

    def search_page(self, query, *, limit, database, store, context):
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("LinkedIn search result limit is outside its bound")
        try:
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                material = store.load_for_runner(session, context, "linkedin_search")
        except ConnectionUnavailable:
            raise LinkedInUnavailable() from None
        page = self.execute(
            LinkedInSearch(operation="search_people", keywords=query),
            database=database,
            store=store,
            context=context,
            expected_credential_ref=material.credential_ref,
        )
        # Search page text is unaligned: never attach it as somebody's biography/post.
        references = page.references[:limit]
        return SearchPage(
            hits=[
                SearchHit(
                    title=item.label or "LinkedIn search reference",
                    url=item.url,
                    snippet=item.label or "",
                    provider="linkedin_mcp",
                    evidence_kind="search_reference",
                    rank=index,
                )
                for index, item in enumerate(references, 1)
            ],
            rejected=page.rejected_count,
            truncated=len(page.references) > limit
            or page.text_truncated
            or bool(page.failed_sections),
            query=query,
            observed_at=page.observed_at,
            read_connection_ref=material.connection_ref,
            read_credential_ref=material.credential_ref,
        )


def public_linkedin_binding(reader=None, *, database=None, store=None):
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, serialized_request):
        if reader is None or database is None or store is None:
            raise LinkedInUnavailable()
        request = LinkedInSearch.model_validate_json(serialized_request)
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise LinkedInUnavailable()
        return reader.execute(
            request, database=database, store=store, context=context, timeout=min(40, remaining)
        )

    return AdapterBinding(
        Capability(
            source="linkedin",
            operation="discover",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="session",
            access_route="Owner-connected acquired LinkedIn search; unaligned references, no profile read",
            version="linkedin_search_v1",
            allowed_fields=["source_url", "search_reference"],
        ),
        "linkedin_search_v1",
        execute,
    )


def linkedin_read_binding(reader=None, *, database=None, store=None):
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, serialized_request):
        if reader is None or database is None or store is None:
            raise LinkedInUnavailable()
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise LinkedInUnavailable()
        return reader.read(
            LinkedInRead.model_validate_json(serialized_request),
            database=database,
            store=store,
            context=context,
            timeout=min(40, remaining),
        )

    return AdapterBinding(
        Capability(
            source="linkedin",
            operation="read",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="session",
            access_route="Owner-connected isolated single resource section; no contact overlays or inferred identity",
            version="linkedin_resource_v1",
            allowed_fields=["source_url", "section_text"],
        ),
        "linkedin_resource_v1",
        execute,
    )
