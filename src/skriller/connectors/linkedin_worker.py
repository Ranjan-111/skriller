"""Bounded LinkedIn search and resource reads using acquired page capture code."""

import asyncio
import json
import logging
import os
import re
import sys
from urllib.parse import urlsplit

from skriller.connectors.linkedin_discovery import LinkedInSearch
from skriller.connectors.linkedin_read import LinkedInRead


def session_cookie(path="/run/skriller-credentials.json", *, runner="linkedin_search"):
    if os.environ.get("SKRILLER_LINKEDIN_WORKER") != "isolated" or not os.path.isfile(
        "/.dockerenv"
    ):
        raise ValueError("LinkedIn search requires an isolated worker")
    with open(path, encoding="utf-8") as stream:
        raw = stream.read(65537)
    data = json.loads(raw) if len(raw) <= 65536 else None
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("runner") != runner
        or not isinstance(data.get("environment"), dict)
        or set(data["environment"]) != {"LINKEDIN_SESSION_COOKIE"}
    ):
        raise ValueError("Session unavailable")
    cookie = data["environment"]["LINKEDIN_SESSION_COOKIE"]
    if not isinstance(cookie, str) or not re.fullmatch(r"[^\s;\x00-\x1f\x7f]{1,16384}", cookie):
        raise ValueError("Session unavailable")
    return cookie


def allowed_request(url, method, resource_type):
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and port in {None, 443}
        and method in {"GET", "HEAD"}
        and resource_type in {"document", "script", "stylesheet", "xhr", "fetch"}
        and (host == "www.linkedin.com" or host == "static.licdn.com")
        and not parts.path.startswith(("/login", "/checkpoint", "/uas/", "/challenge"))
    )


class RequestBudget:
    def __init__(self, target):
        self.target = target
        self.count = 0
        self.documents = 0
        self.stopped = False
        self.blocked_navigation = False

    def allow(self, url, method, resource_type):
        self.count += 1
        if self.count > 80:
            self.stopped = True
        if resource_type == "document":
            self.documents += 1
            if url != self.target or self.documents > 1:
                self.stopped = True
                self.blocked_navigation = urlsplit(url).path.startswith(
                    ("/login", "/checkpoint", "/uas/", "/challenge")
                )
        return not self.stopped and allowed_request(url, method, resource_type)


async def capture_search(page, request):
    # These are the unchanged acquired extraction/capture modules, not a new DOM scraper.
    from linkedin_mcp_server.linkedin.capture import (
        CaptureMode,
        CapturePlan,
        SectionCapture,
        _PermalinkResponseListener,
    )
    from linkedin_mcp_server.linkedin.content import PageContentReader
    from linkedin_mcp_server.linkedin.contracts import RATE_LIMITED_SECTION_TEXT
    from linkedin_mcp_server.linkedin.navigation import PageNavigator
    from linkedin_mcp_server.linkedin.session import PageSession

    session = PageSession(page)
    capture = SectionCapture(session, PageNavigator(session), PageContentReader(session))
    listener = _PermalinkResponseListener(page) if request.operation == "search_posts" else None
    mode = CaptureMode.SEARCH_RESULTS
    if listener:
        mode |= CaptureMode.POST_PERMALINKS
        listener.install()
    try:
        # Use the upstream single-attempt primitive; do not retry a rate-limit barrier.
        result = await capture._capture_once(
            request.search_url(),
            "search_results",
            CapturePlan(mode, 5 if listener else 1),
            listener,
        )
        if result.text == RATE_LIMITED_SECTION_TEXT:
            raise ValueError("Source is rate limited")
        return {
            "url": page.url,
            "sections": {"search_results": result.text},
            "references": {"search_results": result.references or []},
            "section_errors": {"search_results": result.error} if result.error else {},
        }
    finally:
        if listener:
            listener.remove()
            await listener.drain()


