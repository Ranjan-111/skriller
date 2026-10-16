"""Adapt pinned upstream parser fixtures plus conservative product boundaries."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from skriller._vendor.twitter.parser import _deep_get, parse_timeline_response
from skriller.connectors.registry import ConnectorRegistry
from skriller.connectors.x_discovery import XSearch, parse_rest_search, parse_search_timeline

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/external/twitter"
NOW = datetime(2026, 10, 16, tzinfo=UTC)


def fixture(name):
    return json.loads((SOURCE / "tests/fixtures" / name).read_text())


def search(*results):
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "entries": [
                                    {
                                        "content": {
                                            "itemContent": {"tweet_results": {"result": result}}
                                        }
                                    }
                                    for result in results
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }


def tweet(identifier="500", **legacy):
    return {
        "__typename": "Tweet",
        "rest_id": identifier,
        "core": {"user_results": {"result": {"core": {"screen_name": "founder"}, "legacy": {}}}},
        "legacy": {
            "full_text": "We are researching a CRM.",
            "created_at": "Sat Mar 08 13:00:00 +0000 2026",
            **legacy,
        },
    }


def test_runtime_code_and_license_are_unchanged_pinned_source_without_auth_or_client():
    subset = ROOT / "src/skriller/_vendor/twitter"
    manifest = json.loads((subset / "PROVENANCE.json").read_text())
    assert manifest["commit"] == "7c634e0d396b1e7af9f63315b414925fe4f29ae7"
    for name, record in manifest["files"].items():
        raw = (subset / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert raw == (SOURCE / record["source"]).read_bytes()
    assert (subset / "LICENSE").read_bytes() == (SOURCE / "LICENSE").read_bytes()
    assert not any((subset / name).exists() for name in ["auth.py", "client.py", "cli.py"])
    acquired = json.loads((SOURCE / "PROVENANCE.json").read_text())
    for record in acquired["files"]:
        assert (
            hashlib.sha256((SOURCE / record["path"]).read_bytes()).hexdigest() == record["sha256"]
        )


@pytest.mark.parametrize(
    "name,path,ids,cursor",
    [
        (
            "home_timeline.json",
            ("data", "home", "home_timeline_urt", "instructions"),
            ["1", "20"],
            "cursor-bottom-1",
        ),
        (
            "search_timeline.json",
            ("data", "search_by_raw_query", "search_timeline", "timeline", "instructions"),
            ["500"],
            "search-cursor",
        ),
        (
            "tweet_detail.json",
            ("data", "threaded_conversation_with_injections_v2", "instructions"),
            ["100", "101"],
            "conversation-cursor",
        ),
        (
            "list_timeline.json",
            ("data", "list", "tweets_timeline", "timeline", "instructions"),
            ["700"],
            "list-cursor",
        ),
    ],
)
def test_adapted_upstream_parser_fixtures(name, path, ids, cursor):
    # Adapted from upstream test_parser_fixtures; deliberately omit its HTTP
    # client import and execute the unchanged pure parser in the local namespace.
    tweets, next_cursor = parse_timeline_response(
        fixture(name), lambda data: _deep_get(data, *path)
    )
    assert [item.id for item in tweets] == ids and next_cursor == cursor


def test_source_search_fixture_preserves_text_time_and_unknown_identity():
    request = XSearch(query="CRM", limit=10)
    assert request.backend_arguments() == {"query": "CRM", "count": 10, "product": "Latest"}
    page = parse_search_timeline(fixture("search_timeline.json"), request, observed_at=NOW)
    assert page.status == "parsed_not_live_verified" and page.has_more
    assert page.posts[0].source_url == "https://x.com/searcher/status/500"
    assert page.posts[0].excerpt == "search result with video"
    assert page.posts[0].author_identity == "unknown"
    assert page.posts[0].published_at == datetime(2026, 3, 8, 13, tzinfo=UTC)
    assert "metrics" not in page.posts[0].model_dump()


def test_duplicates_caps_unknown_dates_and_truncation_stay_explicit():
    page = parse_search_timeline(
        search(
            tweet("1", full_text="x" * 5000, created_at="future or unknown"), tweet("1"), tweet("2")
        ),
        XSearch(query="CRM", limit=1),
        observed_at=NOW,
    )
    assert len(page.posts) == 1 and page.posts[0].truncated
    assert page.posts[0].published_at is None
    assert page.duplicate_count == 1 and page.omitted_count == 1


def test_invalid_or_missing_result_is_counted_without_promoting_default_author():
    malformed = tweet()
    malformed["core"] = {}
    page = parse_search_timeline(
        search(malformed, {"__typename": "TweetTombstone"}), XSearch(query="CRM"), observed_at=NOW
    )
    assert page.posts == () and page.rejected_count == 2


@pytest.mark.parametrize("payload", [{}, {"errors": [{"message": "denied"}]}, {"data": []}])
def test_error_or_wrong_shape_is_not_successful_empty_search(payload):
    with pytest.raises(ValueError):
        parse_search_timeline(payload, XSearch(query="CRM"), observed_at=NOW)


def test_bounded_structure_and_private_subscriber_result_fail_closed():
    private = {
        "__typename": "TweetWithVisibilityResults",
        "tweet": tweet(),
        "tweetInterstitial": {"text": "Subscriber only"},
    }
    page = parse_search_timeline(search(private), XSearch(query="CRM"), observed_at=NOW)
    assert page.posts == () and page.rejected_count == 1
    nested = {}
    payload = nested
    for _ in range(40):
        nested["nested"] = {}
        nested = nested["nested"]
    with pytest.raises(ValueError):
        parse_search_timeline(payload, XSearch(query="CRM"), observed_at=NOW)


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": " "},
        {"query": "CRM", "limit": True},
        {"query": "CRM", "limit": 26},
        {"query": "CRM", "mode": "People"},
        {"query": "CRM", "command": "post"},
    ],
)
def test_unsupported_operations_and_unbounded_arguments_are_rejected(arguments):
    with pytest.raises(ValidationError):
        XSearch(**arguments)


def test_parsing_and_configured_account_do_not_enable_unverified_source():
    from uuid import UUID

    registry = ConnectorRegistry(UUID(str(uuid4())), connected_sources=frozenset({"x"}))
    parse_search_timeline(search(tweet()), XSearch(query="CRM"), observed_at=NOW)
    assert registry.capability("x", "read").operational_status != "available"
    assert registry.select("read", source="x").code == "unsupported_operation"


def test_official_rest_search_requires_matching_author_expansion_and_truncates_results():
    request = XSearch(query="CRM", limit=1)
    payload = {
        "data": [
            {
                "id": "1",
                "author_id": "u1",
                "text": "Building a CRM",
                "created_at": "2026-10-15T10:00:00Z",
            },
            {"id": "2", "author_id": "u2", "text": "Second post"},
            {"id": "3", "author_id": "missing", "text": "Unattributed"},
        ],
        "includes": {
            "users": [{"id": "u1", "username": "founder"}, {"id": "u2", "username": "second"}]
        },
        "meta": {"result_count": 3, "next_token": "next"},
    }
    page = parse_rest_search(payload, request, observed_at=NOW)
    assert page.posts[0].author_handle == "founder"
    assert page.posts[0].source_url == "https://x.com/founder/status/1"
    assert page.posts[0].published_at == datetime(2026, 10, 15, 10, tzinfo=UTC)
    assert page.omitted_count == 1 and page.rejected_count == 1 and page.has_more


def test_official_rest_parser_rejects_errors_and_oversized_payload():
    with pytest.raises(ValueError):
        parse_rest_search({"errors": [{"title": "denied"}]}, XSearch(query="CRM"), observed_at=NOW)
    with pytest.raises(ValueError):
        parse_rest_search(
            {"data": [{"text": "x" * 1_100_000}]}, XSearch(query="CRM"), observed_at=NOW
        )
