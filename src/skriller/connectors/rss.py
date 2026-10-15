"""Bounded RSS/Atom parsing using the copied Agent-Reach feedparser dependency.

The caller supplies bytes from the product's guarded HTTP fetch path. Parsing
never fetches a feed or follows an entry link itself.
"""

from __future__ import annotations

from calendar import timegm
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from urllib.parse import urljoin

import feedparser
from agent_reach.utils.url import normalize_public_http_url

MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 100
MAX_SUMMARY_CHARS = 8192


@dataclass(frozen=True)
class FeedEntry:
    entry_id: str
    title: str
    url: str
    feed_url: str
    published_at: str | None
    summary: str
    summary_truncated: bool
    updated_at: str | None = None
    source: str = "rss"


@dataclass(frozen=True)
class FeedParseResult:
    feed_url: str
    entries: tuple[FeedEntry, ...]
    duplicate_count: int
    invalid_link_count: int
    truncated_entry_count: int
    malformed: bool
    omitted_entry_count: int = 0


def _date(entry, keys) -> str | None:
    for key in keys:
        if key not in entry:
            continue  # Avoid feedparser's compatibility aliases between date kinds.
        parsed = entry.get(key)
        if isinstance(parsed, struct_time):
            try:
                return datetime.fromtimestamp(timegm(parsed), tz=UTC).isoformat()
            except (OverflowError, OSError, ValueError):
                return None
    return None


def parse_feed(body: bytes, feed_url: str, *, max_entries: int = MAX_ENTRIES) -> FeedParseResult:
    """Parse a bounded already-fetched feed, retaining its own IDs and dates.

    Invalid/private entry links are excluded, never passed to another fetcher.
    Duplicate IDs or canonical links are counted once. A missing or malformed
    publication date remains ``None``; fetch time is never substituted.
    """
    if not isinstance(body, bytes):
        raise TypeError("Feed body must be bytes from the guarded fetch stage")
    if not 1 <= max_entries <= MAX_ENTRIES:
        raise ValueError("Feed entry limit must be between 1 and 100")
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("Feed body exceeds its 2 MiB limit")
    normalized_feed = normalize_public_http_url(feed_url)
    parsed = feedparser.parse(
        body,
        response_headers={"content-type": "application/xml; charset=utf-8"},
        resolve_relative_uris=True,
        sanitize_html=True,
    )
    entries: list[FeedEntry] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    duplicate_count = invalid_link_count = truncated_entry_count = 0
    inspected = 0
    for item in parsed.entries[:MAX_ENTRIES]:
        inspected += 1
        raw_link = item.get("link")
        if not isinstance(raw_link, str) or not raw_link.strip():
            invalid_link_count += 1
            continue
        try:
            link = normalize_public_http_url(urljoin(normalized_feed, raw_link.strip()))
        except ValueError:
            invalid_link_count += 1
            continue
        raw_id = item.get("id")
        identifier = raw_id.strip() if isinstance(raw_id, str) else ""
        if not identifier or len(identifier) > 512:
            identifier = link
        if identifier in seen_ids or link in seen_urls:
            duplicate_count += 1
            continue
        seen_ids.add(identifier)
        seen_urls.add(link)
        raw_title = item.get("title", "")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        raw_summary = item.get("summary", "")
        summary = raw_summary if isinstance(raw_summary, str) else ""
        truncated = len(summary) > MAX_SUMMARY_CHARS
        if truncated:
            summary = summary[:MAX_SUMMARY_CHARS]
            truncated_entry_count += 1
        entries.append(
            FeedEntry(
                entry_id=identifier,
                title=title[:1000],
                url=link,
                feed_url=normalized_feed,
                published_at=_date(item, ("published_parsed",)),
                updated_at=_date(item, ("updated_parsed",)),
                summary=summary,
                summary_truncated=truncated,
            )
        )
        if len(entries) >= max_entries:
            break
    return FeedParseResult(
        feed_url=normalized_feed,
        entries=tuple(entries),
        duplicate_count=duplicate_count,
        invalid_link_count=invalid_link_count,
        truncated_entry_count=truncated_entry_count,
        malformed=bool(parsed.get("bozo", False)) or not bool(parsed.get("version")),
        omitted_entry_count=max(0, len(parsed.entries) - inspected),
    )


def public_rss_binding(database=None, proxy_url=None, *, operation_key="rss_read"):
    from skriller.connectors.fetch import HTTPFetcher
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, url):
        if database is None or proxy_url is None or context.connection_ref is not None:
            raise ValueError("Public RSS collecting configuration required")
        return HTTPFetcher(
            database, trusted_proxy_url=proxy_url, max_body_bytes=MAX_FEED_BYTES
        ).fetch(
            context,
            url,
            source="rss",
            operation_key=operation_key,
        )

    return AdapterBinding(
        Capability(
            source="rss",
            operation="read",
            engineering_status="implemented",
            operational_status="experimental",
            access_route="Guarded public RSS/Atom bytes; no entry-link following",
            auth_kind="none",
            version="feedparser_6.0.14",
            allowed_fields=["entry_id", "title", "published_at", "updated_at", "summary", "url"],
        ),
        "public_rss_feed",
        execute,
    )
