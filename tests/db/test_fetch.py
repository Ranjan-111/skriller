import asyncio
import gzip
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from test_budget import job_fixture

from skriller.connectors.fetch import FetchUnavailable, HTTPFetcher
from skriller.contracts import ExecutionContext
from skriller.jobs.budget import current_usage
from skriller.security.proxy import GuardedProxy
from skriller.security.urls import Destination, EgressDenied
from skriller.storage import BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


def test_disabled_read_never_starts_http_or_charges(database, proxy):
    from skriller.connectors.switches import set_disabled

    context = ctx(database)
    endpoint, requests, _ = proxy
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        set_disabled(session, "web", "read", True)
    with pytest.raises(FetchUnavailable, match="disabled"):
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            context, "https://example.com/company", source="web", operation_key=uuid4().hex
        )
    assert not requests
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 0


@pytest.fixture
def proxy(monkeypatch):
    import skriller.connectors.fetch as fetch_module
    from skriller.settings import Settings

    original_acquire = fetch_module.acquire
    rss_fixture = uuid4().hex

    def fixture_capacity(session, job_id, **kwargs):
        if kwargs.get("source") == "rss" and kwargs.get("host") == "example.com":
            kwargs.update(source="rss-test-" + rss_fixture, host=rss_fixture + ".example.invalid")
        return original_acquire(session, job_id, **kwargs)

    monkeypatch.setattr(fetch_module, "acquire", fixture_capacity)

    owner = sa.create_engine(Settings().database_url)
    with owner.begin() as connection:
        connection.execute(
            sa.text(
                "DELETE FROM capacity_cadence WHERE (scope='source' AND name='web') OR (scope='host' AND name='example.com')"
            )
        )
    company = (Path(__file__).resolve().parents[1] / "fixtures/research/company.html").read_bytes()
    requests = []

    class Origin(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            requests.append(self.path)
            if self.path == "/slow":
                time.sleep(0.3)
            if self.path == "/idle-headers":
                time.sleep(10)
            status = 200
            body, extras = company, {}
            content_type = "text/html; charset=utf-8"
            if self.path in {"/rss", "/rss-bad", "/rss-empty"}:
                content_type = "application/atom+xml; charset=utf-8"
                body = (
                    Path(__file__).resolve().parents[1] / "fixtures/research/feed.xml"
                ).read_bytes()
                if self.path == "/rss-bad":
                    body = b"<error>Not a feed</error>"
                if self.path == "/rss-empty":
                    body = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Empty feed</title></feed>'
            if self.path == "/large":
                body = gzip.compress(b"x" * 100000)
                extras["Content-Encoding"] = "gzip"
            if self.path == "/login200":
                body = b'<html><head><title>Sign in</title></head><body><form><input type="password"><p>Sign in to continue</p></form></body></html>'
            if self.path == "/dynamic":
                body = (
                    Path(__file__).resolve().parents[1] / "fixtures/research/dynamic.html"
                ).read_bytes()
            if self.path == "/empty-results":
                body = b'<html><body><p role="status">No posts found</p><script src="app.js"></script></body></html>'
            if self.path == "/challenge":
                body = b"<html>verify you are human</html>"
            if self.path == "/denied":
                status = 403
            if self.path == "/rate":
                status = 429
                extras["Retry-After"] = "120"
            if self.path in {"/redirect", "/private"}:
                status = 302
                extras["Location"] = (
                    "/company" if self.path == "/redirect" else "http://127.0.0.1/secret"
                )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extras.items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)

    # Only this fixture maps public test names to a loopback origin. Production
    # continues to use the strict resolver and vetted numerical dialer unchanged.
    def fixture_destination(url):
        if "example.com" not in url:
            raise EgressDenied("Fixture public target only")
        return Destination(url, "example.com", origin.server_port, ("127.0.0.1",))

    monkeypatch.setattr("skriller.security.proxy.resolve_public_destination", fixture_destination)
    guarded = GuardedProxy(("127.0.0.1", 0))
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (origin, guarded)]
    for t in threads:
        t.start()
    yield f"http://127.0.0.1:{guarded.server_port}", requests, company
    for s in (guarded, origin):
        s.shutdown()
        s.server_close()
    with owner.begin() as connection:
        connection.execute(
            sa.text(
                "DELETE FROM capacity_cadence WHERE (scope='source' AND name='web') OR (scope='host' AND name='example.com')"
            )
        )
    owner.dispose()


