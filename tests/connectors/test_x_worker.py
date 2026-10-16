import json
from urllib.parse import parse_qs, urlsplit

import pytest

from skriller.connectors.x_discovery import XSearch
from skriller.connectors.x_worker import NoRedirect, fetch_recent
from skriller.security.runner import reviewed_command


class Response:
    status = 200

    def __init__(self, body):
        self.body = body
        self.closed = False

    def geturl(self):
        return self.url

    def read(self, limit):
        assert limit == 1_048_577
        return self.body

    def close(self):
        self.closed = True


def test_x_worker_uses_only_fixed_official_search_get_and_oauth_header():
    seen = {}
    response = Response(b'{"data":[],"meta":{"result_count":0}}')

    class Opener:
        def open(self, request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            response.url = request.full_url
            return response

    def opener_factory(*handlers):
        seen["handlers"] = handlers
        return Opener()

    result = fetch_recent(
        XSearch(query="CRM founder", limit=3), "synthetic-token", opener_factory=opener_factory
    )
    assert result["meta"]["result_count"] == 0
    req = seen["request"]
    assert urlsplit(req.full_url).scheme == "https"
    assert urlsplit(req.full_url).netloc == "api.x.com"
    assert urlsplit(req.full_url).path == "/2/tweets/search/recent"
    query = parse_qs(urlsplit(req.full_url).query)
    assert query["query"] == ["CRM founder"] and query["max_results"] == ["10"]
    assert req.method == "GET" and req.get_header("Authorization") == "Bearer synthetic-token"
    assert seen["timeout"] == 8 and response.closed
    assert any(isinstance(handler, NoRedirect) for handler in seen["handlers"])


def test_reviewed_x_operation_rejects_arbitrary_targets_and_bounds_search():
    command = reviewed_command("x_read", XSearch(query="CRM").model_dump_json())
    assert command[:4] == [
        "python",
        "-m",
        "skriller.connectors.x_worker",
        '{"query":"CRM","limit":10,"mode":"Latest"}',
    ]
    for target in ["https://example.com", json.dumps({"query": "x", "command": "curl"})]:
        with pytest.raises(ValueError):
            reviewed_command("x_read", target)


def test_x_redirects_are_not_followed():
    assert (
        NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example") is None
    )
