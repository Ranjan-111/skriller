"""OAuth-backed X recent search through the existing isolated runner."""

import json
from datetime import UTC, datetime
from pathlib import Path

from skriller.connections.execution import run_connected
from skriller.connections.store import ConnectionStore
from skriller.connectors.search import SearchHit, SearchPage
from skriller.connectors.x_discovery import XRestPage, XSearch, parse_rest_search
from skriller.contracts import ExecutionContext
from skriller.security.runner import IsolatedRunner


class XUnavailable(ValueError):
    def __init__(self, code="source_unavailable", retry_after_seconds=None):
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Connected X read did not complete")


class ConcreteXExecutor:
    def __init__(self, image: str, *, docker: Path = Path("/usr/local/bin/docker")):
        self.runner = IsolatedRunner(image, docker=docker)

    def execute(
        self,
        request: XSearch,
        *,
        database,
        store: ConnectionStore,
        context: ExecutionContext,
        timeout: float = 30,
    ) -> XRestPage:
        if not isinstance(request, XSearch) or not 0 < timeout <= 45:
            raise ValueError("X request or timeout is outside the supported bound")
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            "x_read",
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_100_000,
        )
        if result.status != "completed":
            raise XUnavailable()
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict) and payload.get("_skriller_error"):
                code = payload.get("_skriller_error")
                retry_after = payload.get("retry_after_seconds")
                if code not in {
                    "auth_expired",
                    "access_denied",
                    "not_found",
                    "rate_limited",
                    "source_unavailable",
                } or (
                    retry_after is not None
                    and (type(retry_after) is not int or not 0 <= retry_after <= 86400)
                ):
                    raise XUnavailable()
                raise XUnavailable(code, retry_after)
            return parse_rest_search(payload, request, observed_at=datetime.now(UTC))
        except XUnavailable:
            raise
        except (ValueError, TypeError):
            raise XUnavailable("X result did not match its bounded source contract") from None

    def search_page(
        self,
        query: str,
        *,
        limit: int,
        database,
        store: ConnectionStore,
        context: ExecutionContext,
    ) -> SearchPage:
        request = XSearch(query=query, limit=limit, mode="Latest")
        page = self.execute(request, database=database, store=store, context=context)
        return SearchPage(
            hits=[
                SearchHit(
                    title="@" + post.author_handle,
                    url=post.source_url,
                    snippet=post.excerpt,
                    provider="x_api_v2",
                    evidence_kind="public_post",
                    rank=index,
                )
                for index, post in enumerate(page.posts, 1)
            ],
            rejected=page.rejected_count,
            truncated=page.omitted_count > 0 or page.has_more,
            query=query,
            observed_at=page.observed_at,
        )


def public_x_binding(reader: ConcreteXExecutor | None = None, *, database=None, store=None):
    """Register an OAuth read capability; live availability requires verification."""
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, serialized_request):
        if reader is None or database is None or store is None or context.connection_ref is None:
            raise XUnavailable("Connect an X OAuth account before searching")
        try:
            request = XSearch.model_validate_json(serialized_request)
        except ValueError:
            raise XUnavailable("X search request is invalid") from None
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise XUnavailable("X execution window ended")
        return reader.execute(
            request, database=database, store=store, context=context, timeout=min(30, remaining)
        )

    return AdapterBinding(
        Capability(
            source="x",
            operation="discover",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="oauth",
            access_route="Official X API v2 recent post search using connected OAuth read access",
            version="x_api_v2_recent_search",
            allowed_fields=["public_post_text", "author_handle", "published_at", "source_url"],
        ),
        "x_api_v2_recent_search",
        execute,
    )
