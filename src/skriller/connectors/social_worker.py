"""Fresh isolated browser execution of generated, attributed read-only scripts.

No host bridge, browser profile, write module or Node runtime is used. This module
is not registered as a product source route until isolation/connection wiring passes.
The launch and credential-delivery pattern reuses the existing LinkedIn worker.
"""

import asyncio
import json
import logging
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit

from skriller.connectors.facebook_read import FacebookRead, FacebookSearch
from skriller.connectors.facebook_read import parse_profile_response as facebook_profile
from skriller.connectors.facebook_read import parse_search_response as facebook_search
from skriller.connectors.instagram_read import InstagramRead, InstagramSearch
from skriller.connectors.instagram_read import parse_profile_response as instagram_profile
from skriller.connectors.instagram_read import parse_search_response as instagram_search
from skriller.connectors.social_read import SocialData

BUNDLE = Path(__file__).parents[1] / "_vendor/opencli/READ_SCRIPTS.json"
OPERATIONS: dict[str, type[SocialData]] = {
    "instagram_search": InstagramSearch,
    "instagram_profile": InstagramRead,
    "facebook_search": FacebookSearch,
    "facebook_profile": FacebookRead,
}


def encoded(value):
    return quote(value, safe="~()*!.'")


def navigation_targets(operation, request):
    if operation == "instagram_search":
        return ["https://www.instagram.com/"]
    if operation == "facebook_search":
        return [
            "https://www.facebook.com/",
            "https://www.facebook.com/search/top?q=" + encoded(request.query),
        ]
    return [request.target_url()]


def extraction_script(operation, request):
    if operation not in OPERATIONS or not isinstance(request, OPERATIONS[operation]):
        raise ValueError("A named typed read operation is required")
    raw = BUNDLE.read_bytes()
    if len(raw) > 65536:
        raise ValueError("Read script bundle exceeds its bound")
    bundle = json.loads(raw)
    if bundle.get("schema_version") != 1 or set(bundle.get("commands", {})) != set(OPERATIONS):
        raise ValueError("Read script bundle is unavailable")
    command = bundle["commands"][operation]
    tokens = command["tokens"]
    expected = (
        {"username"}
        if operation.endswith("profile")
        else {"query", "limit"}
        if operation.startswith("instagram")
        else {"limit"}
    )
    if set(tokens) != expected or not isinstance(command["script"], str):
        raise ValueError("Read script parameters are invalid")
    script = command["script"]
    for name, token in tokens.items():
        if not isinstance(token, str) or not token or script.count(token) != 1:
            raise ValueError("Read script replacement must be unambiguous")
        value = json.dumps(getattr(request, name), ensure_ascii=True)
        if operation == "facebook_search":
            value = "const limit = " + value + ";"
        script = script.replace(token, value, 1)
    if len(script.encode()) > 32768:
        raise ValueError("Read script exceeds its bound")
    return script


def session_credentials(operation, path="/run/skriller-credentials.json"):
    if (
        operation not in OPERATIONS
        or os.environ.get("SKRILLER_SOCIAL_WORKER") != "isolated"
        or not os.path.isfile("/.dockerenv")
    ):
        raise ValueError("An isolated social worker is required")
    with open(path, encoding="utf-8") as stream:
        raw = stream.read(65537)
    data = json.loads(raw) if len(raw) <= 65536 else None
    names = (
        {"INSTAGRAM_SESSION_COOKIE": "sessionid"}
        if operation.startswith("instagram")
        else {"FACEBOOK_USER_ID": "c_user", "FACEBOOK_SESSION_COOKIE": "xs"}
    )
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("runner") != operation
        or not isinstance(data.get("environment"), dict)
        or set(data["environment"]) != set(names)
    ):
        raise ValueError("Source session is unavailable")
    cookies = []
    for key, name in names.items():
        value = data["environment"][key]
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[^\s;\x00-\x1f\x7f]{1,16384}", value)
            or key == "FACEBOOK_USER_ID"
            and not re.fullmatch(r"[0-9]{1,30}", value)
        ):
            raise ValueError("Source session is unavailable")
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".instagram.com"
                if operation.startswith("instagram")
                else ".facebook.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }
        )
    return cookies


