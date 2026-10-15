"""Offline real-Chromium probe; no external CAPTCHA or site is contacted."""

import json
from time import monotonic

from scrapling.engines._browsers._stealth import StealthySession

from skriller.connectors.classification import classify_page


def main():
    configured = StealthySession(
        headless=True,
        real_chrome=False,
        timeout=3000,
        retries=1,
        solve_cloudflare=True,
        user_data_dir="/tmp/controlled-stealth-profile",
        google_search=False,
        cookies=[],
    )
    with configured as copied:
        page = copied.context.new_page()
        page.set_content(
            "<html><body>Controlled waiting fixture<script>"
            "var marker = \"cType: 'non-interactive'\";"
            "setTimeout(() => document.documentElement.innerHTML = "
            "'<body><h1>Controlled company result</h1></body>', 1200);"
            "</script></body></html>"
        )
        copied._cloudflare_solver(page)
        content = page.content().encode()
        assert b"Controlled company result" in content
        assert classify_page(
            content, source="web", final_url="https://fixture.example.invalid"
        ).accepts_content
        page.close()
        page = copied.context.new_page()
        page.set_content(
            "<html><body><script>var marker = \"cType: 'non-interactive'\";</script></body></html>"
        )
        started = monotonic()
        try:
            copied._cloudflare_solver(page)
        except TimeoutError:
            elapsed = monotonic() - started
        else:
            raise AssertionError("Persistent fixture must reach the shared deadline")
        assert elapsed < 3.6
        assert not classify_page(
            page.content().encode(), source="web", final_url="https://fixture.example.invalid"
        ).accepts_content
        page.close()
    print(
        json.dumps(
            {
                "cleared_page": True,
                "persistent_rejected": True,
                "persistent_seconds": round(elapsed, 3),
                "network": "none",
            }
        )
    )


if __name__ == "__main__":
    main()
