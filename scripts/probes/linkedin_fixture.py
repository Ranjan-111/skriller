"""Installed acquired LinkedIn capture on synthetic HTML, with Docker network none."""

import asyncio
import json

from patchright.async_api import async_playwright

from skriller.connectors.linkedin_discovery import LinkedInSearch, parse_search_response
from skriller.connectors.linkedin_read import LinkedInRead, parse_read_response
from skriller.connectors.linkedin_worker import capture_read, capture_search


def synthetic_route(target_url):
    async def route(item):
        if item.request.url == target_url:
            await item.fulfill(
                status=200,
                content_type="text/html",
                body="""<!doctype html><main>
                  <h1>Search results</h1><p>Controlled synthetic fixture content for acquisition verification.
                  No real account, user page, platform operation or network is being read.</p>
                  <a href="/in/synthetic/">Synthetic founder</a>
                  <a href="/feed/update/urn:li:activity:12345/">Synthetic post</a></main>""",
            )
        else:
            await item.abort()

    return route


async def probe():
    from datetime import UTC, datetime

    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            checked = []
            for operation in ("search_people", "search_posts"):
                request = LinkedInSearch(operation=operation, keywords="synthetic founder")
                context = await browser.new_context(service_workers="block")

                await context.route("**/*", synthetic_route(request.search_url()))
                page = await context.new_page()
                page.set_default_timeout(3000)
                payload = await asyncio.wait_for(capture_search(page, request), 20)
                result = parse_search_response(payload, request, observed_at=datetime.now(UTC))
                assert any(
                    item.url == "https://www.linkedin.com/in/synthetic/"
                    for item in result.references
                ), result
                assert "Controlled synthetic" in result.text
                checked.append(operation)
                await context.close()
            reads = []
            for operation, identifier in (
                ("read_profile", "synthetic"),
                ("read_company", "synthetic"),
                ("read_post", "12345"),
            ):
                request = LinkedInRead(operation=operation, resource_id=identifier)
                context = await browser.new_context(service_workers="block")
                await context.route("**/*", synthetic_route(request.target_url()))
                page = await context.new_page()
                page.set_default_timeout(3000)
                payload = await asyncio.wait_for(capture_read(page, request), 10)
                result = parse_read_response(payload, request, observed_at=datetime.now(UTC))
                assert (
                    "Controlled synthetic" in result.text
                    and result.contact_details == "unavailable"
                )
                reads.append(operation)
                await context.close()
            from linkedin_mcp_server.core.exceptions import (
                AccountRestrictedError,
                AuthenticationError,
                ProfileNotFoundError,
                RateLimitError,
            )
            from linkedin_mcp_server.linkedin.capture import SectionCapture

            original_capture = SectionCapture._capture_once
            try:
                for error_type, code in (
                    (AuthenticationError, "auth_expired"),
                    (AccountRestrictedError, "access_denied"),
                    (RateLimitError, "rate_limited"),
                    (ProfileNotFoundError, "not_found"),
                ):

                    async def denied(*args, _error_type=error_type, **kwargs):
                        raise _error_type("PRIVATE SYNTHETIC DIAGNOSTIC")

                    SectionCapture._capture_once = denied
                    assert await capture_read(page, request) == {"_skriller_error": code}
            finally:
                SectionCapture._capture_once = original_capture
            return {
                "failure_sanitization_verified": True,
                "resource_operations_checked": reads,
                "installed_capture_pipeline": True,
                "search_reference_verified": True,
                "network": "none",
                "source_live_verified": False,
                "operations_checked": checked,
            }
        finally:
            await browser.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe())))
