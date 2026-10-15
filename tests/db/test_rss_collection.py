"""Actual copied HTTP/proxy/feedparser into scoped private evidence and API."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from fastapi.testclient import TestClient
from test_research_workflow import isolate_capacity

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.search import SearchHit, SearchPage
from skriller.db import ResearchRepository
from skriller.db.schema import attempts, evidence
from skriller.erasure import erase
from skriller.jobs.budget import current_usage
from skriller.jobs.worker import CheckpointWorker
from skriller.research.collection import execute_collection
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def prepare(database, monkeypatch, endpoint, path, *, source_url=None):
    actor = str(uuid4())
    app = create_app(Settings(public_collection_proxy_url=endpoint))
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={}).json()
    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": "Find public RSS feeds",
            "options": {"sources": ["rss"], "result_limit": 10},
        },
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    isolate_capacity(monkeypatch, task["job_id"])
    scheduled = CheckpointWorker(database, {}).schedule(task)

    class Provider:
        async def search(self, query, **kwargs):
            return SearchPage(
                hits=[
                    SearchHit(
                        title="Feed reference",
                        url=source_url or f"http://example.com/{path}",
                        snippet="Indexed feed",
                        rank=1,
                    )
                ],
                rejected=0,
                truncated=False,
            )

    execute_discovery(
        database,
        {**task, "attempt_id": scheduled["attempt_id"]},
        Provider(),
        collection_proxy_url=endpoint,
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        row = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "collecting"
                )
            )
            .mappings()
            .one()
        )
    task["attempt_id"] = row["id"]
    return client, task, row["logical_key"].removeprefix("collecting:")


def test_rss_ingestion_preserves_dates_ids_bounds_no_follow_and_replay(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    client, task, entity_id = prepare(database, monkeypatch, endpoint, "rss")
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    assert (
        execute_collection(database, task, endpoint, storage=storage, enable_extraction=True)[
            "status"
        ]
        == "checkpointed"
    )
    execute_collection(database, task, endpoint, storage=storage)
    assert requests == ["/rss"]
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 1 and results[0]["qualification"] == "unverified"
    feed = results[0]["feed"]
    assert [entry["entry_id"] for entry in feed["entries"]] == ["story-1", "story-2"]
    assert feed["entries"][0]["published_at"].startswith("2026-10-12T11:00:00")
    assert feed["entries"][0]["updated_at"] is None
    assert feed["entries"][1]["published_at"] is None
    assert feed["entries"][1]["updated_at"].startswith("2026-10-13T12:00:00")
    assert feed["duplicate_count"] == 1 and feed["invalid_link_count"] == 1
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        content = storage.retrieve(session, entity["attributes"]["_collection_body_evidence_id"])
        assert b"<feed" in content
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 1
        assert not ResearchRepository.claims_for(session, entity_id)
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(attempts)
                .where(attempts.c.job_id == task["job_id"], attempts.c.stage == "extracting")
            ).scalar_one()
            == 0
        )
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == entity["attributes"]["_collection_body_evidence_id"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    stale = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]["feed"]
    assert stale["entries"] == [] and stale["evidence_expired"]
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        erase(session, storage, entity_id, request_key="erase-feed")
    assert client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"] == []


@pytest.mark.parametrize("path,readable", [("rss-empty", True), ("rss-bad", False)])
def test_empty_feed_differs_from_invalid_xml(
    database, monkeypatch, proxy, tmp_path, path, readable
):
    endpoint, requests, _ = proxy
    client, task, _ = prepare(database, monkeypatch, endpoint, path)
    execute_collection(
        database, task, endpoint, storage=EvidenceStorage(LocalBlobBackend(tmp_path))
    )
    result = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]
    assert (result["collection"]["status"] == "read") == readable
    assert (result.get("feed") is not None) == readable
    if readable:
        assert result["feed"]["entries"] == []
    assert requests == ["/" + path]


@pytest.mark.live
def test_one_live_public_feed_through_guarded_pipeline(database, monkeypatch):
    import json
    from pathlib import Path

    endpoint = "http://127.0.0.1:18080"
    client, task, entity_id = prepare(
        database, monkeypatch, endpoint, "", source_url="https://www.python.org/downloads/feed.rss"
    )
    storage = EvidenceStorage(LocalBlobBackend(Settings().object_directory))
    result = execute_collection(database, task, endpoint, storage=storage, enable_extraction=True)
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        assert entity["attributes"]["collection"]["status"] == "read", entity["attributes"][
            "collection"
        ]
        feed = entity["attributes"]["feed"]
        assert 0 < len(feed["entries"]) <= 10
        counters = current_usage(session, task["job_id"])[1]
        assert 1 <= counters["fetch_attempts"] <= 3
        assert not ResearchRepository.claims_for(session, entity_id)
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert (
        response.status_code == 200
        and response.json()["results"][0]["qualification"] == "unverified"
    )
    Path("docs/completions/RSS-COLLECTION-LIVE.json").write_text(
        json.dumps(
            {
                "status": result["status"],
                "source": "official public Python releases RSS",
                "route": "copied Scrapling session through local GuardedProxy and feedparser",
                "entries": len(feed["entries"]),
                "omitted_entry_count": feed["omitted_entry_count"],
                "fetch_attempts": counters["fetch_attempts"],
                "followup_fetches": 0,
                "model_calls": 0,
                "lead_fit": "unverified",
                "currency_cost": 0,
            },
            indent=2,
        )
        + "\n"
    )
