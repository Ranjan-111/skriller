import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from skriller.connectors.reddit_discovery import RedditCursor, RedditSearch, parse_search_listing

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def post(identifier="abc123", **changes):
    return {
        "kind": "t3",
        "data": {
            "id": identifier,
            "title": "CRM migration discussion",
            "subreddit": "startups",
            "author": "anonymous_handle",
            "selftext": "We are evaluating CRM options.",
            "permalink": f"/r/startups/comments/{identifier}/crm/",
            **changes,
        },
    }


def listing(*posts, after=None):
    return {"kind": "Listing", "data": {"children": list(posts), "after": after}}


def test_uses_unchanged_pinned_models_and_parser():
    root = Path(__file__).resolve().parents[2]
    subset = root / "src/skriller/_vendor/reddit"
    provenance = json.loads((subset / "PROVENANCE.json").read_text())
    assert provenance["commit"] == "5e4fb3720d5c174e976cd425ccc3b879d52cac66"
    for name, record in provenance["files"].items():
        body = (subset / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == record["sha256"]
        assert body == (root / "third_party/external/reddit" / record["source"]).read_bytes()


def test_filters_cursor_source_dates_and_unknown_identity_are_preserved():
    request = RedditSearch(
        query="CRM",
        subreddit="startups",
        time_filter="week",
        sort="new",
        cursor=RedditCursor(after="t3_old123"),
    )
    assert request.backend_arguments() == {
        "query": "CRM",
        "subreddit": "startups",
        "sort": "new",
        "time_filter": "week",
        "limit": 10,
        "after": "t3_old123",
    }
    page = parse_search_listing(
        listing(post(created_utc=1700000000), after="t3_next123"), request, observed_at=NOW
    )
    assert page.next_cursor.after == "t3_next123"
    assert page.posts[0].published_at == datetime.fromtimestamp(1700000000, UTC)
    assert page.posts[0].author_identity == "unknown"
    assert page.posts[0].author_handle == "anonymous_handle"
    assert page.status == "parsed_not_live_verified"


def test_deleted_content_and_missing_date_do_not_become_generated_evidence():
    page = parse_search_listing(
        listing(post(author="[deleted]", selftext="[removed]")),
        RedditSearch(query="CRM"),
        observed_at=NOW,
    )
    item = page.posts[0]
    assert item.published_at is None and item.author_handle is None
    assert item.content_unavailable and item.excerpt == ""


def test_source_community_mismatch_is_rejected_even_without_a_requested_filter():
    page = parse_search_listing(
        listing(post(subreddit="other")), RedditSearch(query="CRM"), observed_at=NOW
    )
    assert page.posts == () and page.rejected_count == 1


def test_deduplication_filter_enforcement_and_result_cap_remain_explicit():
    page = parse_search_listing(
        listing(
            post(),
            post(),
            post("def456"),
            post("ghi789", subreddit="other"),
            post("jkl123", permalink="https://evil.example/comments/jkl123"),
        ),
        RedditSearch(query="CRM", subreddit="startups", limit=1),
        observed_at=NOW,
    )
    assert len(page.posts) == 1
    assert page.duplicate_count == 1 and page.rejected_count == 2 and page.omitted_count == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "error", "data": {}},
        listing({"kind": "t1", "data": {}}),
        listing(post(), after="https://evil.example/cursor"),
    ],
)
def test_invalid_listing_is_not_a_successful_empty_search(bad):
    with pytest.raises(ValueError):
        parse_search_listing(bad, RedditSearch(query="CRM"), observed_at=NOW)


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "CRM", "subreddit": "startups/../../"},
        {"query": "CRM", "time_filter": "forever"},
        {"query": "CRM", "limit": True},
        {"query": "CRM", "limit": 26},
    ],
)
def test_requests_refuse_unsupported_or_unbounded_filters(arguments):
    with pytest.raises(ValidationError):
        RedditSearch(**arguments)
