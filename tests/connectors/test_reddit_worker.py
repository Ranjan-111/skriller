"""Native request boundary and copied search construction, without source traffic."""

import ast
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from skriller.connectors.reddit_request import RedditCursor, RedditSearch
from skriller.connectors.reddit_worker import NoRedirect, fetch_search
from skriller.security.runner import reviewed_command


def test_copied_reddit_search_method_retains_acquired_backend_logic():
    root = Path(__file__).resolve().parents[2]

    def method(path):
        tree = ast.parse(path.read_text())
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "search"
        )

    original = method(root / "third_party/external/reddit/rdt_cli/client.py")
    copied = method(root / "src/skriller/_vendor/reddit/search.py")
    assert ast.dump(original) == ast.dump(copied)


@pytest.mark.parametrize("community", [None, "startups"])
def test_reddit_worker_uses_one_fixed_oauth_search_with_exact_filters(community):
    seen = []

    class Reply:
        status = 200

        def geturl(self):
            return seen[0].full_url

        def read(self, limit):
            assert limit == 1048577
            return b'{"kind":"Listing","data":{"children":[],"after":null}}'

        def close(self):
            pass

    class Opener:
        def open(self, request, timeout):
            assert timeout == 8
            seen.append(request)
            return Reply()

    def factory(*handlers):
        assert any(isinstance(handler, NoRedirect) for handler in handlers)
        return Opener()

    result = fetch_search(
        RedditSearch(
            query="founder",
            subreddit=community,
            sort="new",
            time_filter="month",
            limit=4,
            user_agent="web:skriller-fixture:v0.1 (by /u/fixture)",
        ),
        "synthetic-token",
        opener_factory=factory,
    )
    assert result["kind"] == "Listing" and len(seen) == 1
    request = seen[0]
    url = urlsplit(request.full_url)
    assert url.scheme == "https" and url.netloc == "oauth.reddit.com"
    assert url.path == ("/r/startups/search.json" if community else "/search.json")
    params = parse_qs(url.query)
    assert params == {
        "q": ["founder"],
        "sort": ["new"],
        "t": ["month"],
        "limit": ["4"],
        "restrict_sr": ["on" if community else "off"],
        "raw_json": ["1"],
    }
    assert (
        request.get_method() == "GET"
        and request.get_header("Authorization") == "Bearer synthetic-token"
    )
    assert request.get_header("Cookie") is None
    assert request.get_header("User-agent") == "web:skriller-fixture:v0.1 (by /u/fixture)"


def test_reddit_reviewed_operation_accepts_typed_source_cursor_and_rejects_urls_and_commands():
    command = reviewed_command(
        "reddit_oauth_search", RedditSearch(query="founder").model_dump_json()
    )
    assert command[:3] == ["python", "-m", "skriller.connectors.reddit_worker"]
    bound = RedditSearch(query="x", cursor=RedditCursor(after="t3_abc123"))
    assert json.loads(reviewed_command("reddit_oauth_search", bound.model_dump_json())[-1])[
        "cursor"
    ] == {"after": "t3_abc123"}
    for request in [
        "https://reddit.com",
        json.dumps({"query": "x", "command": "vote"}),
    ]:
        with pytest.raises(ValueError):
            reviewed_command("reddit_oauth_search", request)


def test_reddit_worker_rate_limit_stops_without_retry_or_private_error(monkeypatch, capsys):
    from email.message import Message
    from urllib.error import HTTPError

    from skriller.connectors import reddit_worker

    calls = []
    headers = Message()
    headers["Retry-After"] = "120"
    monkeypatch.setattr(reddit_worker, "_access_token", lambda **kwargs: "private-sentinel")

    def limited(request, token):
        calls.append(request)
        raise HTTPError(
            "https://oauth.reddit.com/search.json", 429, "private-sentinel", headers, None
        )

    monkeypatch.setattr(reddit_worker, "fetch_search", limited)
    assert reddit_worker.main([RedditSearch(query="fixture").model_dump_json()]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {"_skriller_error": "rate_limited", "retry_after_seconds": 120}
    assert len(calls) == 1 and "private-sentinel" not in output.out + output.err