def ctx(database):
    actor, workspace, job = job_fixture(database)
    return ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
        attempt_budget=3,
    )


def test_actual_copied_fetcher_through_guarded_proxy_persists_evidence(
    database, proxy, tmp_path, monkeypatch
):
    endpoint, requests, body = proxy
    context = ctx(database)
    # NO_PROXY must not make libcurl silently route the public URL directly.
    monkeypatch.setenv("NO_PROXY", "*")
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context, "http://example.com/company", source="web", operation_key=uuid4().hex
    )
    assert artifact.response.css(".founder-name")[0].text == "Mira Rao"
    assert artifact.response.body == body and artifact.decoded_bytes == len(body)
    assert artifact.network_seconds > 0 and artifact.parser_seconds > 0
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        evidence = artifact.persist(session, storage)
        assert storage.retrieve(session, evidence["id"]) == body
        assert evidence["content_hash"] == artifact.content_hash
        assert evidence["artifact_metadata"]["evidence_kind"] == "page_read"
        metadata = json.loads(storage.retrieve(session, evidence["metadata_evidence_id"]))
        assert metadata["body_evidence_id"] == evidence["id"]
        assert metadata["raw_object_ref"] == evidence["object_key"]
        assert metadata["content_hash"] == artifact.content_hash
        assert metadata["content_type"] == "text/html"
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 1
    assert requests == ["/company"]
    other = ctx(database)
    with (
        database.tenant(other.actor_id, str(other.workspace_id)) as session,
        pytest.raises(BlobUnavailable),
    ):
        storage.retrieve(session, evidence["id"])


@pytest.mark.parametrize(
    "path,code",
    [
        ("/large", "budget_exhausted"),
        ("/slow", "source_unavailable"),
        ("/challenge", "challenge_detected"),
        ("/denied", "access_denied"),
        ("/rate", "rate_limited"),
        ("/private", "access_denied"),
    ],
)
def test_source_failures_are_bounded_and_typed(database, proxy, path, code):
    endpoint, requests, _ = proxy
    fetcher = HTTPFetcher(
        database,
        trusted_proxy_url=endpoint,
        max_body_bytes=2000 if path == "/large" else 5000,
        timeout_seconds=0.05 if path == "/slow" else 2,
    )
    with pytest.raises(FetchUnavailable) as failure:
        fetcher.fetch(
            ctx(database), "http://example.com" + path, source="web", operation_key=uuid4().hex
        )
    assert failure.value.failure.code == code
    assert len(requests) == 1


def test_manual_redirect_each_hop_counts_and_is_guarded(database, proxy):
    endpoint, requests, _ = proxy
    context = ctx(database)
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context, "http://example.com/redirect", source="web", operation_key=uuid4().hex
    )
    assert artifact.attempts == 2 and artifact.final_url.endswith("/company")
    assert requests == ["/redirect", "/company"]
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 2


def test_per_url_attempts_and_operation_replay_do_not_repeat_io(database, proxy):
    endpoint, requests, _ = proxy
    context = ctx(database)
    fetcher = HTTPFetcher(database, trusted_proxy_url=endpoint)
    first_key = uuid4().hex
    for index in range(3):
        artifact = fetcher.fetch(
            context,
            "http://example.com/company",
            source="web",
            operation_key=first_key if index == 0 else uuid4().hex,
        )
        time.sleep(max(0.02, artifact.network_seconds * 2))
    with pytest.raises(FetchUnavailable) as blocked:
        fetcher.fetch(
            context, "http://example.com/company", source="web", operation_key=uuid4().hex
        )
    assert blocked.value.failure.code == "budget_exhausted"
    with pytest.raises(FetchUnavailable) as replay:
        fetcher.fetch(context, "http://example.com/company", source="web", operation_key=first_key)
    assert replay.value.failure.code == "access_denied"
    assert len(requests) == 3
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 3


