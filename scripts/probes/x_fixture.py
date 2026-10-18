"""Installed X worker probe with synthetic credentials and a network-none transport."""

import contextlib
import importlib.util
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from skriller.connectors import x_worker
from skriller.connectors.x_discovery import XSearch, parse_rest_search

assert os.getuid() != 0 and Path("/.dockerenv").is_file()
assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
assert importlib.util.find_spec("playwright") is None
assert importlib.util.find_spec("scrapling") is None
credential_file = Path("/tmp/x-fixture-credentials.json")
credential_file.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "runner": "x_read",
            "environment": {"X_ACCESS_TOKEN": "SYNTHETIC_X_TOKEN_ONLY"},
        }
    )
)
token = x_worker._access_token(str(credential_file))
credential_file.unlink()
requests = []
payload = {
    "data": [{"id": "123456", "author_id": "42", "text": "Synthetic founder hiring engineers"}],
    "includes": {"users": [{"id": "42", "username": "fixture"}]},
    "meta": {"result_count": 1},
}


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
        assert request.full_url.startswith("https://api.x.com/2/tweets/search/recent?")
        assert request.get_method() == "GET" and timeout == 8
        assert request.get_header("Authorization") == "Bearer SYNTHETIC_X_TOKEN_ONLY"
        requests.append(request.full_url)
        return Reply(request.full_url)


def opener_factory(*handlers):
    assert any(isinstance(handler, x_worker.NoRedirect) for handler in handlers)
    return Opener()


original = x_worker.fetch_recent
x_worker.fetch_recent = lambda request, access: original(
    request, access, opener_factory=opener_factory
)
x_worker._access_token = lambda: token
request = XSearch(query="synthetic hiring", limit=3)
output = io.StringIO()
with contextlib.redirect_stdout(output):
    assert x_worker.main([request.model_dump_json()]) == 0
page = parse_rest_search(json.loads(output.getvalue()), request, observed_at=datetime.now(UTC))
assert len(requests) == 1 and page.posts[0].source_url == "https://x.com/fixture/status/123456"
assert page.posts[0].excerpt == "Synthetic founder hiring engineers"
assert "SYNTHETIC_X_TOKEN" not in output.getvalue()
print(
    json.dumps(
        {
            "actual_worker_pipeline": True,
            "post_citation_verified": True,
            "network": "none",
            "source_live_verified": False,
            "browser_installed": False,
        }
    )
)
