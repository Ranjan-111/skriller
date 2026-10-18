"""Read-resource boundaries against copied Reddit parser/request construction."""

import ast
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skriller.connectors.reddit_read import parse_thread
from skriller.connectors.reddit_request import RedditRead
from skriller.security.runner import reviewed_command

NOW = datetime(2026, 10, 17, tzinfo=UTC)
REQUEST = RedditRead(post_id="abc123", subreddit="startups")


def thread():
    post = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "title": "Problem with deployment",
                        "subreddit": "startups",
                        "author": "source_handle",
                        "selftext": "Our deployment takes hours.",
                        "permalink": "/r/startups/comments/abc123/deployment/",
                        "created_utc": 1700000000,
                    },
                }
            ]
        },
    }

    def comment(identifier, parent, body):
        return {
            "kind": "t1",
            "data": {
                "id": identifier,
                "name": "t1_" + identifier,
                "parent_id": parent,
                "link_id": "t3_abc123",
                "body": body,
                "author": "anonymous_handle",
                "created_utc": 1700000100,
                "replies": "",
            },
        }

    parent = comment("com123", "t3_abc123", "The queue is slow.")
    parent["data"]["replies"] = {
        "kind": "Listing",
        "data": {
            "children": [
                comment("com456", "t1_com123", "[deleted]"),
                {"kind": "more", "data": {"parent_id": "t1_com123", "children": ["more123"]}},
            ]
        },
    }
    return [post, {"kind": "Listing", "data": {"children": [parent]}}]


def test_read_method_is_copied_unchanged_and_command_is_read_only():
    root = Path(__file__).resolve().parents[2]

    def method(path):
        return next(
            n
            for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.FunctionDef) and n.name == "get_post_comments"
        )

    assert ast.dump(method(root / "third_party/external/reddit/rdt_cli/client.py")) == ast.dump(
        method(root / "src/skriller/_vendor/reddit/read.py")
    )
    assert reviewed_command("reddit_oauth_read", REQUEST.model_dump_json())[:3] == [
        "python",
        "-m",
        "skriller.connectors.reddit_worker",
    ]
    with pytest.raises(ValueError):
        reviewed_command("reddit_oauth_search", REQUEST.model_dump_json())
    with pytest.raises(ValueError):
        RedditRead(post_id="../../write", subreddit="startups")


def test_nested_deletion_and_source_dates_are_preserved_without_identity_or_intent():
    page = parse_thread(thread(), REQUEST, observed_at=NOW)
    assert page.post.native_id == "t3_abc123"
    assert page.comments[1].parent_id == page.comments[0].native_id
    assert page.comments[1].text == "" and page.comments[1].content_unavailable
    assert page.comments[0].published_at == datetime.fromtimestamp(1700000100, UTC)
    assert page.comments[0].source_url.endswith("/deployment/com123/")
    assert page.unexpanded_nodes == 1 and not page.coverage_complete
    assert page.subject_identity == "unknown" and page.buying_intent == "not_inferred"
    assert "email" not in page.model_dump() and "company" not in page.model_dump()


@pytest.mark.parametrize("change", ["post", "parent", "link", "duplicate", "shape", "depth"])
def test_cross_resource_and_unbounded_trees_cannot_be_accepted(change):
    payload = thread()
    first = payload[1]["data"]["children"][0]
    if change == "post":
        payload[0]["data"]["children"][0]["data"]["id"] = "other123"
    elif change == "parent":
        first["data"]["parent_id"] = "t3_other123"
    elif change == "link":
        first["data"]["link_id"] = "t3_other123"
    elif change == "duplicate":
        payload[1]["data"]["children"].append(deepcopy(first))
    elif change == "shape":
        first["data"]["replies"] = {"kind": "Listing", "data": {"children": "bad"}}
    else:
        payload[1]["data"]["children"] *= 101
    with pytest.raises(ValueError):
        parse_thread(payload, REQUEST, observed_at=NOW)


def test_limit_and_unknown_date_are_explicit():
    payload = thread()
    payload[1]["data"]["children"][0]["data"]["created_utc"] = NOW.timestamp() + 100
    result = parse_thread(payload, REQUEST.model_copy(update={"limit": 1}), observed_at=NOW)
    assert len(result.comments) == 1 and result.comments[0].published_at is None
    assert result.omitted_comments == 1 and not result.coverage_complete
