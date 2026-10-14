"""Opt-in real public rendering in a fresh digest-pinned guarded container."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from test_browser import (
    context,
    fixture_source_cadence,  # noqa: F401 - registers imported pytest fixture
)

from skriller.connectors.browser import DynamicBrowserAdapter
from skriller.connectors.browser_executor import ConcreteBrowserExecutor

pytestmark = [pytest.mark.integration_db, pytest.mark.usefixtures("fixture_source_cadence")]


def test_actual_copied_browser_reads_public_example_in_guarded_container(database):
    image = os.environ.get("SKRILLER_BROWSER_TEST_IMAGE")
    if not image:
        pytest.skip("Requires installed immutable isolated browser worker test image")
    ctx = context(database).model_copy(
        update={"deadline": datetime.now(UTC) + timedelta(seconds=45)}
    )
    result = DynamicBrowserAdapter(
        database, executor=ConcreteBrowserExecutor(image), isolation_verified=True
    ).fetch(
        ctx,
        "https://example.com",
        source="web",
        readiness_selector="body",
        operation_key="actual-browser",
        max_requests=8,
    )
    assert b"Example Domain" in result.content
    assert result.classification.accepts_content
    assert 1 <= result.request_count <= 8
    print(f"Public browser elapsed: {result.elapsed_seconds:.3f}s")


def test_actual_chromium_container_persisted_cancel_removes_worker(database, monkeypatch):
    import subprocess
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import sqlalchemy as sa

    from skriller.connectors import browser_executor as module
    from skriller.connectors.fetch import FetchUnavailable
    from skriller.db.schema import reservations
    from skriller.jobs.capacity import acquire, release
    from skriller.jobs.control import cancel

    image = os.environ.get("SKRILLER_BROWSER_TEST_IMAGE")
    if not image:
        pytest.skip("Requires installed immutable isolated browser worker test image")
    ctx = context(database).model_copy(
        update={"deadline": datetime.now(UTC) + timedelta(seconds=45)}
    )
    names = []
    launched = threading.Event()
    original = module.bounded_process

    def record(argv, **kwargs):
        if argv[1] == "run":
            names.append(argv[argv.index("--name") + 1])
            launched.set()
        return original(argv, **kwargs)

    monkeypatch.setattr(module, "bounded_process", record)
    adapter = DynamicBrowserAdapter(
        database, executor=ConcreteBrowserExecutor(image), isolation_verified=True
    )
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(
            adapter.fetch,
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="[data-skriller-never-present]",
            operation_key="cancel-browser",
            max_requests=8,
        )
        try:
            assert launched.wait(3)
            end = time.monotonic() + 8
            while time.monotonic() < end:
                top = subprocess.run(
                    ["/usr/local/bin/docker", "top", names[0], "-eo", "pid,comm"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                    check=False,
                )
                if top.returncode == 0 and any(
                    name in top.stdout.casefold() for name in ("chrome", "chromium")
                ):
                    break
                if task.done():
                    task.result()
                    pytest.fail("Browser worker finished before Chromium readiness")
                time.sleep(0.05)
            else:
                pytest.fail(
                    "Own isolated Chromium process was not confirmed: " + top.stdout + top.stderr
                )
            started = time.monotonic()
            with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
                cancel(session, str(ctx.job_id))
            with pytest.raises(FetchUnavailable) as caught:
                task.result(timeout=5)
            assert caught.value.failure.code == "cancelled"
            elapsed = time.monotonic() - started
            assert elapsed < 5
            print(f"Chromium persisted cancellation elapsed: {elapsed:.3f}s")
            inspect = subprocess.run(
                ["/usr/local/bin/docker", "inspect", names[0]],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
                check=False,
            )
            assert inspect.returncode != 0 and "No such" in inspect.stderr
            with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
                rows = session.execute(sa.select(reservations)).mappings().all()
                assert len(rows) == 1 and rows[0]["reconciliation_status"] == "estimated"
            other = context(database)
            with database.tenant(other.actor_id, str(other.workspace_id)) as session:
                lease = acquire(
                    session, str(other.job_id), kind="browser", source="reddit", host="reddit.com"
                )
                assert release(session, lease)
        finally:
            if names:
                cleanup = subprocess.run(
                    ["/usr/local/bin/docker", "rm", "-f", names[0]],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                    check=False,
                )
                assert cleanup.returncode == 0 or "No such container" in cleanup.stderr


def test_actual_copied_browser_renders_fixed_js_fixture_without_private_route(
    database, monkeypatch
):
    from skriller.connectors import browser_executor as module

    image = os.environ.get("SKRILLER_BROWSER_TEST_IMAGE")
    if not image:
        pytest.skip("Requires installed immutable isolated browser worker test image")
    # Test-only fixed page_setup fulfillment of a synthetic public target. The
    # production executor still only runs browser_worker with its bounded JSON.
    code = """
import base64,json,logging,pathlib
logging.disable(logging.CRITICAL)
import skriller.connectors.browser as browser
original=browser.copied_engine_options
html='<html><body><h1 id="target">Loading</h1><script>setTimeout(()=>{target.textContent="JS fixture ready";target.dataset.ready="yes"},50);fetch("http://169.254.169.254/latest/meta-data").catch(()=>{})</script></body></html>'
def options(request, setup):
    def fixture_setup(page):
        setup(page)
        page.route('https://example.com/skriller-fixed-js-fixture',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
    return original(request,fixture_setup)
browser.copied_engine_options=options
request=browser.BrowserRequest(**json.loads(pathlib.Path('/work/request.json').read_bytes()))
result=browser.run_copied_browser_in_container(request)
print(json.dumps(dict(content_base64=base64.b64encode(result.content).decode(),final_url=result.final_url,status=result.status,request_count=result.request_count,elapsed_seconds=result.elapsed_seconds)))
"""
    original = module.bounded_process
    launched = []

    def fixed_fixture(argv, **kwargs):
        if argv[1] == "run":
            launched.append(argv[argv.index("--name") + 1])
            argv = argv[:-4] + ["python", "-c", code]
        return original(argv, **kwargs)

    monkeypatch.setattr(module, "bounded_process", fixed_fixture)
    ctx = context(database).model_copy(
        update={"deadline": datetime.now(UTC) + timedelta(seconds=30)}
    )
    result = DynamicBrowserAdapter(
        database, executor=ConcreteBrowserExecutor(image), isolation_verified=True
    ).fetch(
        ctx,
        "https://example.com/skriller-fixed-js-fixture",
        source="web",
        readiness_selector="h1[data-ready=yes]",
        operation_key="js-fixture",
        max_requests=4,
    )
    assert b">JS fixture ready</h1>" in result.content
    assert result.classification.accepts_content
    assert result.request_count == 1  # Private fetch was intercepted and aborted.
    assert len(launched) == 1
    print(f"Isolated JS fixture elapsed: {result.elapsed_seconds:.3f}s")
