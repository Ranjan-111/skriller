"""Read-only, unauthenticated GitHub public repository and profile metadata.

The public API route is deliberately independent of the user's gh credentials.
It cannot read private repositories or perform writes. Search snippets remain a
separate evidence kind from these dated API observations.
"""

import math
import re
from datetime import UTC, datetime
from time import monotonic
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from agent_reach.utils.url import normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from scrapling.spiders.throttle import parse_retry_after

API = "https://api.github.com"
API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 256_000
TIMEOUT_SECONDS = 8.0


class GitHubUnavailable(RuntimeError):
    def __init__(
        self,
        code: Literal["not_found", "rate_limited", "source_unavailable"],
        retry_after_seconds: int | None = None,
    ):
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


class PublicOwner(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    login: str = Field(min_length=1, max_length=100)
    type: Literal["User", "Organization"]


class PublicRepository(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int = Field(ge=1, strict=True)
    full_name: str = Field(min_length=1, max_length=300)
    html_url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public"]
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None = None
    stargazers_count: int = Field(ge=0, strict=True)
    forks_count: int = Field(ge=0, strict=True)
    open_issues_count: int = Field(ge=0, strict=True)
    language: str | None = Field(default=None, max_length=100)
    owner: PublicOwner


class PublicProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int = Field(ge=1, strict=True)
    login: str = Field(min_length=1, max_length=100)
    type: Literal["User", "Organization"]
    html_url: str = Field(max_length=2048)
    name: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    blog: str | None = Field(default=None, max_length=2048)
    public_repos: int = Field(ge=0, strict=True)
    followers: int = Field(ge=0, strict=True)
    created_at: datetime
    updated_at: datetime


class GitHubEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["github"] = "github"
    evidence_kind: Literal["public_api_metadata"] = "public_api_metadata"
    access_scope: Literal["public_only"] = "public_only"
    observed_at: datetime
    source_url: str = Field(max_length=2048)
    record: PublicRepository | PublicProfile
    network_seconds: float = Field(ge=0, le=180)
    parser_seconds: float = Field(ge=0, le=180)


def _repo_path(url: str) -> tuple[str, str]:
    canonical = normalize_public_http_url(url)
    parsed = urlsplit(canonical)
    if parsed.hostname not in {"github.com", "www.github.com"} or parsed.query or parsed.fragment:
        raise ValueError("A GitHub public repository URL is required")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or any(part in {".", ".."} for part in parts):
        raise ValueError("Only public owner/repository URLs are supported")
    owner, repo = parts
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid GitHub owner or repository")
    repo = repo.removesuffix(".git")
    if not repo or repo in {".", ".."}:
        raise ValueError("Invalid GitHub repository")
    return owner, repo


def _profile_path(login: str) -> str:
    if not isinstance(login, str) or not login or len(login) > 100:
        raise ValueError("Bounded GitHub profile name required")
    if not login.replace("-", "").isalnum():
        raise ValueError("Invalid GitHub profile name")
    return quote(login, safe="")


def _public_html_url(value: str, expected_path: str) -> str:
    try:
        canonical = normalize_public_http_url(value)
        parsed = urlsplit(canonical)
    except ValueError as exc:
        raise GitHubUnavailable("source_unavailable") from exc
    if (
        parsed.hostname not in {"github.com", "www.github.com"}
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/").casefold() != expected_path.casefold()
    ):
        raise GitHubUnavailable("source_unavailable")
    return canonical


class GitHubPublicReader:
    """Fetch allowlisted public API records; no caller URL or auth token is sent."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        trusted_proxy_url: str | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ):
        if not 0 < timeout_seconds <= TIMEOUT_SECONDS:
            raise ValueError("Bounded GitHub request timeout required")
        if trusted_proxy_url:
            from skriller.connectors.fetch import HTTPFetcher

            endpoint = urlsplit(trusted_proxy_url)
            validation_url = trusted_proxy_url
            if endpoint.username is not None or endpoint.password is not None:
                # Only our authenticated, short-lived loopback gateway may carry
                # credentials. httpx uses them for CONNECT, never origin headers.
                if (
                    endpoint.username != "task"
                    or not re.fullmatch(r"[A-Za-z0-9_-]{43}", endpoint.password or "")
                    or endpoint.hostname not in {"127.0.0.1", "::1", "localhost"}
                ):
                    raise ValueError("Invalid task gateway credentials")
                host = f"[{endpoint.hostname}]" if ":" in endpoint.hostname else endpoint.hostname
                validation_url = urlunsplit(
                    (
                        endpoint.scheme,
                        f"{host}:{endpoint.port}",
                        endpoint.path,
                        endpoint.query,
                        endpoint.fragment,
                    )
                )
            HTTPFetcher(None, trusted_proxy_url=validation_url)
        self._transport = transport
        self._proxy = trusted_proxy_url
        self._timeout = timeout_seconds

    async def _get(self, path: str) -> tuple[dict, float, float]:
        if not (
            re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path)
            or re.fullmatch(r"/users/[A-Za-z0-9-]+", path)
        ):
            raise ValueError("GitHub API operation is not allowlisted")
        network_started = monotonic()
        async with httpx.AsyncClient(
            base_url=API,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            proxy=self._proxy,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "Skriller-public-research/1.0",
            },
        ) as client:
            try:
                async with client.stream("GET", path) as response:
                    if response.status_code == 404:
                        # GitHub intentionally also hides private resources as 404.
                        raise GitHubUnavailable("not_found")
                    if response.status_code == 429 or (
                        response.status_code == 403
                        and response.headers.get("x-ratelimit-remaining") == "0"
                    ):
                        delay = parse_retry_after(response.headers)
                        wait = (
                            min(86400, max(60, math.ceil(delay)))
                            if delay is not None and math.isfinite(delay)
                            else 60
                        )
                        raise GitHubUnavailable("rate_limited", wait)
                    if response.status_code != 200:
                        raise GitHubUnavailable("source_unavailable")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise GitHubUnavailable("source_unavailable")
                        chunks.append(chunk)
            except GitHubUnavailable:
                raise
            except (httpx.HTTPError, TimeoutError) as exc:
                raise GitHubUnavailable("source_unavailable") from exc
        network_seconds = monotonic() - network_started
        parser_started = monotonic()
        try:
            value = httpx.Response(200, content=b"".join(chunks)).json()
        except ValueError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        if not isinstance(value, dict):
            raise GitHubUnavailable("source_unavailable")
        return value, network_seconds, monotonic() - parser_started

    async def repository(self, url: str) -> GitHubEvidence:
        owner, repo = _repo_path(url)
        raw, network_seconds, parser_seconds = await self._get(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        )
        validation_started = monotonic()
        if raw.get("visibility") != "public":
            raise GitHubUnavailable("not_found")
        try:
            record = PublicRepository.model_validate(raw)
        except ValidationError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        if record.full_name.casefold() != f"{owner}/{repo}".casefold():
            raise GitHubUnavailable("source_unavailable")
        return GitHubEvidence(
            observed_at=datetime.now(UTC),
            source_url=_public_html_url(record.html_url, f"/{owner}/{repo}"),
            record=record,
            network_seconds=network_seconds,
            parser_seconds=parser_seconds + monotonic() - validation_started,
        )

    async def profile(self, login: str) -> GitHubEvidence:
        raw, network_seconds, parser_seconds = await self._get(f"/users/{_profile_path(login)}")
        validation_started = monotonic()
        try:
            record = PublicProfile.model_validate(raw)
        except ValidationError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        return GitHubEvidence(
            observed_at=datetime.now(UTC),
            source_url=_public_html_url(record.html_url, f"/{login}"),
            record=record,
            network_seconds=network_seconds,
            parser_seconds=parser_seconds + monotonic() - validation_started,
        )

    async def read_url(self, url: str) -> GitHubEvidence:
        canonical = normalize_public_http_url(url)
        parts = [part for part in urlsplit(canonical).path.split("/") if part]
        if len(parts) == 1:
            _public_html_url(canonical, f"/{parts[0]}")
            return await self.profile(parts[0])
        _repo_path(canonical)
        return await self.repository(canonical)


def public_github_binding(reader=None):
    """Registered bounded public route; no gh auth or source-account discovery."""
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    adapter = reader or GitHubPublicReader()

    async def execute(context, url):
        if context.connection_ref is not None:
            raise GitHubUnavailable("source_unavailable")
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise GitHubUnavailable("source_unavailable")
        import asyncio

        async with asyncio.timeout(min(TIMEOUT_SECONDS, remaining)):
            return await adapter.read_url(url)

    return AdapterBinding(
        Capability(
            source="github",
            operation="read",
            engineering_status="implemented",
            operational_status="experimental",
            access_route="Unauthenticated public GitHub API metadata; local opt-in collecting",
            auth_kind="none",
            version=API_VERSION,
            allowed_fields=["resource_id", "public_counters", "created_at", "updated_at"],
        ),
        "public_github_api",
        execute,
    )