def test_cancelled_and_foreign_artifacts_cannot_be_persisted(database, proxy, tmp_path):
    endpoint, _, _ = proxy
    context = ctx(database)
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context, "http://example.com/company", source="web", operation_key=uuid4().hex
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    other = ctx(database)
    with (
        database.tenant(other.actor_id, str(other.workspace_id)) as session,
        pytest.raises(PermissionError),
    ):
        artifact.persist(session, storage)
    from skriller.jobs.control import cancel

    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        cancel(session, str(context.job_id))
    with (
        database.tenant(context.actor_id, str(context.workspace_id)) as session,
        pytest.raises(FetchUnavailable),
    ):
        artifact.persist(session, storage)
    assert not list(tmp_path.rglob("evidence/*"))


def test_cancelled_job_is_denied_before_any_request_or_reservation(database, proxy):
    from skriller.jobs.control import cancel

    endpoint, requests, _ = proxy
    context = ctx(database)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        cancel(session, str(context.job_id))
    with pytest.raises(FetchUnavailable) as denied:
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            context, "http://example.com/company", source="web", operation_key=uuid4().hex
        )
    assert denied.value.failure.code == "deadline_exceeded"
    assert requests == []
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 0


@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded", "disabled"])
async def test_actual_async_fetch_stops_idle_headers_within_five_seconds(
    database, proxy, monkeypatch, stop, caplog
):
    from curl_cffi.requests import AsyncSession

    from skriller.connectors.switches import set_disabled
    from skriller.db.schema import evidence, jobs, reservations
    from skriller.jobs.control import cancel

    endpoint, requests, _ = proxy
    context = ctx(database)
    releases = []
    original = AsyncSession.release_curl

    def release_curl(self, curl):
        original(self, curl)
        releases.append(True)

    monkeypatch.setattr(AsyncSession, "release_curl", release_curl)
    fetcher = HTTPFetcher(database, trusted_proxy_url=endpoint, timeout_seconds=20)
    task = asyncio.create_task(
        fetcher.afetch(
            context, "http://example.com/idle-headers", source="web", operation_key=uuid4().hex
        )
    )

    def persist_stop():
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            if stop == "cancelled":
                cancel(session, str(context.job_id))
            elif stop == "disabled":
                set_disabled(session, "web", "read", True)
            else:
                session.execute(
                    sa.update(jobs)
                    .where(jobs.c.id == str(context.job_id))
                    .values(created_at=sa.func.now() - sa.text("interval '1 hour'"))
                )

    try:
        async with asyncio.timeout(3):
            while not requests:
                await asyncio.sleep(0.01)
        started = time.monotonic()
        await asyncio.to_thread(persist_stop)
        with pytest.raises(FetchUnavailable) as caught:
            await asyncio.wait_for(task, 5)
        assert time.monotonic() - started < 5
        assert caught.value.failure.code == (
            "unsupported_operation" if stop == "disabled" else stop
        )
        assert requests == ["/idle-headers"] and releases == [True]
        assert "idle-headers" not in caplog.text
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            rows = session.execute(sa.select(reservations)).mappings().all()
            assert len(rows) == 1
            assert rows[0]["reconciliation_status"] == "estimated"
            assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 1
            assert (
                session.execute(sa.select(sa.func.count()).select_from(evidence)).scalar_one() == 0
            )
        with pytest.raises(FetchUnavailable):
            await fetcher.afetch(
                context, "http://example.com/company", source="web", operation_key=uuid4().hex
            )
        assert requests == ["/idle-headers"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_sync_fetch_rejects_active_loop_before_creating_coroutine(database, proxy):
    endpoint, requests, _ = proxy
    with pytest.raises(RuntimeError, match="afetch"):
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            ctx(database), "http://example.com/company", source="web", operation_key=uuid4().hex
        )
    assert requests == []


async def test_async_fetch_caller_cancellation_keeps_dispatched_usage(database, proxy):
    from skriller.db.schema import reservations

    endpoint, requests, _ = proxy
    context = ctx(database)
    task = asyncio.create_task(
        HTTPFetcher(database, trusted_proxy_url=endpoint).afetch(
            context, "http://example.com/idle-headers", source="web", operation_key=uuid4().hex
        )
    )
    try:
        async with asyncio.timeout(3):
            while not requests:
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert requests == ["/idle-headers"]
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            rows = session.execute(sa.select(reservations)).mappings().all()
            assert len(rows) == 1 and rows[0]["reconciliation_status"] == "estimated"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
