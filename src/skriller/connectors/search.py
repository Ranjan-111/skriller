"""Free Exa MCP search via the official SDK; no paid credentials or fallback."""

import asyncio
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
import sqlalchemy as sa
from agent_reach.utils.url import host_matches, normalize_public_http_url
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field
from scrapling.spiders.throttle import parse_retry_after

from skriller.contracts import ExecutionContext, Failure
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.jobs.budget import locked_job, reconcile, reserve

ENDPOINT = "https://mcp.exa.ai/mcp?tools=web_search_exa"
MAX_RESPONSE_BYTES = 1_048_576


DiscoveryProvider = Literal[
    "exa_keyless",
    "x_api_v2",
    "reddit_oauth",
    "linkedin_mcp",
    "opencli_instagram",
    "opencli_facebook",
]


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(max_length=4096)
    snippet: str = Field(max_length=4096)
    provider: DiscoveryProvider = "exa_keyless"
    evidence_kind: Literal["search_snippet", "public_post", "search_reference"] = "search_snippet"
    rank: int = Field(ge=1)


class SearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hits: list[SearchHit] = Field(max_length=10)
    rejected: int
    truncated: bool
    pagination_supported: bool = False
    continuation_ref: UUID | None = None
    read_connection_ref: UUID | None = None
    read_credential_ref: UUID | None = None
    currency_cost: Literal[0] = 0
    query: str = Field(default="", max_length=2000)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SearchUnavailable(RuntimeError):
    def __init__(self, failure: Failure):
        self.failure = failure
        super().__init__(failure.message)


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError("Provider response limit exceeded")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class LimitedTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        response.stream = LimitedStream(response.stream)
        return response

    async def aclose(self):
        await self.transport.aclose()


def parse_hits(text: str, limit: int, domains: tuple[str, ...] = ()) -> SearchPage:
    if len(text.encode()) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response limit exceeded")
    # Provider metadata envelopes, never links mined from the retrieved body.
    matches = list(
        re.finditer(r"(?m)^Title: ([^\n]+)\nURL: ([^\n]+)\n(?:Published|Published Date):", text)
    )
    if not matches:
        raise ValueError("Unrecognised provider result format")
    hits: list[SearchHit] = []
    seen: set[str] = set()
    rejected = 0
    truncated = False
    for index, match in enumerate(matches):
        try:
            url = normalize_public_http_url(match.group(2).strip())
        except (TypeError, ValueError):
            rejected += 1
            continue
        if domains and not any(host_matches(url, domain) for domain in domains):
            rejected += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        if len(hits) == limit:
            truncated = True
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        snippet = text[match.end() : end].partition("Highlights:\n")[2].strip()
        title = match.group(1).strip()
        truncated |= len(snippet) > 4096 or len(title) > 300
        hits.append(SearchHit(title=title[:300], url=url, snippet=snippet[:4096], rank=index + 1))
    return SearchPage(hits=hits, rejected=rejected, truncated=truncated)


def classify_failure(error) -> Failure:
    if isinstance(error, SearchUnavailable):
        return error.failure
    if isinstance(error, BaseExceptionGroup):
        failures = [classify_failure(item) for item in error.exceptions]
        return next((item for item in failures if item.code != "source_unavailable"), failures[0])
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            seconds = parse_retry_after(error.response.headers)
            delay = (
                min(math.ceil(seconds), 86400)
                if seconds is not None and math.isfinite(seconds)
                else None
            )
            return Failure(
                code="rate_limited",
                message="Free search limit reached. Try later.",
                retry_after_seconds=delay,
            )
        if status in {401, 402, 403}:
            return Failure(code="access_denied", message="Free search is currently unavailable.")
    return Failure(code="source_unavailable", message="Search could not complete. Try later.")


