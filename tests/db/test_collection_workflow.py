"""Actual copied HTTP/cleanup engines, proxy, blobs and tenant checkpoints."""

from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from test_research_workflow import isolate_capacity, prepare

from skriller.connectors.search import SearchHit, SearchPage
from skriller.db import JobRepository, ResearchRepository
from skriller.db.schema import attempts, evidence
from skriller.jobs.budget import current_usage
from skriller.jobs.worker import CheckpointWorker
from skriller.research.collection import execute_collection
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


class Provider:
    def __init__(self, paths):
        self.paths = paths
        self.calls = 0

    async def search(self, query, **options):
        self.calls += 1
        hits = (
            []
            if options["domains"]
            else [
                SearchHit(
                    title="Fixture company",
                    url=f"http://example.com/{path}",
                    snippet="An indexed reference",
                    rank=index + 1,
                )
                for index, path in enumerate(self.paths)
            ]
        )
        return SearchPage(hits=hits, rejected=0, truncated=False)


def discover(database, monkeypatch, actor, endpoint, paths, *, extraction=False):
    _, client, accepted = prepare(
        database,
        monkeypatch,
        actor,
        settings=Settings(public_collection_proxy_url=endpoint, enable_page_extraction=extraction),
    )
    isolate_capacity(monkeypatch, accepted["job_id"])
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    scheduled = CheckpointWorker(database, {}).schedule(task)
    task["attempt_id"] = scheduled["attempt_id"]
    provider = Provider(paths)
    result = execute_discovery(database, task, provider, collection_proxy_url=endpoint)
    assert result["status"] == "checkpointed"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        pending = (
            session.execute(
                sa.select(attempts)
                .where(
                    attempts.c.job_id == accepted["job_id"],
                    attempts.c.stage == "collecting",
                )
                .order_by(attempts.c.logical_key)
            )
            .mappings()
            .all()
        )
        assert JobRepository.get(session, accepted["job_id"])["stage"] == "collecting"
    tasks = [{**task, "attempt_id": row["id"]} for row in pending]
    return client, accepted, task, tasks, provider


