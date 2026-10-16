"""Bounded X search parsing over copied twitter-cli code; no source execution."""

import json
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from skriller._vendor.twitter.parser import _deep_get, parse_timeline_response


class XSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    limit: int = Field(default=10, ge=1, le=25)
    mode: Literal["Top", "Latest"] = "Latest"

    def backend_arguments(self):
        return {"query": self.query, "count": self.limit, "product": self.mode}


class XPostReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_id: str
    source_url: str
    author_handle: str
    author_identity: Literal["unknown"] = "unknown"
    excerpt: str
    published_at: datetime | None
    is_repost: bool
    reposted_by: str | None
    truncated: bool


class XDiscoveryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["x"] = "x"
    backend: Literal["twitter_cli"] = "twitter_cli"
    status: Literal["parsed_not_live_verified"] = "parsed_not_live_verified"
    request: XSearch
    posts: tuple[XPostReference, ...]
    has_more: bool
    pagination_status: Literal["not_implemented"] = "not_implemented"
    rejected_count: int
    duplicate_count: int
    omitted_count: int
    observed_at: datetime


class XRestPost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    native_id: str = Field(pattern=r"^x_post:[0-9]{1,25}$")
    source_url: str = Field(pattern=r"^https://x\.com/[A-Za-z0-9_]{1,15}/status/[0-9]{1,25}$")
    author_handle: str = Field(min_length=1, max_length=15, pattern=r"^[A-Za-z0-9_]+$")
    author_identity: Literal["x_user_id"] = "x_user_id"
    excerpt: str = Field(min_length=1, max_length=4096)
    published_at: datetime | None = None


class XRestPage(BaseModel):
    """Official X API search result with no engagement or inferred lead fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["x"] = "x"
    backend: Literal["x_api_v2_recent_search"] = "x_api_v2_recent_search"
    status: Literal["parsed_not_live_verified"] = "parsed_not_live_verified"
    request: XSearch
    posts: tuple[XRestPost, ...]
    has_more: bool
    pagination_status: Literal["not_implemented"] = "not_implemented"
    rejected_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    observed_at: datetime


def parse_rest_search(payload, request: XSearch, *, observed_at: datetime) -> XRestPage:
    """Validate bounded X API v2 recent-search JSON and retain source attribution."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    if (
        not isinstance(payload, dict)
        or len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576
    ):
        raise ValueError("X API response exceeds bounds")
    if payload.get("errors") or not isinstance(payload.get("data", []), list):
        raise ValueError("X API returned an unsuccessful response")
    data = payload.get("data", [])
    includes = payload.get("includes", {})
    users = includes.get("users", []) if isinstance(includes, dict) else []
    if not isinstance(users, list) or len(users) > 100:
        raise ValueError("X API user expansion exceeds bounds")
    handles = {}
    for user in users:
        if (
            isinstance(user, dict)
            and isinstance(user.get("id"), str)
            and isinstance(user.get("username"), str)
            and re.fullmatch(r"[A-Za-z0-9_]{1,15}", user["username"])
        ):
            handles[user["id"]] = user["username"]
    posts: list[XRestPost] = []
    rejected = omitted = 0
    seen = set()
    if len(data) > 100:
        raise ValueError("X API result count exceeds bounds")
    for item in data:
        if not isinstance(item, dict):
            rejected += 1
            continue
        identifier, author_id, text = item.get("id"), item.get("author_id"), item.get("text")
        handle = handles.get(author_id)
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[0-9]{1,25}", identifier)
            or not isinstance(author_id, str)
            or not handle
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 65536
        ):
            rejected += 1
            continue
        if identifier in seen:
            rejected += 1
            continue
        seen.add(identifier)
        if len(posts) >= request.limit:
            omitted += 1
            continue
        published = None
        created = item.get("created_at")
        if isinstance(created, str):
            try:
                candidate = datetime.fromisoformat(created)
                if candidate.tzinfo and candidate <= observed_at:
                    published = candidate.astimezone(UTC)
            except ValueError:
                pass
        posts.append(
            XRestPost(
                native_id="x_post:" + identifier,
                source_url=f"https://x.com/{handle}/status/{identifier}",
                author_handle=handle,
                excerpt=text[:4096],
                published_at=published,
            )
        )
    meta = payload.get("meta", {})
    if not isinstance(meta, dict):
        raise TypeError("Invalid X API metadata")
    return XRestPage(
        request=request,
        posts=tuple(posts),
        has_more=isinstance(meta.get("next_token"), str) and bool(meta.get("next_token")),
        rejected_count=rejected,
        omitted_count=omitted,
        observed_at=observed_at,
    )


