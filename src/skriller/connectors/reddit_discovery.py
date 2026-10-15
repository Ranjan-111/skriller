"""Bounded Reddit listing adaptation over the unchanged pinned rdt-cli parser.

This module does not load credentials, create a client or mark a search ready.
The isolated execution layer must supply a real listing and own authorization,
budgeting and live verification independently of successful parsing.
"""

import json
import math
import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit

from agent_reach.utils.url import host_matches, normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field

from skriller._vendor.reddit.parser import parse_listing
from skriller.connectors.candidates import native_reference


class DiscoveryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RedditCursor(DiscoveryData):
    after: str = Field(pattern=r"^t3_[a-z0-9]{3,13}$")


class RedditSearch(DiscoveryData):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    subreddit: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,32}$")
    sort: Literal["relevance", "hot", "top", "new", "comments"] = "relevance"
    time_filter: Literal["all", "hour", "day", "week", "month", "year"] = "all"
    limit: int = Field(default=10, ge=1, le=25)
    cursor: RedditCursor | None = None

    def backend_arguments(self):
        """Exact reviewed rdt-cli search signature, never arbitrary tool args."""
        return {
            "query": self.query,
            "subreddit": self.subreddit,
            "sort": self.sort,
            "time_filter": self.time_filter,
            "limit": self.limit,
            "after": self.cursor.after if self.cursor else None,
        }


class RedditPostReference(DiscoveryData):
    native_id: str
    source_url: str
    title: str
    subreddit: str
    author_handle: str | None
    author_identity: Literal["unknown"] = "unknown"
    excerpt: str
    content_unavailable: bool
    truncated: bool
    published_at: datetime | None


class RedditDiscoveryPage(DiscoveryData):
    source: Literal["reddit"] = "reddit"
    backend: Literal["rdt_cli"] = "rdt_cli"
    status: Literal["parsed_not_live_verified"] = "parsed_not_live_verified"
    request: RedditSearch
    posts: tuple[RedditPostReference, ...]
    next_cursor: RedditCursor | None
    rejected_count: int
    duplicate_count: int
    omitted_count: int
    observed_at: datetime


def parse_search_listing(
    payload: dict, request: RedditSearch, *, observed_at: datetime
) -> RedditDiscoveryPage:
    """Retain source dates, handles and cursors without asserting person identity."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("An aware observation time is required")
    # Bound the upstream parser's permissive input before calling it. Search
    # listing bodies are data only; comments/replies are handled separately.
    if len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576:
        raise ValueError("Reddit listing exceeds bounds")
    data = payload.get("data")
    if payload.get("kind") != "Listing" or not isinstance(data, dict):
        raise ValueError("Expected a Reddit search listing")
    children = data.get("children")
    if not isinstance(children, list) or len(children) > 100:
        raise ValueError("Reddit listing children exceed bounds")
    if any(
        not isinstance(child, dict)
        or child.get("kind") != "t3"
        or not isinstance(child.get("data"), dict)
        for child in children
    ):
        raise ValueError("Search listing contains unsupported resource kinds")
    cursor = RedditCursor(after=data["after"]) if data.get("after") is not None else None
    listing = parse_listing(payload)
    posts: list[RedditPostReference] = []
    rejected = duplicates = omitted = 0
    seen: set[str] = set()
    for post in listing.items:
        try:
            url = normalize_public_http_url(urljoin("https://www.reddit.com", post.permalink))
            native = native_reference(url)
            source_community = re.match(r"^/r/([A-Za-z0-9_]{1,32})/comments/", urlsplit(url).path)
            if (
                not host_matches(url, "reddit.com")
                or native != {"namespace": "reddit_post", "id": post.id}
                or not post.title.strip()
                or not post.subreddit
                or source_community is None
                or source_community[1].casefold() != post.subreddit.casefold()
                or request.subreddit is not None
                and post.subreddit.casefold() != request.subreddit.casefold()
            ):
                raise ValueError("Listing reference does not match its source filters")
        except ValueError:
            rejected += 1
            continue
        if post.id in seen:
            duplicates += 1
            continue
        seen.add(post.id)
        if len(posts) >= request.limit:
            omitted += 1
            continue
        published = None
        if math.isfinite(post.created_utc) and 0 < post.created_utc <= observed_at.timestamp():
            published = datetime.fromtimestamp(post.created_utc, UTC)
        unavailable = post.selftext in {"[deleted]", "[removed]"}
        posts.append(
            RedditPostReference(
                native_id="t3_" + post.id,
                source_url=url,
                title=post.title[:300],
                subreddit=post.subreddit[:32],
                author_handle=(
                    None if post.author in {"", "[deleted]", "[removed]"} else post.author[:100]
                ),
                excerpt="" if unavailable else post.selftext[:4096],
                content_unavailable=unavailable,
                truncated=len(post.title) > 300 or len(post.selftext) > 4096,
                published_at=published,
            )
        )
    return RedditDiscoveryPage(
        request=request,
        posts=tuple(posts),
        next_cursor=cursor,
        rejected_count=rejected,
        duplicate_count=duplicates,
        omitted_count=omitted,
        observed_at=observed_at,
    )
