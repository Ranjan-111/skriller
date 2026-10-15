from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from skriller.connectors.browser import (
    BrowserRequest,
    BrowserResult,
    DynamicBrowserAdapter,
    copied_engine_options,
    run_copied_browser_in_container,
)
from skriller.connectors.fetch import FetchUnavailable
from skriller.contracts import ExecutionContext, SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.jobs.budget import current_usage
from skriller.jobs.capacity import acquire, release
from skriller.security.runner import bounded_process

pytestmark = pytest.mark.integration_db


@pytest.fixture(autouse=True)
def fixture_source_cadence():
    from skriller.settings import Settings

    owner = sa.create_engine(Settings().database_url)
    statement = sa.text(
        "DELETE FROM capacity_cadence WHERE scope='source' AND name IN ('web','linkedin','reddit') OR scope='host' AND name IN ('example.com','example.net','linkedin.com','reddit.com')"
    )
    with owner.begin() as connection:
        connection.execute(statement)
    yield
    with owner.begin() as connection:
        connection.execute(statement)
    owner.dispose()


def context(database):
    actor = "browser-" + uuid4().hex
    workspace = database.create_workspace(actor, "Browser fixture")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Browser source fixture")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            sources=["linkedin", "reddit", "web"],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job_record = JobRepository.create(session, conversation["id"], revision["id"], uuid4().hex)
        JobRepository.transition(session, job_record["id"], "queued")
        job = job_record["id"]
    return ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
        attempt_budget=8,
    )


class FixtureExecutor:
    def __init__(self, fail=False):
        self.fail = fail
        self.requests = []

    def execute(self, request, *, cancel_check=None):
        self.requests.append(request)
        if self.fail:
            raise TimeoutError("private page content")
        return BrowserResult(
            b'<html><body><h1>Aurora Ledger</h1><p data-field="founder">Mira Rao</p></body></html>',
            request.url,
            200,
            2,
            0.01,
        )


def test_default_browser_execution_is_unavailable_without_isolation(database):
    ctx = context(database)
    with pytest.raises(FetchUnavailable) as unavailable:
        DynamicBrowserAdapter(database).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=uuid4().hex,
        )
    assert unavailable.value.failure.code == "unsupported_operation"
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        assert current_usage(session, str(ctx.job_id))[1]["fetch_attempts"] == 0


def test_disabled_read_never_starts_browser_or_charges(database):
    from skriller.connectors.switches import set_disabled

    ctx = context(database)
    fixture = FixtureExecutor()
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        set_disabled(session, "web", "read", True)
    with pytest.raises(FetchUnavailable, match="disabled"):
        DynamicBrowserAdapter(database, executor=fixture, isolation_verified=True).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=uuid4().hex,
        )
    assert not fixture.requests
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        assert current_usage(session, str(ctx.job_id))[1]["fetch_attempts"] == 0


def test_controlled_executor_charges_resources_and_returns_classified_output(database):
    ctx = context(database)
    fixture = FixtureExecutor()
    result = DynamicBrowserAdapter(database, executor=fixture, isolation_verified=True).fetch(
        ctx,
        "https://example.com",
        source="web",
        readiness_selector="[data-field=founder]",
        operation_key=uuid4().hex,
        max_requests=4,
    )
    assert b"Mira Rao" in result.content and result.classification.status == "readable"
    assert 0 < fixture.requests[0].timeout_seconds <= 5
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        assert current_usage(session, str(ctx.job_id))[1]["fetch_attempts"] == 2


def test_timeout_killed_fixture_child_releases_pool_for_other_work(database, tmp_path):
    import sys

    ctx = context(database)

    class ChildTimeout:
        def execute(self, request, *, cancel_check=None):
            outcome = bounded_process(
                [sys.executable, "-c", "import time;time.sleep(5)"],
                cwd=tmp_path,
                env={"PATH": "/usr/bin:/bin"},
                timeout=0.05,
                max_output=1000,
            )
            assert outcome.status == "timeout"
            raise TimeoutError("fixturechildterminated")

    with pytest.raises(FetchUnavailable):
        DynamicBrowserAdapter(database, executor=ChildTimeout(), isolation_verified=True).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=uuid4().hex,
            max_requests=3,
        )
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        assert current_usage(session, str(ctx.job_id))[1]["fetch_attempts"] == 3
        # Different host/source proves global browser slot was released. Source
        # backoff is deliberately retained on the failed original destination.
        lease = acquire(
            session, str(ctx.job_id), kind="browser", source="reddit", host="reddit.com"
        )
        assert release(session, lease)


