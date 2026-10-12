from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.db import ConversationRepository, JobRepository
from skriller.progress import database_for
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def setup_progress(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Progress")
    with database.tenant(actor, workspace["id"]) as session:
        conversation = ConversationRepository.create(session, "Read")
        plan = ConversationRepository.revise_plan(session, conversation["id"], {"query": "fintech"})
        job = JobRepository.create(session, conversation["id"], plan["id"], str(uuid4()))
        JobRepository.transition(session, job["id"], "queued")
        JobRepository.transition(session, job["id"], "running", stage="discovering")
        JobRepository.event(session, job["id"], "candidate", "candidate_collected", {"count": 1})
        JobRepository.transition(
            session, job["id"], "completed", terminal_reason="source_exhausted"
        )
        rows = JobRepository.events_after(session, job["id"])
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    app.dependency_overrides[database_for] = lambda: database
    return TestClient(app), app, workspace["id"], job["id"], rows


def test_progress_replays_persisted_events_once_and_snapshot(database):
    client, _app, workspace, job, rows = setup_progress(database)
    base = f"/v1/workspaces/{workspace}/jobs/{job}"
    response = client.get(base + "/events")
    assert response.status_code == 200
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == [row["sequence"] for row in rows]
    assert '"count":1' in response.text
    response = client.get(base + "/events", headers={"Last-Event-ID": str(ids[1])})
    assert [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")] == ids[
        2:
    ]
    assert client.get(base + "/events", headers={"Last-Event-ID": str(ids[-1])}).text == ""
    assert client.get(base).json()["state"] == "completed"


def test_progress_rejects_cross_tenant_and_bad_credentials_or_cursor(database):
    client, app, workspace, job, _rows = setup_progress(database)
    base = f"/v1/workspaces/{workspace}/jobs/{job}"
    assert client.get(base + "/events", headers={"Last-Event-ID": "-1"}).status_code == 400
    assert client.get(base + "/events?access_token=secret").status_code == 400
    other = database.create_workspace("other-actor", "Other")
    assert client.get(f"/v1/workspaces/{other['id']}/jobs/{job}/events").status_code == 404
    app.dependency_overrides[require_identity] = lambda: Identity("other-actor")
    assert client.get(base + "/events").status_code == 404
    assert client.get(base).status_code == 404
    app.dependency_overrides.clear()
    assert client.get(base + "/events").status_code == 401


def test_replay_drains_multiple_batches_before_terminal_close(database):
    client, app, workspace, job, _rows = setup_progress(database)
    actor = app.dependency_overrides[require_identity]().uid
    with database.tenant(actor, workspace) as session:
        for index in range(105):
            JobRepository.event(session, job, f"detail:{index}", "evidence_saved", {"index": index})
        expected = [row["sequence"] for row in JobRepository.events_after(session, job, limit=200)]
    response = client.get(f"/v1/workspaces/{workspace}/jobs/{job}/events")
    actual = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert actual == expected
    assert len(actual) > 100


def test_concurrent_event_sequences_cannot_commit_out_of_order(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from skriller.db import Database

    client, app, workspace, job, rows = setup_progress(database)
    actor = app.dependency_overrides[require_identity]().uid
    concurrent = Database(database.engine.url, pool_size=3)
    allocated = Event()
    release = Event()
    second_allocated = Event()

    def first():
        with concurrent.tenant(actor, workspace) as session:
            row = JobRepository.event(session, job, "concurrent:first", "first")
            allocated.set()
            assert release.wait(3)
            return row["sequence"]

    def second():
        with concurrent.tenant(actor, workspace) as session:
            row = JobRepository.event(session, job, "concurrent:second", "second")
            second_allocated.set()
            return row["sequence"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            assert allocated.wait(2)
            two = pool.submit(second)
            try:
                assert not second_allocated.wait(0.1)
                with concurrent.tenant(actor, workspace) as session:
                    assert not JobRepository.events_after(session, job, rows[-1]["sequence"])
            finally:
                release.set()
            first_id, second_id = one.result(timeout=3), two.result(timeout=3)
        assert first_id < second_id
        replay = client.get(
            f"/v1/workspaces/{workspace}/jobs/{job}/events",
            headers={"Last-Event-ID": str(rows[-1]["sequence"])},
        )
        assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == [
            first_id,
            second_id,
        ]
    finally:
        release.set()
        concurrent.dispose()
