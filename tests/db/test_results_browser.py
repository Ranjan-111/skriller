"""Real Chromium renders the shipped component against a synthetic tenant API.

The browser uses a fresh temporary profile. All page network requests are confined
to the fixture server; no user browser session, Firebase login or cloud model runs.
"""

import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from test_identity import fact
from test_qualification_pipeline import fixture

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.db import ResearchRepository
from skriller.db.schema import entities
from skriller.jobs.budget import locked_job
from skriller.research.collection import finish_collection_pipeline
from skriller.research.qualification import checkpoint_qualification
from skriller.research.service import result_rows
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
ROOT = Path(__file__).resolve().parents[2]


def test_real_browser_results_identity_conflicts_and_anonymous_discussion(database, tmp_path):
    actor, workspace, job_id = fixture(database)
    with database.tenant(actor, workspace) as session:
        rows = result_rows(session, job_id)
        selected = [row["id"] for row in rows if row["title"] in {"Confirmed", "Unknown size"}]
        for identifier in selected:
            fact(session, identifier, "domain", "company.example.org")
            fact(session, identifier, "legal_name", "Synthetic Company")
            fact(session, identifier, "country", "India")
        candidate = next(row for row in rows if row["title"] == "Confirmed")
        observations = []
        for role, url in (
            ("Founder", "https://example.org/team"),
            ("Advisor", "https://example.net/bio"),
        ):
            saved = ResearchRepository.add_evidence(
                session,
                source_url=url,
                source_platform="web",
                collected_at=datetime.now(UTC),
                excerpt=f"Current role: {role}",
            )
            claim = ResearchRepository.claim(
                session,
                candidate["id"],
                "current_role",
                role,
                mode="observed",
                status="accepted",
                evidence_ids=[saved["id"]],
            )
            observations.append(
                {
                    "claim_id": claim["id"],
                    "field": "current_role",
                    "value": role,
                    "quote": f"Current role: {role}",
                    "status": claim["status"],
                }
            )
        record = ResearchRepository.get_entity(session, candidate["id"])
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == workspace, entities.c.id == candidate["id"])
            .values(
                attributes={
                    **record["attributes"],
                    "extraction": {
                        "status": "observed",
                        "failure_code": None,
                        "observations": observations,
                        "rejected_claims": 0,
                        "coverage_complete": True,
                        "omitted_chunks": 0,
                    },
                }
            )
        )
        discussion = next(row for row in rows if row["title"] == "Unknown identity")
        record = ResearchRepository.get_entity(session, discussion["id"])
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == workspace, entities.c.id == discussion["id"])
            .values(
                attributes={
                    **record["attributes"],
                    "source": "linkedin",
                    "url": "https://www.linkedin.com/feed/update/urn:li:activity:123456789/",
                    "_source_native_id": {"namespace": "linkedin_activity", "id": "123456789"},
                }
            )
        )
        job = checkpoint_qualification(
            session, locked_job(session, job_id), result_rows(session, job_id)
        )
        finish_collection_pipeline(session, job)
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    client = TestClient(app)
    bundle = tmp_path / "bundle"
    subprocess.run(
        ["node", str(ROOT / "apps/web/tools/results-browser-fixture.mjs"), str(bundle)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        timeout=60,
    )
    css = next(bundle.glob("*.css")).name
    job_json = json.dumps({"id": job_id, "workspace_id": workspace, "status": "completed"})
    html = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/{css}"></head><body><div id="root"></div><script>window.fixtureJob={job_json}</script><script src="/fixture.js"></script></body></html>'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def serve(self):
            if self.path.startswith("/api/"):
                payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                response = client.request(
                    self.command, self.path.removeprefix("/api"), content=payload
                )
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.content)
                return
            path = bundle / self.path.lstrip("/")
            content = (
                html.encode() if self.path == "/" else path.read_bytes() if path.is_file() else b""
            )
            self.send_response(200 if content else 404)
            self.send_header(
                "Content-Type",
                "text/html"
                if self.path == "/"
                else "text/css"
                if self.path.endswith(".css")
                else "application/javascript",
            )
            self.end_headers()
            self.wfile.write(content)

        do_GET = serve
        do_POST = serve

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            executable = os.environ.get("SKRILLER_TEST_CHROME_EXECUTABLE")
            mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if not executable and mac_chrome.is_file():
                executable = str(mac_chrome)
            browser = playwright.chromium.launch(
                executable_path=executable, headless=True, args=["--disable-background-networking"]
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = f"http://127.0.0.1:{server.server_port}"
            page.route(
                "**/*",
                lambda route: (
                    route.continue_() if route.request.url.startswith(base + "/") else route.abort()
                ),
            )
            page.goto(base)
            expect(
                page.get_by_role("heading", name="Research complete", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_text("LinkedIn post · indexed reference", exact=True)
            ).to_be_visible()
            expect(page.get_by_text("The author is unknown", exact=False)).to_be_visible()
            page.locator("summary").filter(has_text="Source observations").click()
            expect(
                page.get_by_role("heading", name="Conflicting source observations")
            ).to_be_visible()
            page.get_by_role("button", name="View supporting source", exact=True).first.click()
            expect(page.get_by_role("link", name="Open original source")).to_be_visible()
            page.get_by_text("Identity review queue", exact=True).click()
            page.get_by_role("button", name="View current identity evidence", exact=True).click()
            expect(page.get_by_role("button", name="Approve link", exact=True)).to_be_enabled()
            expect(page.get_by_role("link", name="Open identity source").first).to_be_visible()
            capture = Path(os.environ.get("SKRILLER_BROWSER_CAPTURE_DIR", str(tmp_path)))
            capture.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(capture / "desktop.png"), full_page=True)
            page.get_by_role("button", name="Approve link", exact=True).click()
            expect(page.get_by_role("button", name="Reverse link", exact=True)).to_be_enabled()
            page.get_by_role("button", name="Reverse link", exact=True).click()
            expect(page.get_by_text("reversed", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(
                page.get_by_text("LinkedIn post · indexed reference", exact=True)
            ).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(capture / "mobile.png"), full_page=True)
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
