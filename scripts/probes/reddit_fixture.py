"""Actual installed Reddit module with synthetic data and network disabled."""

import contextlib
import io
import json
import os
from pathlib import Path

from skriller.connectors import reddit_worker
from skriller.connectors.reddit_request import RedditCursor, RedditRead, RedditSearch

assert os.getuid() != 0 and Path("/.dockerenv").is_file()
assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
path = Path("/tmp/reddit-fixture-credentials.json")
path.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "runner": "reddit_oauth_search",
            "environment": {"REDDIT_ACCESS_TOKEN": "SYNTHETIC_REDDIT_TOKEN_ONLY"},
        }
    )
)
token = reddit_worker._access_token(str(path))
path.unlink()
payload = {
    "kind": "Listing",
    "data": {
        "after": None,
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "abc123",
                    "title": "Synthetic founder hiring",
                    "permalink": "/r/startups/comments/abc123/fixture/",
                    "subreddit": "startups",
                    "selftext": "Hiring engineers",
                    "author": "fixture",
                },
            }
        ],
    },
}
requests = []


class Reply:
    status = 200

    def __init__(self, url):
        self.url = url

    def geturl(self):
        return self.url

    def read(self, limit):
        return json.dumps(payload).encode()[:limit]

    def close(self):
        pass


class Opener:
    def open(self, request, timeout):
        assert request.full_url.startswith(
            (
                "https://oauth.reddit.com/search.json?",
                "https://oauth.reddit.com/r/startups/comments/abc123.json?",
            )
        )
        assert request.get_method() == "GET" and timeout == 8
        assert request.get_header("Authorization") == "Bearer SYNTHETIC_REDDIT_TOKEN_ONLY"
        assert request.get_header("Cookie") is None
        requests.append(request)
        return Reply(request.full_url)


original = reddit_worker.fetch_search
reddit_worker.fetch_search = lambda request, access: original(
    request, access, opener_factory=lambda *args: Opener()
)
reddit_worker._access_token = lambda **kwargs: token
output = io.StringIO()
with contextlib.redirect_stdout(output):
    assert reddit_worker.main([RedditSearch(query="synthetic founder").model_dump_json()]) == 0
assert json.loads(output.getvalue()) == payload and len(requests) == 1
output.seek(0)
output.truncate()
with contextlib.redirect_stdout(output):
    assert (
        reddit_worker.main(
            [
                RedditSearch(
                    query="synthetic founder", cursor=RedditCursor(after="t3_fixture")
                ).model_dump_json()
            ]
        )
        == 0
    )
assert json.loads(output.getvalue()) == payload and len(requests) == 2
assert "after=t3_fixture" in requests[1].full_url
assert "SYNTHETIC_REDDIT_TOKEN" not in output.getvalue()
payload = [
    payload,
    {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "id": "com123",
                        "name": "t1_com123",
                        "parent_id": "t3_abc123",
                        "link_id": "t3_abc123",
                        "author": "anonymous",
                        "body": "[deleted]",
                        "replies": "",
                        "created_utc": 1700000000,
                    },
                }
            ]
        },
    },
]
output.seek(0)
output.truncate()
read = RedditRead(post_id="abc123", subreddit="startups")
with contextlib.redirect_stdout(output):
    assert reddit_worker.main([read.model_dump_json()]) == 0
thread = json.loads(output.getvalue())
assert thread[1]["data"]["children"][0]["data"]["body"] == "[deleted]"
assert len(requests) == 3
print(
    json.dumps(
        {
            "actual_worker_pipeline": True,
            "post_citation_verified": True,
            "typed_cursor_read_verified": True,
            "thread_read_verified": True,
            "network": "none",
            "source_live_verified": False,
        }
    )
)