def _bounded(payload):
    if not isinstance(payload, dict):
        raise TypeError("Expected an X timeline object")
    pending, count, tweet_results = [(payload, 0)], 0, 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 10000 or depth > 32:
            raise ValueError("X timeline structure exceeds bounds")
        if isinstance(node, dict):
            if len(node) > 10000 or any(not isinstance(key, str) for key in node):
                raise ValueError("X timeline object exceeds bounds")
            tweet_results += int("tweet_results" in node)
            pending.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            if len(node) > 10000:
                raise ValueError("X timeline collection exceeds bounds")
            pending.extend((value, depth + 1) for value in node)
    if len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576:
        raise ValueError("X timeline body exceeds bounds")
    return tweet_results


def parse_search_timeline(payload, request: XSearch, *, observed_at: datetime):
    """Retain literal source text and unknown identity without invented metrics.

    Upstream defaults missing counts to zero, so this adapter deliberately does
    not publish engagement metrics. It never loads a client, cookies or tools.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Aware observation time required")
    raw_results = _bounded(payload)
    instructions = _deep_get(
        payload, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions"
    )
    if payload.get("errors") or not isinstance(instructions, list) or len(instructions) > 100:
        raise ValueError("Expected a successful bounded X search timeline")
    try:
        tweets, cursor = parse_timeline_response(payload, lambda _: instructions)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise ValueError("Malformed X timeline response") from None
    if cursor is not None and (
        not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024 or not cursor.isprintable()
    ):
        raise ValueError("Invalid X pagination metadata")
    posts: list[XPostReference] = []
    seen: set[str] = set()
    rejected = max(0, raw_results - len(tweets))
    duplicates = omitted = 0
    for tweet in tweets:
        if (
            not isinstance(tweet.id, str)
            or not re.fullmatch(r"[0-9]{1,25}", tweet.id)
            or not isinstance(tweet.author.screen_name, str)
            or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", tweet.author.screen_name)
            or tweet.author.screen_name == "unknown"
            or not isinstance(tweet.text, str)
            or not tweet.text.strip()
            or len(tweet.text) > 65536
            or tweet.is_promoted
            or tweet.is_subscriber_only
        ):
            rejected += 1
            continue
        if tweet.id in seen:
            duplicates += 1
            continue
        seen.add(tweet.id)
        if len(posts) >= request.limit:
            omitted += 1
            continue
        published = None
        if isinstance(tweet.created_at, str):
            try:
                candidate = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
                if candidate <= observed_at:
                    published = candidate.astimezone(UTC)
            except ValueError:
                pass
        posts.append(
            XPostReference(
                native_id="x_post:" + tweet.id,
                source_url=f"https://x.com/{tweet.author.screen_name}/status/{tweet.id}",
                author_handle=tweet.author.screen_name,
                excerpt=tweet.text[:4096],
                published_at=published,
                is_repost=tweet.is_retweet,
                reposted_by=tweet.retweeted_by,
                truncated=len(tweet.text) > 4096,
            )
        )
    return XDiscoveryPage(
        request=request,
        posts=tuple(posts),
        has_more=bool(cursor),
        rejected_count=rejected,
        duplicate_count=duplicates,
        omitted_count=omitted,
        observed_at=observed_at,
    )
