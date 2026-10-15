"""Fixed container child protocol for the copied public DynamicFetcher."""

import base64
import json
import logging
import sys
from pathlib import Path

from skriller.connectors.browser import BrowserRequest, run_copied_browser_in_container


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        if sys.argv[1:] != ["/work/request.json"]:
            raise ValueError("Fixed request path required")
        with Path("/work/request.json").open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError("Bounded request required")
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "url",
            "readiness_selector",
            "timeout_seconds",
            "max_requests",
            "max_body_bytes",
            "engine",
            "solve_challenge",
        }:
            raise ValueError("Typed request fields required")
        request = BrowserRequest(**data)
        result = run_copied_browser_in_container(request)
        print(
            json.dumps(
                {
                    "content_base64": base64.b64encode(result.content).decode("ascii"),
                    "final_url": result.final_url,
                    "status": result.status,
                    "request_count": result.request_count,
                    "elapsed_seconds": result.elapsed_seconds,
                },
                separators=(",", ":"),
            )
        )
        return 0
    except TimeoutError:
        print('{"error":"deadline_exceeded"}')
        return 1
    except Exception:  # noqa: BLE001 - serialize only typed redacted child failure
        # Never serialize page text, URL, stack traces or SDK/OS error details.
        print('{"error":"source_unavailable"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