class RequestBudget:
    def __init__(self, operation, request):
        self.operation, self.request = operation, request
        self.targets = navigation_targets(operation, request)
        self.count = self.documents = self.api_requests = 0
        self.stopped = False
        self.failure_code = "source_unavailable"

    def allow(self, url, method, resource_type):
        self.count += 1
        if self.stopped or self.count > 80:
            self.stopped = True
            return False
        try:
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.username
                or parts.password
                or parts.port not in {None, 443}
                or method not in {"GET", "HEAD"}
            ):
                return False
        except ValueError:
            return False
        host = "www.instagram.com" if self.operation.startswith("instagram") else "www.facebook.com"
        if resource_type == "document":
            expected = self.targets[self.documents] if self.documents < len(self.targets) else None
            self.documents += 1
            if url != expected:
                self.stopped = True
                self.failure_code = "access_denied"
                return False
            return True
        if resource_type in {"fetch", "xhr"}:
            if (
                host != parts.hostname
                or method != "GET"
                or not self.operation.startswith("instagram")
            ):
                return False
            if self.operation == "instagram_search":
                expected = (
                    "https://www.instagram.com/web/search/topsearch/?query="
                    + encoded(self.request.query)
                    + "&context=user"
                )
                valid = self.api_requests == 0 and url == expected
            else:
                user = encoded(self.request.username)
                expected = [
                    "https://www.instagram.com/api/v1/users/web_profile_info/?username=" + user,
                    "https://www.instagram.com/api/v1/feed/user/" + user + "/username/?count=1",
                ]
                valid = (
                    self.api_requests < 2
                    and url == expected[self.api_requests]
                    or self.api_requests == 2
                    and bool(re.fullmatch(r"/api/v1/users/[0-9]{1,30}/info/", parts.path))
                    and not parts.query
                )
            if valid:
                self.api_requests += 1
            return bool(valid)
        static = (
            "static.cdninstagram.com"
            if self.operation.startswith("instagram")
            else "static.xx.fbcdn.net"
        )
        return resource_type in {"script", "stylesheet"} and parts.hostname in {host, static}

    def response(self, status):
        if status in {401, 403, 429}:
            self.stopped = True
            self.failure_code = "rate_limited" if status == 429 else "auth_expired"


def read_failure(payload):
    failure = payload.get("failure") if isinstance(payload, dict) else None
    if not isinstance(failure, dict):
        return "source_unavailable"
    message = failure.get("message")
    if not isinstance(message, str):
        return "source_unavailable"
    if failure.get("code") == "AUTH_REQUIRED" or re.search(r"HTTP (401|403)\b", message):
        return "auth_expired"
    if re.search(r"HTTP 429\b", message):
        return "rate_limited"
    if "explicitly public account" in message:
        return "access_denied"
    return "source_unavailable"


async def capture(page, operation, request):
    script = extraction_script(operation, request)
    for target in navigation_targets(operation, request):
        await page.goto(target, wait_until="domcontentloaded")
        if page.url.rstrip("/") != target.rstrip("/"):
            return {"_skriller_error": "access_denied"}
    if operation.startswith("facebook"):
        await page.wait_for_timeout(4000 if operation.endswith("search") else 3000)
    payload = await page.evaluate(script)
    if operation.startswith("instagram"):
        if not isinstance(payload, dict) or "failure" in payload:
            return {"_skriller_error": read_failure(payload)}
        payload = payload.get("rows")
    elif operation == "facebook_search":
        if isinstance(payload, dict) and payload.get("status") == "auth":
            return {"_skriller_error": "auth_expired"}
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("rows"), list)
            or not payload["rows"]
        ):
            return {"_skriller_error": "source_unavailable"}
        payload = payload["rows"]
    now = datetime.now(UTC)
    parser = {
        "instagram_search": instagram_search,
        "instagram_profile": instagram_profile,
        "facebook_search": facebook_search,
        "facebook_profile": facebook_profile,
    }[operation]
    result = cast(Callable[..., Any], parser)(payload, request, observed_at=now)
    return {
        "data": [item.model_dump(mode="json") for item in result]
        if isinstance(result, list)
        else result.model_dump(mode="json")
    }


async def execute(operation, request, cookies):
    from patchright.async_api import async_playwright

    async with async_playwright() as driver:
        browser = await driver.chromium.launch(
            headless=True,
            proxy={"server": "http://172.29.0.2:8080"},
            args=["--disable-dev-shm-usage"],
        )
        try:
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            await context.add_cookies(cookies)
            budget = RequestBudget(operation, request)

            async def route_request(route):
                item = route.request
                if budget.allow(item.url, item.method, item.resource_type):
                    await route.continue_()
                else:
                    await route.abort()

            async def block_socket(socket):
                await socket.close()

            await context.route("**/*", route_request)
            await context.route_web_socket("**/*", block_socket)
            page = await context.new_page()
            page.set_default_timeout(8000)
            page.on(
                "response",
                lambda response: (
                    budget.response(response.status)
                    if response.request.resource_type in {"document", "fetch", "xhr"}
                    else None
                ),
            )
            try:
                payload = await asyncio.wait_for(capture(page, operation, request), timeout=35)
            except Exception:  # noqa: BLE001 - never expose page/session/SDK exceptions
                return {
                    "_skriller_error": budget.failure_code
                    if budget.stopped
                    else "source_unavailable"
                }
            if budget.stopped:
                return {"_skriller_error": budget.failure_code}
            payload.update(network_requests_seen=budget.count, api_requests=budget.api_requests)
            return payload
        finally:
            await browser.close()


def main(argv=None):
    logging.disable(logging.CRITICAL)
    try:
        args = sys.argv[1:] if argv is None else argv
        if len(args) != 2 or args[0] not in OPERATIONS or len(args[1].encode()) > 8192:
            raise ValueError("One named bounded read is required")
        operation = args[0]
        request = OPERATIONS[operation].model_validate_json(args[1])
        payload = asyncio.run(execute(operation, request, session_credentials(operation)))
        serialized = json.dumps(payload, allow_nan=False)
        if len(serialized.encode()) > 1_048_576:
            raise ValueError("Read output exceeds bounds")
        sys.stdout.write(serialized)
        return 0
    except Exception:  # noqa: BLE001 - cookies, page bodies and SDK errors remain private
        sys.stderr.write("Social read unavailable\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
