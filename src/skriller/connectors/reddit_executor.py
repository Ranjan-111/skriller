"""OAuth-backed Reddit search through the existing isolated runner."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from skriller.connections import reddit_continuation
from skriller.connections.execution import run_connected
from skriller.connections.store import ConnectionStore, ConnectionUnavailable
from skriller.connectors.reddit_discovery import (
    RedditDiscoveryPage,
    RedditSearch,
    parse_search_listing,
)
from skriller.connectors.reddit_read import RedditThread, parse_thread
from skriller.connectors.reddit_request import RedditRead
from skriller.connectors.search import SearchHit, SearchPage
from skriller.contracts import ExecutionContext
from skriller.security.runner import IsolatedRunner


class RedditUnavailable(ValueError):
    def __init__(self, code="source_unavailable", retry_after_seconds=None):
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Connected Reddit read did not complete")


class ConcreteRedditExecutor:
    def __init__(
        self,
        image: str,
        *,
        docker: Path = Path("/usr/local/bin/docker"),
        user_agent: str | None = None,
    ):
        self.runner = IsolatedRunner(image, docker=docker)
        self.user_agent = (
            RedditSearch(query="configuration", user_agent=user_agent)
            if user_agent is not None
            else RedditSearch(query="configuration")
        ).user_agent

    def read(
        self,
        request: RedditRead,
        *,
        database,
        store,
        context,
        timeout: float = 30,
        expected_credential_ref: UUID | None = None,
    ) -> RedditThread:
        if not isinstance(request, RedditRead) or not 0 < timeout <= 30:
            raise ValueError("A bounded Reddit thread request is required")
        request = request.model_copy(update={"user_agent": self.user_agent})
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            "reddit_oauth_read",
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_100_000,
            expected_credential_ref=expected_credential_ref,
        )
        if result.status != "completed":
            raise RedditUnavailable()
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict) and payload.get("_skriller_error"):
                code = payload.get("_skriller_error")
                retry = payload.get("retry_after_seconds")
                if code not in {
                    "auth_expired",
                    "access_denied",
                    "not_found",
                    "rate_limited",
                    "source_unavailable",
                } or (retry is not None and (type(retry) is not int or not 0 <= retry <= 86400)):
                    raise RedditUnavailable()
                raise RedditUnavailable(code, retry)
            return parse_thread(payload, request, observed_at=datetime.now(UTC))
        except RedditUnavailable:
            raise
        except (TypeError, ValueError):
            raise RedditUnavailable() from None

    def execute(
        self,
        request: RedditSearch,
        *,
        database,
        store: ConnectionStore,
        context: ExecutionContext,
        timeout: float = 30,
        continuation_ref: UUID | None = None,
    ) -> RedditDiscoveryPage:
        if not isinstance(request, RedditSearch) or not 0 < timeout <= 45:
            raise ValueError("Reddit request or timeout is outside the supported bound")
        if request.cursor is not None:
            raise RedditUnavailable("unbound_cursor")
        request = request.model_copy(update={"user_agent": self.user_agent})
        original_request = request
        try:
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                material = store.load_for_runner(session, context, "reddit_oauth_search")
                if continuation_ref is not None:
                    cursor = reddit_continuation.consume(
                        session, store, context, material, request, UUID(str(continuation_ref))
                    )
                    request = request.model_copy(update={"cursor": cursor})
        except (ConnectionUnavailable, ValueError):
            raise RedditUnavailable("needs_connection") from None
        except Exception:  # noqa: BLE001 - sanitize private control-plane errors
            raise RedditUnavailable("control_unavailable") from None
        result = run_connected(
            database,
            store,
            context,
            self.runner,
            "reddit_oauth_search",
            request.model_dump_json(),
            timeout=timeout,
            max_output=1_100_000,
            expected_credential_ref=material.credential_ref,
        )
        if result.status != "completed":
            raise RedditUnavailable()
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
                    raise RedditUnavailable()
                raise RedditUnavailable(code, retry_after)
            page = parse_search_listing(payload, request, observed_at=datetime.now(UTC))
            reference = None
            if page.next_cursor is not None:
                with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                    reference = reddit_continuation.issue(
                        session, store, context, material, original_request, page.next_cursor
                    )
            return page.model_copy(
                update={
                    "continuation_ref": reference,
                    "has_more": page.next_cursor is not None,
                    "next_cursor": None,
                    "read_connection_ref": context.connection_ref,
                    "read_credential_ref": material.credential_ref,
                }
            )
        except RedditUnavailable:
            raise
        except (ValueError, TypeError, ConnectionUnavailable):
            raise RedditUnavailable() from None

    def search_page(
        self,
        query: str,
        *,
        limit: int,
        database,
        store: ConnectionStore,
        context: ExecutionContext,
        continuation_ref: UUID | None = None,
    ) -> SearchPage:
        request = RedditSearch(query=query, limit=limit, sort="new")
        page = self.execute(
            request,
            database=database,
            store=store,
            context=context,
            continuation_ref=continuation_ref,
        )
        return SearchPage(
            hits=[
                SearchHit(
                    title=post.title,
                    url=post.source_url,
                    snippet=post.excerpt,
                    provider="reddit_oauth",
                    evidence_kind="public_post",
                    rank=index,
                )
                for index, post in enumerate(page.posts, 1)
            ],
            rejected=page.rejected_count,
            truncated=page.omitted_count > 0 or page.has_more,
            pagination_supported=True,
            continuation_ref=page.continuation_ref,
            read_connection_ref=page.read_connection_ref,
            read_credential_ref=page.read_credential_ref,
            query=query,
            observed_at=page.observed_at,
        )


def public_reddit_binding(
    reader: ConcreteRedditExecutor | None = None, *, database=None, store=None
):
    """Register an OAuth read capability; live availability requires verification."""
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, serialized_request):
        if reader is None or database is None or store is None or context.connection_ref is None:
            raise RedditUnavailable("needs_connection")
        try:
            request = RedditSearch.model_validate_json(serialized_request)
        except ValueError:
            raise RedditUnavailable("invalid_request") from None
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise RedditUnavailable("deadline_exceeded")
        return reader.execute(
            request, database=database, store=store, context=context, timeout=min(30, remaining)
        )

    return AdapterBinding(
        Capability(
            source="reddit",
            operation="discover",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="oauth",
            access_route="Reddit OAuth post search using connected OAuth read access",
            version="reddit_oauth_search",
            allowed_fields=["title", "public_post_text", "published_at", "source_url"],
        ),
        "reddit_oauth_search",
        execute,
    )


def reddit_read_binding(reader=None, *, database=None, store=None):
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, serialized_request):
        if reader is None or database is None or store is None or context.connection_ref is None:
            raise RedditUnavailable("needs_connection")
        request = RedditRead.model_validate_json(serialized_request)
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise RedditUnavailable("deadline_exceeded")
        return reader.read(
            request, database=database, store=store, context=context, timeout=min(30, remaining)
        )

    return AdapterBinding(
        Capability(
            source="reddit",
            operation="read",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="oauth",
            access_route="Owner-connected OAuth post and bounded nested-comment read",
            version="reddit_oauth_read_v1",
            allowed_fields=["public_post_text", "comment_text", "published_at", "source_url"],
        ),
        "reddit_oauth_read_v1",
        execute,
    )
