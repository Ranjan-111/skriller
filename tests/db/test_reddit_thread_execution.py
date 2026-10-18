"""Real tenant and durable thread evidence with synthetic worker responses."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from test_reddit_continuation import listing, prepared
from test_research_workflow import Provider, isolate_capacity

from skriller.connections.lifecycle import reconnect
from skriller.connections.store import SecretPayload
from skriller.connectors.reddit_executor import RedditUnavailable
from skriller.connectors.reddit_request import RedditRead
from skriller.connectors.switches import set_disabled
from skriller.db.schema import attempts, entities, evidence
from skriller.erasure import erase
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.page_extraction import execute_page_extraction
from skriller.research.service import execute_discovery
from skriller.security.runner import RunResult
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


class Runner:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def run(self, operation, target, **kwargs):
        assert not kwargs["cancel_check"]()
        assert kwargs["credential_material"].injection() == {
            "REDDIT_ACCESS_TOKEN": "fixture-access-token"
        }
        self.calls.append(operation)
        post = listing(1, after=None)
        if operation == "reddit_oauth_read":
            request = RedditRead.model_validate_json(target)
            assert request.post_id == "abc001" and request.subreddit == "startups"
            payload = [
                post,
                {
                    "kind": "Listing",
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "com123",
                                    "name": "t1_com123",
                                    "link_id": "t3_abc001",
                                    "parent_id": "t3_abc001",
                                    "author": "anonymous_handle",
                                    "body": "A queue problem",
                                    "created_utc": 1700000000,
                                    "replies": "",
                                },
                            }
                        ]
                    },
                },
            ]
        else:
            assert operation == "reddit_oauth_search"
            payload = post
        if self.callback:
            self.callback()
        return RunResult("completed", 0, json.dumps(payload), "", 1)


@pytest.mark.parametrize("change", [None, "disabled", "rotated_during_read", "wrong_generation"])
def test_connected_read_checks_authority_before_and_after_io(database, monkeypatch, change):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)

    def rotate():
        with database.tenant(actor, accepted["workspace_id"]) as session:
            reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials={"access_token": "replacement"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    runner = Runner(rotate if change == "rotated_during_read" else None)
    reader.runner = runner
    with database.tenant(actor, accepted["workspace_id"]) as session:
        material = store.load_for_runner(session, context, "reddit_oauth_read")
        if change == "disabled":
            set_disabled(session, "reddit", "read", True)
    if change == "wrong_generation":
        rotate()
    call = lambda: reader.read(
        RedditRead(post_id="abc001", subreddit="startups"),
        database=database,
        store=store,
        context=context,
        expected_credential_ref=material.credential_ref,
    )
    if change is None:
        page = call()
        assert page.comments[0].text == "A queue problem"
        assert page.buying_intent == "not_inferred"
    else:
        with pytest.raises(RedditUnavailable):
            call()
        assert len(runner.calls) == (1 if change == "rotated_during_read" else 0)


@pytest.mark.parametrize("lifecycle", ["expiry", "comment_erasure", "signals"])
def test_durable_native_thread_evidence_expiry_and_checkpoint_replay(
    database, monkeypatch, tmp_path, lifecycle
):
    actor, client, accepted, store, _, reader = prepared(
        database,
        monkeypatch,
        settings=Settings(
            public_reddit_image="sha256:" + "a" * 64,
            public_collection_proxy_url="http://127.0.0.1:18080",
            enable_page_extraction=lifecycle == "signals",
        ),
    )
    reader.runner = runner = Runner()
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    isolate_capacity(monkeypatch, task["job_id"])
    scheduled = CheckpointWorker(database, {}).schedule(task)
    discovery = execute_discovery(
        database,
        {**task, "attempt_id": scheduled["attempt_id"]},
        Provider(),
        reddit_reader=reader,
        connection_store=store,
        collection_proxy_url="http://127.0.0.1:18080",
    )
    assert discovery["status"] == "checkpointed", discovery
    with database.tenant(actor, task["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "collecting"
                )
            )
            .mappings()
            .one()
        )
        entity_id = attempt["logical_key"].removeprefix("collecting:")
        attributes = session.execute(
            sa.select(entities.c.attributes).where(entities.c.id == entity_id)
        ).scalar_one()
        assert attributes["_read_connection_ref"] and attributes["_read_credential_ref"]
    original = collection.collection_handler
    monkeypatch.setattr(
        collection,
        "collection_handler",
        lambda *args, **kwargs: replace(
            original(*args, **kwargs),
            capacity_source="thread-" + task["job_id"],
            capacity_host=task["job_id"] + ".example.invalid",
        ),
    )
    payload = {**task, "attempt_id": str(attempt["id"])}
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    outcome = collection.execute_collection(
        database,
        payload,
        "http://127.0.0.1:18080",
        storage=storage,
        reddit_reader=reader,
        connection_store=store,
        enable_extraction=lifecycle == "signals",
    )
    assert outcome["status"] == "checkpointed", outcome
    if lifecycle == "signals":

        class Model:
            calls = 0

            async def ainvoke(self, messages, config):
                self.calls += 1
                assert config["callbacks"] == []
                return AIMessage(
                    content=json.dumps(
                        {
                            "signals": [
                                {"resource_id": "t1_com123", "quote": "A queue problem"},
                                {"resource_id": "t3_abc001", "quote": "A queue problem"},
                                {"resource_id": "t1_fake123", "quote": "Invented company"},
                            ]
                        }
                    ),
                    usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                )

        model = Model()
        with database.tenant(actor, task["workspace_id"]) as session:
            extracting = session.execute(
                sa.select(attempts.c.id).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "extracting"
                )
            ).scalar_one()
        extracted = execute_page_extraction(
            database,
            {**task, "attempt_id": str(extracting)},
            storage=storage,
            model=LocalStructuredModel(model_instance=model),
        )
        assert extracted["status"] == "checkpointed", extracted
        assert model.calls == 1
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["reddit_thread"]["thread"]["comments"][0]["text"] == "A queue problem"
    assert result["reddit_thread"]["thread"]["subject_identity"] == "unknown"
    if lifecycle == "signals":
        signals = result["reddit_thread"]["signals"]
        assert len(signals) == 1 and signals[0]["resource_id"] == "t1_com123"
        assert signals[0]["buying_intent"] == "not_inferred"
        assert result["reddit_thread"]["rejected_signals"] == 2
    assert not any(key.startswith("_read") for key in result)
    count = len(runner.calls)
    replay = collection.execute_collection(
        database,
        payload,
        "http://127.0.0.1:18080",
        storage=storage,
        reddit_reader=reader,
        connection_store=store,
    )
    assert replay["status"] == "checkpointed" and len(runner.calls) == count
    with database.tenant(actor, task["workspace_id"]) as session:
        if lifecycle != "comment_erasure":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == result["reddit_thread"]["evidence_id"])
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        else:
            child = session.execute(
                sa.select(entities.c.id).where(
                    entities.c.canonical_key == f"{task['job_id']}:reddit-comment:t1_com123"
                )
            ).scalar_one()
            erase(session, storage, child, request_key="erase-nested-comment")
    current = client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"]
    if lifecycle != "comment_erasure":
        assert current[0]["reddit_thread"] is None
    else:
        assert current == []
