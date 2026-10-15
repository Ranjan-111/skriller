"""Opt-in rdt-cli search/read probe using an explicit cookie file only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_reach.utils.paths import read_small_text_no_follow

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/external/reddit"
COMMIT = "5e4fb3720d5c174e976cd425ccc3b879d52cac66"


def verify_source() -> dict:
    manifest = json.loads((SOURCE / "SOURCE_MANIFEST.json").read_text())
    if manifest["commit"] != COMMIT:
        raise ValueError("Backend commit differs from reviewed pin")
    for relative, digest in manifest["files"].items():
        path = SOURCE / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Backend source differs from acquired snapshot")
    return {
        "repository": manifest["repository"],
        "commit": COMMIT,
        "license": manifest["license_declaration"],
        "license_files": manifest["license_files"],
    }


def backend():
    # Import the actual acquired source; never call optional_auth/load_credential
    # because they can refresh cookies by reading a user's browser.
    sys.path.insert(0, str(SOURCE))
    import rdt_cli.client as module
    from rdt_cli.auth import Credential
    from rdt_cli.client import RedditClient
    from rdt_cli.parser import parse_listing, parse_post_detail

    if not Path(module.__file__).resolve().is_relative_to(SOURCE):
        raise ValueError("Unexpected Reddit backend import location")
    return Credential, RedditClient, parse_listing, parse_post_detail


def probe(
    *,
    live: bool = False,
    cookie_file: Path | None = None,
    operation: str = "search",
    query: str = "fintech",
    subreddit: str | None = None,
    time_filter: str = "all",
    sort: str = "relevance",
    after: str | None = None,
    post_id: str | None = None,
    configured: bool = False,
    bridge_available: bool = False,
    backend_loader=backend,
) -> dict:
    report: dict[str, Any] = {
        "platform": "reddit",
        "operation": operation,
        "source": verify_source(),
        "status": "unvalidated" if configured or bridge_available else "skipped",
        "configured": configured,
        "bridge_available": bridge_available,
        "validated": False,
        "elapsed_ms": 0,
        "reason": "No opt-in controlled live operation executed",
    }
    if operation not in {"search", "read"}:
        raise ValueError("Probe permits only search/read")
    if operation == "read" and (not post_id or not re.fullmatch(r"[a-z0-9]{1,12}", post_id)):
        raise ValueError("Read requires a Reddit post ID")
    if not live or cookie_file is None:
        if live:
            report["reason"] = (
                "Explicit cookie file required; no anonymous or browser extraction fallback"
            )
        return report
    started = time.monotonic()
    try:
        search = None
        if operation == "search":
            from skriller.connectors.reddit_discovery import RedditCursor, RedditSearch

            search = RedditSearch.model_validate(
                {
                    "query": query,
                    "subreddit": subreddit,
                    "time_filter": time_filter,
                    "sort": sort,
                    "limit": 5,
                    "cursor": RedditCursor(after=after) if after is not None else None,
                }
            )
        cookie_file = Path(cookie_file)
        raw = read_small_text_no_follow(cookie_file, max_bytes=64 * 1024)
        if raw is None:
            raise ValueError("Explicit cookie file missing")
        if os.name != "nt" and cookie_file.stat().st_mode & 0o077:
            raise ValueError("Explicit cookie file must not be group/world accessible")
        payload = json.loads(raw)
        cookies = payload.get("cookies") if isinstance(payload, dict) else None
        if (
            not isinstance(cookies, dict)
            or not isinstance(cookies.get("reddit_session"), str)
            or not cookies["reddit_session"]
        ):
            raise ValueError("No explicit Reddit session cookie")
        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in cookies.items()
        ):
            raise ValueError("Unexpected cookie schema")
        Credential, Client, _parse_listing, parse_detail = backend_loader()
        credential = Credential(cookies=cookies, source="explicit-probe-file")
        with Client(credential, timeout=15, request_delay=1, max_retries=0) as client:
            if operation == "search":
                from skriller.connectors.reddit_discovery import parse_search_listing

                if search is None:
                    raise ValueError("Search request is unavailable")
                data = client.search(**search.backend_arguments())
                if not isinstance(data, dict) or not isinstance(
                    data.get("data", {}).get("children"), list
                ):
                    raise ValueError("Unexpected Reddit search schema")
                listing = parse_search_listing(data, search, observed_at=datetime.now(UTC))
                children = data["data"]["children"]
                report.update(
                    count=len(listing.posts),
                    fields=sorted(children[0].get("data", {})) if children else [],
                    pagination_cursor_present=listing.next_cursor is not None,
                    rejected_references=listing.rejected_count,
                    duplicate_references=listing.duplicate_count,
                    unknown_publication_dates=sum(
                        post.published_at is None for post in listing.posts
                    ),
                )
            else:
                data = client.get_post_comments(post_id=post_id, limit=5)
                if not isinstance(data, list) or len(data) < 2:
                    raise ValueError("Unexpected Reddit thread schema")
                detail = parse_detail(data)
                if not detail.post.id:
                    raise ValueError("No thread extracted")
                report.update(
                    count=1,
                    fields=sorted(detail.post.to_dict()),
                    comments_returned=len(detail.comments),
                    pagination_cursor_present=False,
                )
        report.update(
            status="verified",
            validated=True,
            reason="Controlled operation returned expected schema",
        )
        if operation == "search" and listing.rejected_count:
            report.update(
                status="partial",
                validated=False,
                reason="Some search results failed requested source constraints",
            )
    except Exception as exc:  # noqa: BLE001 — external operation boundary must emit a failure report
        # Never include exception payloads: they may include raw session cookies.
        report.update(status="failed", reason=f"{type(exc).__name__}: controlled operation failed")
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--configured", action="store_true")
    parser.add_argument("--bridge-available", action="store_true")
    parser.add_argument("--operation", choices=["search", "read"], default="search")
    parser.add_argument("--query", default="fintech")
    parser.add_argument("--subreddit")
    parser.add_argument(
        "--time-filter", default="all", choices=["all", "hour", "day", "week", "month", "year"]
    )
    parser.add_argument(
        "--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"]
    )
    parser.add_argument("--after")
    parser.add_argument("--post-id")
    print(json.dumps(probe(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