def test_copied_engine_arguments_forbid_user_profile_cdp_and_uncontrolled_network():
    request = BrowserRequest("https://example.com", "h1", 10, 4)
    options = copied_engine_options(request, lambda page: None)
    assert options["real_chrome"] is False and options["cdp_url"] is None
    assert options["cookies"] == [] and options["max_pages"] == 1
    assert options["proxy"] == "http://172.29.0.2:8080"
    assert options["user_data_dir"].startswith("/tmp/")
    assert options["additional_args"]["service_workers"] == "block"
    assert options["additional_args"]["accept_downloads"] is False
    assert options["dns_over_https"] is False


def test_dynamic_and_stealth_share_one_url_attempt_cap(database):
    ctx = context(database)
    fixture = FixtureExecutor()
    for index, stealth in enumerate((False, True, False)):

        class OneRequest(FixtureExecutor):
            def execute(self, request, *, cancel_check=None):
                fixture.requests.append(request)
                return BrowserResult(b"<h1>Retained fixture</h1>", request.url, 200, 1, 0.01)

        DynamicBrowserAdapter(
            database,
            executor=OneRequest(),
            isolation_verified=True,
            stealth=stealth,
        ).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=f"method-{index}",
            max_requests=1,
        )
    assert fixture.requests[1].engine == "stealth"
    options = copied_engine_options(fixture.requests[1], lambda page: None)
    assert options["solve_cloudflare"] and options["retries"] == 1
    with pytest.raises(FetchUnavailable) as stopped:
        DynamicBrowserAdapter(
            database,
            executor=fixture,
            isolation_verified=True,
            stealth=True,
        ).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key="fourth",
            max_requests=1,
        )
    assert stopped.value.failure.code == "budget_exhausted"
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        assert current_usage(session, str(ctx.job_id))[1]["fetch_attempts"] == 3


def test_actual_copied_engine_entry_refuses_developer_host(monkeypatch):
    monkeypatch.delenv("SKRILLER_BROWSER_WORKER", raising=False)
    with pytest.raises(RuntimeError, match="isolated"):
        run_copied_browser_in_container(BrowserRequest("https://example.com", "h1", 1, 2))


