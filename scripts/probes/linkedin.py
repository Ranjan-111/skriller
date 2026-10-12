"""Opt-in read-only LinkedIn MCP feasibility probe; never start/login a server."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/external/linkedin"
COMMIT = "f1ba6aa87234526cf22812e59233e0c619073529"
OPERATIONS = {"search_people", "search_posts", "get_person_profile", "get_company_profile"}


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


async def call_mcp(endpoint: str, operation: str, arguments: dict) -> dict:
    """Use the installed MCP SDK, not a second home-grown MCP transport."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with (
        streamablehttp_client(endpoint) as (reader, writer, _session),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        result = await session.call_tool(operation, arguments)
        if result.isError:
            raise RuntimeError("MCP tool reported an operation error")
        if result.structuredContent is not None:
            return result.structuredContent
        for item in result.content:
            if item.type == "text":
                return json.loads(item.text)
        raise ValueError("MCP returned no structured operation data")


async def probe(
    *,
    live: bool = False,
    endpoint: str | None = None,
    session_confirmed: bool = False,
    auto_import_disabled: bool = False,
    operation: str = "search_people",
    arguments: dict | None = None,
    configured: bool = False,
    caller: Callable[[str, str, dict], Awaitable[dict]] = call_mcp,
) -> dict:
    report = {
        "platform": "linkedin",
        "operation": operation,
        "source": verify_source(),
        "status": "unvalidated" if configured else "skipped",
        "configured": configured,
        "validated": False,
        "elapsed_ms": 0,
        "reason": "No opt-in controlled live operation executed",
    }
    if operation not in OPERATIONS:
        raise ValueError("Probe permits only reviewed read operations")
    if not live:
        return report
    if not endpoint or not session_confirmed or not auto_import_disabled:
        report["reason"] = (
            "Requires explicit endpoint, existing session and disabled auto-import/login"
        )
        return report
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an explicit loopback MCP endpoint without credentials")
    args = dict(arguments or {})
    if operation == "search_posts":
        args["max_pages"] = 1
    elif operation == "get_person_profile":
        args["max_scrolls"] = 1
    started = time.monotonic()
    try:
        data = await asyncio.wait_for(caller(endpoint, operation, args), timeout=60)
        if not isinstance(data, dict) or not isinstance(data.get("sections"), dict):
            raise TypeError("Unexpected LinkedIn operation schema")
        sections = data["sections"]
        if not sections or not any(
            isinstance(value, str) and value.strip() for value in sections.values()
        ):
            raise ValueError("No extracted section content")
        errors = data.get("section_errors") or {}
        report.update(
            status="partial" if errors else "verified",
            validated=not bool(errors),
            reason="Operation returned content" if not errors else "Some requested sections failed",
            fields=sorted(data),
            sections=sorted(sections),
            section_errors=sorted(errors),
            reference_count=sum(
                len(value)
                for value in data.get("references", {}).values()
                if isinstance(value, list)
            ),
        )
    except Exception as exc:  # noqa: BLE001 — external operation boundary must emit a failure report
        # Tool/server errors may contain session secrets outside URL syntax.
        report.update(status="failed", reason=f"{type(exc).__name__}: controlled operation failed")
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--endpoint")
    parser.add_argument("--session-confirmed", action="store_true")
    parser.add_argument("--auto-import-disabled", action="store_true")
    parser.add_argument("--configured", action="store_true")
    parser.add_argument("--operation", choices=sorted(OPERATIONS), default="search_people")
    parser.add_argument("--arguments", default='{"keywords":"fintech founder"}')
    args = vars(parser.parse_args())
    args["arguments"] = json.loads(args["arguments"])
    print(json.dumps(asyncio.run(probe(**args)), indent=2))


if __name__ == "__main__":
    main()