class ExaKeylessSearch:
    async def search(
        self, query: str, *, objective: str, limit: int = 5, domains: tuple[str, ...] = ()
    ) -> SearchPage:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("Search query requires 1–2000 characters")
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 4096:
            raise ValueError("Search objective requires 1–4096 characters")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ValueError("Free search requires 1–10 results")
        domains = tuple(
            httpx.URL(normalize_public_http_url(f"https://{domain}")).host for domain in domains
        )
        try:
            async with (
                asyncio.timeout(20),
                httpx.AsyncClient(
                    transport=LimitedTransport(),
                    timeout=15,
                    follow_redirects=False,
                    trust_env=False,
                    headers={"Accept-Encoding": "identity"},
                ) as client,
                streamable_http_client(ENDPOINT, http_client=client) as (
                    receive,
                    send,
                    _session_id,
                ),
                ClientSession(receive, send, read_timeout_seconds=timedelta(seconds=15)) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                tool = next((item for item in tools.tools if item.name == "web_search_exa"), None)
                if tool is None or set(tool.inputSchema.get("required", [])) - {
                    "query",
                    "objective",
                    "numResults",
                }:
                    raise ValueError("Unsupported provider operation")
                result = await session.call_tool(
                    "web_search_exa",
                    {"query": query, "objective": objective, "numResults": limit},
                )
                if result.isError:
                    error_text = " ".join(
                        item.text for item in result.content if item.type == "text"
                    ).lower()
                    if "rate limit" in error_text or "too many requests" in error_text:
                        raise SearchUnavailable(
                            Failure(
                                code="rate_limited", message="Free search limit reached. Try later."
                            )
                        )
                    raise ValueError("Provider tool error")
                text = "\n".join(item.text for item in result.content if item.type == "text")
                page = parse_hits(text, limit, domains)
                return page.model_copy(update={"query": query})
        except Exception as error:  # noqa: BLE001 - redact SDK/provider failures at the product boundary
            raise SearchUnavailable(classify_failure(error)) from None

    async def search_job(
        self,
        database,
        context: ExecutionContext,
        query: str,
        *,
        operation_key: str,
        objective: str,
        limit: int = 5,
        domains: tuple[str, ...] = (),
    ) -> SearchPage:
        if context.reservation_id is not None:
            raise ValueError(
                "Use the worker's existing reservation boundary for pre-reserved stages"
            )
        if context.attempt_budget < 1 or datetime.now(UTC) >= context.deadline:
            raise SearchUnavailable(
                Failure(code="deadline_exceeded", message="Search attempt is no longer permitted.")
            )

        def prepare():
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                job = locked_job(session, str(context.job_id))
                plan = ConversationRepository.get_plan(session, job["plan_id"])
                if plan["revision"] != context.plan_revision:
                    raise ValueError("Execution plan revision mismatch")
                existing = session.execute(
                    sa.select(reservations.c.id).where(
                        reservations.c.workspace_id == str(context.workspace_id),
                        reservations.c.idempotency_key == operation_key,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    raise ValueError(
                        "Search operation already reserved; use its persisted checkpoint"
                    )
                row = reserve(session, str(context.job_id), operation_key, 0, {"search_calls": 1})
                if row["state"] != "held":
                    raise ValueError(
                        "Search operation already reconciled; use its persisted checkpoint"
                    )
                return row["id"]

        reservation_id = await asyncio.to_thread(prepare)

        def finish(status):
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                reconcile(
                    session,
                    str(context.job_id),
                    reservation_id,
                    status=status,
                    cost=0 if status == "confirmed" else None,
                    actual_dimensions={"search_calls": 1} if status == "confirmed" else None,
                )

        try:
            page = await self.search(query, objective=objective, limit=limit, domains=domains)
        except ValueError:
            await asyncio.to_thread(finish, "not_charged")
            raise
        except (Exception, asyncio.CancelledError):
            await asyncio.shield(asyncio.to_thread(finish, "estimated"))
            raise
        await asyncio.to_thread(finish, "confirmed")
        return page
