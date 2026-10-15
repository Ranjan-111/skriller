"""Real tenant jobs, budget ledger and timestamped video evidence; fixture source I/O."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_research_workflow import isolate_capacity

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.search import SearchHit, SearchPage
from skriller.connectors.youtube import (
    YouTubeReadEvidence,
    YouTubeUnavailable,
    parse_metadata_output,
)
from skriller.connectors.youtube_executor import ConcreteYouTubeExecutor
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.schema import attempts, evidence
from skriller.jobs.budget import current_usage, reconcile, reserve
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
URL = "https://www.youtube.com/watch?v=fixture123"
PROXY = "http://127.0.0.1:18080"


def prepare(database, monkeypatch, *, url=URL):
    actor = str(uuid4())
    app = create_app(Settings(public_collection_proxy_url=PROXY))
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={}).json()
    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": "Research public YouTube videos",
            "options": {"sources": ["youtube"], "result_limit": 10},
        },
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    isolate_capacity(monkeypatch, accepted["job_id"])
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    scheduled = CheckpointWorker(database, {}).schedule(task)

    class Provider:
        async def search(self, query, **kwargs):
            return SearchPage(
                hits=[SearchHit(title="Indexed video", url=url, snippet="A reference", rank=1)],
                rejected=0,
                truncated=False,
            )

    execute_discovery(
        database,
        {**task, "attempt_id": scheduled["attempt_id"]},
        Provider(),
        collection_proxy_url=PROXY,
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
    entity_id = row["logical_key"].removeprefix("collecting:")
    original = collection.collection_handler

    def isolated(*args, **kwargs):
        return replace(
            original(*args, **kwargs),
            capacity_source="yt-" + task["job_id"].replace("-", ""),
            capacity_host=task["job_id"] + ".example.invalid",
        )

    monkeypatch.setattr(collection, "collection_handler", isolated)
    return client, task, entity_id


class Reader:
    def __init__(self, *, captions=True, fail=False):
        self.calls, self.captions, self.fail = 0, captions, fail

    def execute(self, url, *, timeout, cancel_check):
        assert url == URL and timeout <= 50 and cancel_check() is False
        self.calls += 1
        if self.fail:
            raise YouTubeUnavailable("must-not-leak-private-source-error")
        observed = datetime.now(UTC)
        metadata = parse_metadata_output(
            json.dumps(
                {
                    "id": "fixture123",
                    "webpage_url": URL,
                    "title": "Fixture creator video",
                    "view_count": 12,
                    "subtitles": {"en": [{}]} if self.captions else {},
                }
            ),
            requested_url=URL,
            observed_at=observed,
        )
        return YouTubeReadEvidence.model_validate(
            {
                "metadata": metadata,
                "metadata_truncated": False,
                "caption_status": "retrieved" if self.captions else "unavailable",
                "caption_origin": "provided" if self.captions else None,
                "caption_language": "en" if self.captions else None,
                "segments": [
                    {
                        "start_seconds": 1.25,
                        "end_seconds": 3.5,
                        "text": "We build public tools.",
                        "source_url": URL,
                        "observed_at": observed,
                    }
                ]
                if self.captions
                else [],
                "request_count": 3,
                "backend_request_count": 2,
            }
        )


@pytest.mark.live
def test_public_video_through_guarded_worker_to_scoped_caption_citation(
    database, monkeypatch, tmp_path
):
    image = os.environ.get("SKRILLER_YOUTUBE_LIVE_IMAGE")
    if not image:
        pytest.skip("Requires explicit immutable public YouTube worker image")
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    client, task, entity_id = prepare(database, monkeypatch, url=url)
    result = collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        youtube_reader=ConcreteYouTubeExecutor(image),
    )
    assert result["status"] == "checkpointed", result
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200
    row = response.json()["results"][0]
    video = row["youtube"]
    assert video["metadata"]["source_url"] == url
    assert video["metadata"]["counter_scope"] == "public_metadata"
    assert video["caption_status"] == "retrieved" and 0 < len(video["segments"]) <= 20
    assert video["subject_identity"] == "unknown" and row["fit"]["status"] == "excluded"
    segment = video["segments"][0]
    citation = client.get(f"/v1/jobs/{task['job_id']}/evidence/{segment['evidence_id']}")
    assert citation.status_code == 200
    cited = citation.json()
    assert cited["source_url"] == url + "&t=" + str(int(segment["start_seconds"]))
    assert segment["text"] in cited["excerpt"] and cited["source_platform"] == "youtube"
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        counters = current_usage(session, task["job_id"])[1]
        entity = ResearchRepository.get_entity(session, entity_id)
        assert entity["attributes"]["collection"]["status"] == "read"
        assert 1 <= counters["fetch_attempts"] <= 12
    # Only scalar acceptance facts are published; source caption text stays scoped.
    Path("docs/completions/YOUTUBE-COLLECTION-LIVE.json").write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(UTC).isoformat(),
                "image": image,
                "status": result["status"],
                "source_url": url,
                "metadata_live_verified": True,
                "caption_live_verified": True,
                "caption_origin": video["caption_origin"],
                "caption_language": video["caption_language"],
                "retained_caption_cues": len(video["segments"]),
                "timestamped_scoped_citation_verified": True,
                "fetch_attempts": counters["fetch_attempts"],
                "creator_identity": "unknown",
                "lead_fit": row["fit"]["status"],
                "model_calls": 0,
                "limitation": "One public video verifies this operation, not platform-wide source coverage.",
            },
            indent=2,
        )
        + "\n"
    )


def test_video_collection_persists_timed_citation_and_budget_without_promoting_creator(
    database, monkeypatch, tmp_path
):
    client, task, entity_id = prepare(database, monkeypatch)
    reader = Reader()
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    outcome = collection.execute_collection(
        database, task, PROXY, storage=storage, youtube_reader=reader
    )
    assert outcome["status"] == "checkpointed"
    collection.execute_collection(database, task, PROXY, storage=storage, youtube_reader=reader)
    assert reader.calls == 1
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    assert row["youtube"]["subject_identity"] == "unknown"
    assert row["youtube"]["metadata"]["counter_scope"] == "public_metadata"
    assert row["fit"]["status"] == "excluded" and row["qualification"] == "unverified"
    segment = row["youtube"]["segments"][0]
    citation_url = f"/v1/jobs/{task['job_id']}/evidence/{segment['evidence_id']}"
    citation = client.get(citation_url)
    assert citation.status_code == 200, citation.text
    assert "1.250s–3.500s" in citation.json()["excerpt"]
    assert citation.json()["source_url"] == URL + "&t=1"
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 3
        entity = ResearchRepository.get_entity(session, entity_id)
        ids = [entity["attributes"]["_collection_body_evidence_id"], segment["evidence_id"]]
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id.in_(ids))
            .values(expires_at=sa.func.now() - sa.text("interval '1 second'"))
        )
    expired = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]["youtube"]
    assert expired["metadata"] is None and expired["segments"] == [] and expired["evidence_expired"]
    assert client.get(citation_url).status_code == 404


def test_missing_captions_retains_metadata_without_generated_text(database, monkeypatch, tmp_path):
    client, task, _ = prepare(database, monkeypatch)
    collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        youtube_reader=Reader(captions=False),
    )
    video = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]["youtube"]
    assert video["metadata"]["view_count"] == 12
    assert video["caption_status"] == "unavailable" and video["segments"] == []


def test_unknown_source_failure_uses_shared_estimated_budget_and_no_private_error(
    database, monkeypatch, tmp_path
):
    client, task, _ = prepare(database, monkeypatch)
    result = collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        youtube_reader=Reader(fail=True),
    )
    assert result["status"] == "source_unavailable"
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 12
    result = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert "must-not-leak" not in result.text
    assert result.json()["results"][0]["youtube"] is None


def test_job_fetch_limit_is_checked_before_starting_youtube_worker(database, monkeypatch, tmp_path):
    _, task, _ = prepare(database, monkeypatch)
    reader = Reader()
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        job = JobRepository.get(session, task["job_id"])
        plan = ConversationRepository.get_plan(session, job["plan_id"])["interpretation"]
        spent = plan["limits"]["fetch_attempts"] - 2
        held = reserve(session, task["job_id"], "fixture-spent", 0, {"fetch_attempts": spent})
        reconcile(
            session,
            task["job_id"],
            held["id"],
            status="confirmed",
            cost=0,
            actual_dimensions={"fetch_attempts": spent},
        )
    result = collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        youtube_reader=reader,
    )
    assert result["status"] == "budget_exhausted" and reader.calls == 0


def test_source_switch_stops_video_io_without_charging_fetch_attempts(
    database, monkeypatch, tmp_path
):
    from skriller.connectors.switches import set_disabled

    _, task, _ = prepare(database, monkeypatch)
    reader = Reader()
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        set_disabled(session, "youtube", "read", True)
    collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        youtube_reader=reader,
    )
    assert reader.calls == 0
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 0
