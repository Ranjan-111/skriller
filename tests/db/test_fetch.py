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


@pytest.fixture
def proxy(monkeypatch):
    from skriller.settings import Settings

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
            status = 200
            body, extras = company, {}
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
            self.send_header("Content-Type", "text/html; charset=utf-8")
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
