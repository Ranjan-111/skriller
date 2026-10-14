"""Read-only, unauthenticated GitHub public repository and profile metadata.

The public API route is deliberately independent of the user's gh credentials.
It cannot read private repositories or perform writes. Search snippets remain a
separate evidence kind from these dated API observations.
"""

import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from agent_reach.utils.url import domain_matches, normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field, ValidationError

API = "https://api.github.com"
API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 256_000
TIMEOUT_SECONDS = 8.0


class GitHubUnavailable(RuntimeError):
    def __init__(self, code: Literal["not_found", "rate_limited", "source_unavailable"]):
        self.code = code
        super().__init__(code)


class PublicRepository(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int = Field(ge=1)
    full_name: str = Field(min_length=1, max_length=300)
    html_url: str = Field(max_length=2048)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Literal["public"]
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None = None
    stargazers_count: int = Field(ge=0)
    forks_count: int = Field(ge=0)
    open_issues_count: int = Field(ge=0)
    language: str | None = Field(default=None, max_length=100)
    owner: dict


class PublicProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    login: str = Field(min_length=1, max_length=100)
    type: Literal["User", "Organization"]
    html_url: str = Field(max_length=2048)
    name: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    blog: str | None = Field(default=None, max_length=2048)
    public_repos: int = Field(ge=0)
    followers: int = Field(ge=0)
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


def _repo_path(url: str) -> tuple[str, str]:
    canonical = normalize_public_http_url(url)
    parsed = urlsplit(canonical)
    if not domain_matches(parsed.hostname or "", "github.com"):
        raise ValueError("A GitHub public repository URL is required")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or any(part in {".", ".."} for part in parts):
        raise ValueError("Only public owner/repository URLs are supported")
    owner, repo = parts
    if not all(part.replace("-", "").replace("_", "").isalnum() for part in parts):
        raise ValueError("Invalid GitHub owner or repository")
    return owner, repo.removesuffix(".git")


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
        not domain_matches(parsed.hostname or "", "github.com")
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/").casefold() != expected_path.casefold()
    ):
        raise GitHubUnavailable("source_unavailable")
    return canonical


class GitHubPublicReader:
    """Fetch allowlisted public API records; no caller URL or auth token is sent."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def _get(self, path: str) -> dict:
        if not (
            re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path)
            or re.fullmatch(r"/users/[A-Za-z0-9-]+", path)
        ):
            raise ValueError("GitHub API operation is not allowlisted")
        async with httpx.AsyncClient(
            base_url=API,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
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
                    if (
                        response.status_code == 403
                        and response.headers.get("x-ratelimit-remaining") == "0"
                    ):
                        raise GitHubUnavailable("rate_limited")
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
        try:
            value = httpx.Response(200, content=b"".join(chunks)).json()
        except ValueError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        if not isinstance(value, dict):
            raise GitHubUnavailable("source_unavailable")
        return value

    async def repository(self, url: str) -> GitHubEvidence:
        owner, repo = _repo_path(url)
        raw = await self._get(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}")
        if raw.get("visibility") != "public":
            raise GitHubUnavailable("not_found")
        try:
            record = PublicRepository.model_validate(raw)
        except ValidationError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        return GitHubEvidence(
            observed_at=datetime.now(UTC),
            source_url=_public_html_url(record.html_url, f"/{owner}/{repo}"),
            record=record,
        )

    async def profile(self, login: str) -> GitHubEvidence:
        raw = await self._get(f"/users/{_profile_path(login)}")
        try:
            record = PublicProfile.model_validate(raw)
        except ValidationError as exc:
            raise GitHubUnavailable("source_unavailable") from exc
        return GitHubEvidence(
            observed_at=datetime.now(UTC),
            source_url=_public_html_url(record.html_url, f"/{record.login}"),
            record=record,
        )