def test_discovery_actual_read_cleanup_private_evidence_and_replay(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, source = proxy
    actor = f"collection-{uuid4()}"
    client, accepted, discovery, tasks, provider = discover(
        database, monkeypatch, actor, endpoint, ["company"]
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    assert client.get(f"/v1/jobs/{accepted['job_id']}").json()["state"] == "running"
    execute_discovery(database, discovery, provider, collection_proxy_url=endpoint)
    assert provider.calls == 2
    assert (
        execute_collection(database, tasks[0], endpoint, storage=storage)["status"]
        == "checkpointed"
    )
    assert (
        execute_collection(database, tasks[0], endpoint, storage=storage)["status"]
        == "checkpointed"
    )
    assert requests == ["/company"]
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results")
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert response.json()["state"] == "completed"
    assert result["collection"]["status"] == "read" and result["collection"]["prepared_chunks"] > 0
    assert result["qualification"] == "unverified" and result["evidence_kind"] == "search_snippet"
    assert "object_key" not in response.text and "_collection_" not in response.text
    with database.tenant(actor, accepted["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, result["id"])
        assert (
            storage.retrieve(session, entity["attributes"]["_collection_body_evidence_id"])
            == source
        )
        assert current_usage(session, accepted["job_id"])[1]["fetch_attempts"] == 1
        assert session.execute(sa.select(sa.func.count()).select_from(evidence)).scalar_one() == 2
    assert len(list(Path(tmp_path).rglob("evidence/*"))) == 2


def test_collection_failure_retains_reference_and_finishes_only_after_all_attempts(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    actor = f"collection-failure-{uuid4()}"
    client, accepted, _, tasks, _ = discover(
        database, monkeypatch, actor, endpoint, ["company", "challenge"]
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    execute_collection(database, tasks[0], endpoint, storage=storage)
    assert client.get(f"/v1/jobs/{accepted['job_id']}").json()["state"] == "running"
    execute_collection(database, tasks[1], endpoint, storage=storage)
    data = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert data["state"] == "partial" and len(data["results"]) == 2
    failed = next(row for row in data["results"] if row["url"].endswith("/challenge"))
    assert failed["collection"]["failure_code"] == "challenge_detected"
    assert len(requests) == 2
    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert current_usage(session, accepted["job_id"])[1]["fetch_attempts"] == 2
        assert session.execute(sa.select(sa.func.count()).select_from(evidence)).scalar_one() == 2


def test_cancelled_collection_does_not_fetch_or_store(database, monkeypatch, proxy, tmp_path):
    endpoint, requests, _ = proxy
    actor = f"collection-cancel-{uuid4()}"
    client, accepted, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, ["company"])
    assert client.post(f"/v1/jobs/{accepted['job_id']}/cancel").status_code == 200
    result = execute_collection(
        database, tasks[0], endpoint, storage=EvidenceStorage(LocalBlobBackend(tmp_path))
    )
    assert result["status"] == "not_dispatchable" and not requests
    assert not list(Path(tmp_path).rglob("evidence/*"))


def test_platform_url_cannot_use_generic_public_collection(database, monkeypatch, proxy, tmp_path):
    from skriller.db.schema import entities

    endpoint, requests, _ = proxy
    actor = f"collection-platform-{uuid4()}"
    client, accepted, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, ["company"])
    with database.tenant(actor, accepted["workspace_id"]) as session:
        row = session.execute(sa.select(entities)).mappings().one()
        session.execute(
            sa.update(entities)
            .where(entities.c.id == row["id"])
            .values(
                attributes={
                    **row["attributes"],
                    "url": "https://www.linkedin.com/in/synthetic-fixture",
                }
            )
        )
    execute_collection(
        database, tasks[0], endpoint, storage=EvidenceStorage(LocalBlobBackend(tmp_path))
    )
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert result["state"] == "partial"
    assert result["results"][0]["collection"]["failure_code"] == "unsupported_operation"
    assert not requests and not list(Path(tmp_path).rglob("evidence/*"))


def test_collection_rejects_foreign_task_identity_before_io(database, monkeypatch, proxy, tmp_path):
    from skriller.db import WorkspaceAccessDenied

    endpoint, requests, _ = proxy
    actor = f"collection-owner-{uuid4()}"
    _, _, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, ["company"])
    with pytest.raises(WorkspaceAccessDenied):
        execute_collection(
            database,
            {**tasks[0], "actor_id": f"foreign-{uuid4()}"},
            endpoint,
            storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        )
    assert not requests


@pytest.mark.parametrize(
    "path,rendered", [("dynamic", True), ("challenge", False), ("login200", False)]
)
def test_only_js_shell_escalates_through_bounded_browser_adapter(
    database, monkeypatch, proxy, tmp_path, path, rendered
):
    from test_browser import FixtureExecutor

    from skriller.connectors.browser import DynamicBrowserAdapter

    endpoint, requests, _ = proxy
    actor = f"collection-render-{uuid4()}"
    client, accepted, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, [path])
    executor = FixtureExecutor()
    browser = DynamicBrowserAdapter(database, executor=executor, isolation_verified=True)
    execute_collection(
        database,
        tasks[0],
        endpoint,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        browser=browser,
    )
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    collection = result["results"][0]["collection"]
    assert requests == [f"/{path}"] and bool(executor.requests) is rendered
    assert collection["status"] == ("read" if rendered else "unavailable")
    if rendered:
        assert collection["browser_seconds"] == 0.01 and collection["network_seconds"] is None
        assert executor.requests[0].max_requests == 3
        with database.tenant(actor, accepted["workspace_id"]) as session:
            assert current_usage(session, accepted["job_id"])[1]["fetch_attempts"] == 3


def test_actual_isolated_chromium_collecting_stage_js_escalation(
    database, monkeypatch, proxy, tmp_path
):
    import os

    from skriller.connectors import browser_executor as module
    from skriller.connectors.browser import DynamicBrowserAdapter
    from skriller.connectors.browser_executor import ConcreteBrowserExecutor

    image = os.environ.get("SKRILLER_BROWSER_TEST_IMAGE")
    if not image:
        pytest.skip("Requires installed immutable isolated browser fixture image")
    endpoint, requests, _ = proxy
    actor = f"collecting-chromium-{uuid4()}"
    client, accepted, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, ["dynamic"])
    html = (Path(__file__).parents[1] / "fixtures/research/dynamic.html").read_text()
    # Reuse the existing browser container fixture pattern: only this test
    # replaces the fixed child command to serve one synthetic public page.
    code = f"""
import base64,json,logging,pathlib
logging.disable(logging.CRITICAL)
import skriller.connectors.browser as browser
original=browser.copied_engine_options
html={html!r}
def options(request,setup):
    def fixture_setup(page):
        setup(page)
        page.route('http://example.com/dynamic',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
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
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    browser = DynamicBrowserAdapter(
        database, executor=ConcreteBrowserExecutor(image), isolation_verified=True
    )
    outcome = execute_collection(database, tasks[0], endpoint, storage=storage, browser=browser)
    assert outcome["status"] == "checkpointed" and len(launched) == 1 and requests == ["/dynamic"]
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert result["state"] == "completed"
    row = result["results"][0]
    assert row["collection"]["status"] == "read" and row["collection"]["browser_seconds"] > 0
    with database.tenant(actor, accepted["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, row["id"])
        body = storage.retrieve(session, entity["attributes"]["_collection_body_evidence_id"])
        assert b"Aurora Ledger" in body and b"Mira Rao" in body
        assert current_usage(session, accepted["job_id"])[1]["fetch_attempts"] == 2
