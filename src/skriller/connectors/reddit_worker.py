"""One bounded Reddit OAuth search read, launched only in the guarded worker."""

from __future__ import annotations

import json
import os
import re
import sys
from math import ceil
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from skriller._vendor.reddit.read import ReadRequest
from skriller._vendor.reddit.search import SearchRequest
from skriller._vendor.retry_after import parse_retry_after
from skriller.connectors.reddit_request import RedditRead, RedditSearch

MAX_RESPONSE_BYTES = 1_048_576
API_URL = "https://oauth.reddit.com"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _access_token(path="/run/skriller-credentials.json", *, runner="reddit_oauth_search"):
    if os.environ.get("SKRILLER_REDDIT_WORKER") != "isolated" or not os.path.isfile("/.dockerenv"):
        raise RuntimeError("Reddit reads require an isolated worker")
    with open(path, encoding="utf-8") as stream:
        raw = stream.read(65537)
    credentials = json.loads(raw) if len(raw) <= 65536 else None
    if (
        not isinstance(credentials, dict)
        or credentials.get("schema_version") != 1
        or credentials.get("runner") != runner
        or not isinstance(credentials.get("environment"), dict)
        or set(credentials["environment"]) != {"REDDIT_ACCESS_TOKEN"}
    ):
        raise ValueError("OAuth credentials are unavailable")
    token = credentials["environment"]["REDDIT_ACCESS_TOKEN"]
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 16384
        or re.search(r"[\r\n\x00]", token)
    ):
        raise ValueError("OAuth credentials are unavailable")
    return token


def fetch_search(request: RedditSearch | RedditRead, token: str, *, opener_factory=build_opener):
    """Perform exactly one fixed-host request; redirects, retries and fallback are disabled."""
    path, parameters = cast(
        tuple[str, dict],
        (
            ReadRequest().get_post_comments(**request.backend_arguments())
            if isinstance(request, RedditRead)
            else SearchRequest().search(**request.backend_arguments())
        ),
    )
    url = API_URL + path + "?" + urlencode(parameters)
    opener = opener_factory(ProxyHandler({"https": "http://172.29.0.2:8080"}), NoRedirect())
    response = opener.open(
        Request(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "User-Agent": request.user_agent,
            },
            method="GET",
        ),
        timeout=8,
    )
    try:
        if response.geturl() != url or response.status != 200:
            raise ValueError("Reddit API response was not successful")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    finally:
        response.close()
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Reddit API response exceeds bounds")
    payload = json.loads(body)
    if not isinstance(payload, list if isinstance(request, RedditRead) else dict):
        raise TypeError("Reddit API response has an invalid shape")
    return payload


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1:
            raise ValueError("One serialized search request is required")
        if len(args[0].encode()) > 8192:
            raise ValueError("Request exceeds bound")
        raw = json.loads(args[0])
        request = (
            RedditRead.model_validate_json(args[0])
            if isinstance(raw, dict) and raw.get("operation") == "read_post"
            else RedditSearch.model_validate_json(args[0])
        )
        runner = "reddit_oauth_read" if isinstance(request, RedditRead) else "reddit_oauth_search"
        payload = fetch_search(request, _access_token(runner=runner))
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
    except (URLError, TimeoutError, OSError, ValueError, TypeError, RecursionError):
        sys.stderr.write("Reddit API read unavailable\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