def test_two_page_pool_blocks_third_executor_and_releases_on_completion(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from skriller.db import Database

    db = Database(database.engine.url, pool_size=3)
    contexts = [context(db) for _ in range(3)]
    started = [Event(), Event()]
    finish = Event()

    class HoldingExecutor:
        def __init__(self, index):
            self.index = index

        def execute(self, request, *, cancel_check=None):
            started[self.index].set()
            assert finish.wait(3)
            return BrowserResult(
                b"<html><body><h1>Controlled page</h1></body></html>", request.url, 200, 1, 0.01
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = []
            for index, source in enumerate(["linkedin", "reddit"]):
                adapter = DynamicBrowserAdapter(
                    db, executor=HoldingExecutor(index), isolation_verified=True
                )
                futures.append(
                    pool.submit(
                        adapter.fetch,
                        contexts[index],
                        f"https://{source}.com/fixture-{uuid4().hex}",
                        source=source,
                        readiness_selector="h1",
                        operation_key=uuid4().hex,
                        max_requests=2,
                    )
                )
            ready = all(event.wait(3) for event in started)
            if not ready:
                finish.set()
                for future in futures:
                    if future.done():
                        future.result()
            assert ready
            with pytest.raises(FetchUnavailable) as third:
                DynamicBrowserAdapter(
                    db, executor=FixtureExecutor(), isolation_verified=True
                ).fetch(
                    contexts[2],
                    "https://example.net",
                    source="web",
                    readiness_selector="h1",
                    operation_key=uuid4().hex,
                    max_requests=2,
                )
            assert third.value.failure.code == "rate_limited"
            finish.set()
            assert all(future.result(3).classification.status == "readable" for future in futures)
    finally:
        finish.set()
        db.dispose()


def test_child_calls_copied_factory_with_fresh_profile_and_public_only_routes(monkeypatch):
    from types import SimpleNamespace

    from scrapling.engines.toolbelt.custom import Response

    import skriller.connectors.browser as module

    monkeypatch.setenv("SKRILLER_BROWSER_WORKER", "isolated")
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: True if str(p) == "/.dockerenv" else original(p))
    profiles = []
    actions = []

    def factory(url, **options):
        profiles.append(options["user_data_dir"])
        assert Path(profiles[-1]).is_dir()

        class Page:
            def route(self, pattern, handler):
                self.handler = handler

            def on(self, event, handler):
                pass

        page = Page()
        options["page_setup"](page)
        for target in [
            url,
            "http://127.0.0.1/private",
            "file:///Users/private",
            "https://example.com/script.js",
        ]:
            interception = SimpleNamespace(
                request=SimpleNamespace(url=target, resource_type="script"),
                abort=lambda: actions.append("abort"),
                continue_=lambda: actions.append("continue"),
            )
            page.handler(interception)
        return Response(
            url,
            b"<html><body><h1>Controlled output</h1></body></html>",
            200,
            "OK",
            {},
            {},
            {},
            adaptive=False,
        )

    monkeypatch.setattr(module.DynamicFetcher, "fetch", factory)
    request = BrowserRequest("https://example.com", "h1", 1, 4)
    run_copied_browser_in_container(request)
    run_copied_browser_in_container(request)
    assert profiles[0] != profiles[1] and all(not Path(profile).exists() for profile in profiles)
    assert actions == ["continue", "abort", "abort", "continue"] * 2


def test_invalid_executor_result_stays_estimated_and_releases_capacity(database):
    from skriller.db.schema import reservations

    ctx = context(database)

    class OverLimit:
        def execute(self, request, *, cancel_check=None):
            return BrowserResult(
                b"<html><h1>Invalid worker</h1></html>",
                request.url,
                200,
                request.max_requests + 1,
                0.01,
            )

    with pytest.raises(FetchUnavailable) as caught:
        DynamicBrowserAdapter(database, executor=OverLimit(), isolation_verified=True).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=uuid4().hex,
            max_requests=2,
        )
    assert caught.value.failure.code == "budget_exhausted"
    with database.tenant(ctx.actor_id, str(ctx.workspace_id)) as session:
        row = session.execute(sa.select(reservations)).mappings().one()
        assert row["reconciliation_status"] == "estimated"
        assert row["actual_dimensions"] == {"fetch_attempts": 2}
        lease = acquire(
            session, str(ctx.job_id), kind="browser", source="reddit", host="reddit.com"
        )
        assert release(session, lease)
    from skriller.settings import Settings

    owner = sa.create_engine(Settings().database_url)
    try:
        with owner.connect() as connection:
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM capacity_leases WHERE job_id=:job"),
                    {"job": str(ctx.job_id)},
                ).scalar_one()
                == 0
            )
    finally:
        owner.dispose()


def test_reconciliation_failure_still_releases_browser_lease(database, monkeypatch):
    import skriller.connectors.browser as module

    ctx = context(database)
    releases = []
    original = module.release

    def recorded_release(*args, **kwargs):
        result = original(*args, **kwargs)
        releases.append(result)
        return result

    def failed_reconcile(*args, **kwargs):
        raise RuntimeError("controlled accounting failure")

    monkeypatch.setattr(module, "reconcile", failed_reconcile)
    monkeypatch.setattr(module, "release", recorded_release)
    with pytest.raises(RuntimeError, match="controlled accounting failure"):
        DynamicBrowserAdapter(database, executor=FixtureExecutor(), isolation_verified=True).fetch(
            ctx,
            "https://example.com",
            source="web",
            readiness_selector="h1",
            operation_key=uuid4().hex,
            max_requests=3,
        )
    assert releases == [True]
