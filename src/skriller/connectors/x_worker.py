"""One bounded official X API v2 read, launched only in the guarded worker."""

from __future__ import annotations

import json
import os
import re
import sys
from math import ceil
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from skriller._vendor.retry_after import parse_retry_after
from skriller.connectors.x_discovery import XSearch

MAX_RESPONSE_BYTES = 1_048_576
API_URL = "https://api.x.com/2/tweets/search/recent"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _access_token(path="/run/skriller-credentials.json"):
    if os.environ.get("SKRILLER_X_WORKER") != "isolated" or not os.path.isfile("/.dockerenv"):
        raise RuntimeError("X reads require an isolated worker")
    with open(path, encoding="utf-8") as stream:
        credentials = json.load(stream)
    if (
        not isinstance(credentials, dict)
        or credentials.get("schema_version") != 1
        or credentials.get("runner") != "x_read"
        or not isinstance(credentials.get("environment"), dict)
        or set(credentials["environment"]) != {"X_ACCESS_TOKEN"}
    ):
        raise ValueError("OAuth credentials are unavailable")
    token = credentials["environment"]["X_ACCESS_TOKEN"]
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 16384
        or re.search(r"[\r\n\x00]", token)
    ):
        raise ValueError("OAuth credentials are unavailable")
    return token


def fetch_recent(request: XSearch, token: str, *, opener_factory=build_opener):
    """Perform exactly one fixed-host request; redirects, retries and fallback are disabled."""
    query = urlencode(
        {
            "query": request.query,
            "max_results": max(10, request.limit),
            "sort_order": "recency" if request.mode == "Latest" else "relevancy",
            "tweet.fields": "created_at,author_id,referenced_tweets",
            "expansions": "author_id",
            "user.fields": "username",
        }
    )
    url = API_URL + "?" + query
    opener = opener_factory(ProxyHandler({"https": "http://172.29.0.2:8080"}), NoRedirect())
    response = opener.open(
        Request(
            url,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            method="GET",
        ),
        timeout=8,
    )
    try:
        if response.geturl() != url or response.status != 200:
            raise ValueError("X API response was not successful")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    finally:
        response.close()
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("X API response exceeds bounds")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError("X API response has an invalid shape")
    return payload


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1:
            raise ValueError("One serialized search request is required")
        request = XSearch.model_validate_json(args[0])
        payload = fetch_recent(request, _access_token())
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), allow_nan=False))
        return 0
    except HTTPError as exc:
        # Avoid returning upstream messages or headers, which can contain private data.
        retry_after = None
        if exc.code == 429:
            parsed = parse_retry_after(dict(exc.headers.items()))
            retry_after = min(86400, max(0, ceil(parsed))) if parsed is not None else 60
        try:
            exc.close()
        except OSError:
            pass
        status_map = {
            401: "auth_expired",
            403: "access_denied",
            404: "not_found",
            429: "rate_limited",
        }
        sys.stdout.write(
            json.dumps(
                {
                    "_skriller_error": status_map.get(exc.code, "source_unavailable"),
                    "retry_after_seconds": retry_after,
                }
            )
        )
        return 0
    except (URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError):
        sys.stderr.write("X API read unavailable\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