async def capture_read(page, request):
    # Reuse the acquired capture once, without contact overlays, retries or link-following.
    from linkedin_mcp_server.core.exceptions import (
        AccountRestrictedError,
        AuthenticationError,
        ProfileNotFoundError,
        RateLimitError,
    )
    from linkedin_mcp_server.linkedin.capture import CapturePlan, SectionCapture
    from linkedin_mcp_server.linkedin.content import PageContentReader
    from linkedin_mcp_server.linkedin.contracts import RATE_LIMITED_SECTION_TEXT
    from linkedin_mcp_server.linkedin.navigation import PageNavigator
    from linkedin_mcp_server.linkedin.session import PageSession

    session = PageSession(page)
    capture = SectionCapture(session, PageNavigator(session), PageContentReader(session))
    try:
        result = await capture._capture_once(
            request.target_url(), request.section(), CapturePlan(max_scrolls=1)
        )
    except AuthenticationError:
        return {"_skriller_error": "auth_expired"}
    except AccountRestrictedError:
        return {"_skriller_error": "access_denied"}
    except RateLimitError:
        return {"_skriller_error": "rate_limited"}
    except ProfileNotFoundError:
        return {"_skriller_error": "not_found"}
    if result.text == RATE_LIMITED_SECTION_TEXT:
        return {"_skriller_error": "rate_limited"}
    return {
        "url": page.url,
        "sections": {request.section(): result.text},
        "section_errors": {request.section(): result.error} if result.error else {},
    }


async def search(request, cookie):
    from patchright.async_api import async_playwright

    async with async_playwright() as driver:
        browser = await driver.chromium.launch(
            headless=True,
            proxy={"server": "http://172.29.0.2:8080"},
            args=["--disable-dev-shm-usage"],
        )
        try:
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            await context.add_cookies(
                [
                    {
                        "name": "li_at",
                        "value": cookie,
                        "domain": ".linkedin.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                    }
                ]
            )
            budget = RequestBudget(
                request.target_url() if isinstance(request, LinkedInRead) else request.search_url()
            )

            async def route_request(route):
                item = route.request
                if not budget.allow(item.url, item.method, item.resource_type):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_request)

            async def block_socket(socket):
                await socket.close()

            await context.route_web_socket("**/*", block_socket)
            page = await context.new_page()
            page.set_default_timeout(8000)
            try:
                payload = await asyncio.wait_for(
                    capture_read(page, request)
                    if isinstance(request, LinkedInRead)
                    else capture_search(page, request),
                    timeout=35,
                )
            except Exception:
                if isinstance(request, LinkedInRead) and budget.blocked_navigation:
                    return {"_skriller_error": "access_denied"}
                raise
            if budget.stopped:
                if isinstance(request, LinkedInRead):
                    return {
                        "_skriller_error": "access_denied"
                        if budget.blocked_navigation
                        else "source_unavailable"
                    }
                raise ValueError("Source request or navigation budget exhausted")
            return payload
        finally:
            await browser.close()


def main(argv=None):
    logging.disable(logging.CRITICAL)
    try:
        args = sys.argv[1:] if argv is None else argv
        if len(args) != 1 or len(args[0].encode()) > 8192:
            raise ValueError("One bounded search request required")
        read = json.loads(args[0]).get("operation") in {"read_profile", "read_company", "read_post"}
        request = (
            LinkedInRead.model_validate_json(args[0])
            if read
            else LinkedInSearch.model_validate_json(args[0])
        )
        cookie = session_cookie(runner="linkedin_resource_read" if read else "linkedin_search")
        payload = asyncio.run(search(request, cookie))
        serialized = json.dumps(payload, allow_nan=False)
        if len(serialized.encode()) > 1_048_576:
            raise ValueError("Search output exceeds bounds")
        sys.stdout.write(serialized)
        return 0
    except Exception:  # noqa: BLE001 - never serialize cookies/page/SDK errors
        sys.stderr.write("LinkedIn search unavailable\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
