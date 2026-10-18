"""Actual tenant/credential cursor fences and durable paged discovery accounting."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from test_research_workflow import Provider, isolate_capacity, prepare

from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.reddit_continuation import continuations
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.reddit_executor import ConcreteRedditExecutor, RedditUnavailable
from skriller.connectors.reddit_request import RedditCursor, RedditSearch
from skriller.connectors.switches import set_disabled
from skriller.contracts import ExecutionContext
from skriller.db import JobRepository
from skriller.db.schema import reservations
from skriller.jobs.control import cancel
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker
from skriller.research.service import execute_discovery
from skriller.security.runner import RunResult
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def listing(index, *, after):
    identifier = f"abc{index:03}"
    return {
        "kind": "Listing",
        "data": {
            "after": after,
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": identifier,
                        "title": "Source post " + str(index),
                        "subreddit": "startups",
                        "author": "unknown_handle",
                        "selftext": "Source text",
                        "permalink": f"/r/startups/comments/{identifier}/fixture/",
                    },
                }
            ],
        },
    }


class Runner:
    def __init__(self, *, repeat=False, uncertain=False):
        self.calls = []
        self.repeat = repeat
        self.uncertain = uncertain
        self.endless = False
        self.rate_limited = False

    def run(self, operation, target, **kwargs):
        assert operation == "reddit_oauth_search"
        assert not kwargs["cancel_check"]()
        assert kwargs["credential_material"].injection() == {
            "REDDIT_ACCESS_TOKEN": "fixture-access-token"
        }
        request = RedditSearch.model_validate_json(target)
        self.calls.append(request)
        if self.uncertain and len(self.calls) > 1:
            return RunResult("failed", 2, "", "", 0)
        index = len(self.calls)
        if self.rate_limited and index > 1:
            return RunResult(
                "completed",
                0,
                json.dumps({"_skriller_error": "rate_limited", "retry_after_seconds": 120}),
                "",
                0,
            )
        after = "t3_cursor1" if self.repeat or index == 1 else "t3_cursor2" if index == 2 else None
        if self.endless:
            after = f"t3_cursor{index}"
        return RunResult("completed", 0, json.dumps(listing(index, after=after)), "", 1)


def prepared(database, monkeypatch, *, settings=None):
    actor = "reddit-pages-" + uuid4().hex
    settings = settings or Settings(public_reddit_image="sha256:" + "a" * 64)
    _, client, accepted = prepare(
        database, monkeypatch, actor, sources=["reddit"], settings=settings, result_limit=25
    )
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    with database.tenant(actor, accepted["workspace_id"]) as session:
        reference = store.create(
            session,
            "reddit",
            "oauth",
            SecretPayload(credentials={"access_token": "fixture-access-token"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("read", "discover"),
        )
    context = ExecutionContext(
        workspace_id=UUID(accepted["workspace_id"]),
        job_id=UUID(accepted["job_id"]),
        actor_id=actor,
        plan_revision=1,
        connection_ref=reference.id,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        attempt_budget=3,
    )
    reader = ConcreteRedditExecutor("sha256:" + "a" * 64)
    reader.runner = Runner()
    return actor, client, accepted, store, context, reader


def test_opaque_cursor_is_request_bound_single_use_and_replay_does_not_fetch(database, monkeypatch):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)
    request = RedditSearch(query="founder", subreddit="startups", sort="new", time_filter="month")
    first = reader.execute(request, database=database, store=store, context=context)
    assert first.continuation_ref and first.next_cursor is None and first.has_more
    for change in (
        {"query": "different"},
        {"subreddit": "other"},
        {"sort": "top"},
        {"limit": 3},
        {"time_filter": "week"},
    ):
        with pytest.raises(RedditUnavailable):
            reader.execute(
                request.model_copy(update=change),
                database=database,
                store=store,
                context=context,
                continuation_ref=first.continuation_ref,
            )
    assert len(reader.runner.calls) == 1
    second = reader.execute(
        request,
        database=database,
        store=store,
        context=context,
        continuation_ref=first.continuation_ref,
    )
    assert reader.runner.calls[1].cursor.after == "t3_cursor1" and second.continuation_ref
    with pytest.raises(RedditUnavailable):
        reader.execute(
            request,
            database=database,
            store=store,
            context=context,
            continuation_ref=first.continuation_ref,
        )
    assert len(reader.runner.calls) == 2
    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert (
            session.execute(
                sa.select(continuations.c.state).where(
                    continuations.c.id == str(first.continuation_ref)
                )
            ).scalar_one()
            == "consumed"
        )


@pytest.mark.parametrize(
    "change", ["job", "connection", "expired", "rotated", "uncertain", "disabled", "cancelled"]
)
def test_continuation_never_crosses_authority_or_replays_uncertain_page(
    database, monkeypatch, change
):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)
    request = RedditSearch(query="fixture")
    first = reader.execute(request, database=database, store=store, context=context)
    if change == "job":
        with database.tenant(actor, accepted["workspace_id"]) as session:
            previous = JobRepository.get(session, accepted["job_id"])
            other = submit(session, previous["conversation_id"], previous["plan_id"], uuid4().hex)
        context = context.model_copy(update={"job_id": UUID(other["id"])})
    elif change == "connection":
        with database.tenant(actor, accepted["workspace_id"]) as session:
            other = store.create(
                session,
                "reddit",
                "oauth",
                SecretPayload(credentials={"access_token": "fixture-access-token"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=("read", "discover"),
            )
        context = context.model_copy(update={"connection_ref": other.id})
    elif change in {"disabled", "cancelled"}:
        with database.tenant(actor, accepted["workspace_id"]) as session:
            if change == "disabled":
                set_disabled(session, "reddit", "discover", True)
            else:
                cancel(session, accepted["job_id"])
    elif change == "expired":
        with database.tenant(actor, accepted["workspace_id"]) as session:
            session.execute(
                sa.update(continuations)
                .where(continuations.c.id == str(first.continuation_ref))
                .values(expires_at=sa.func.now())
            )
    elif change == "rotated":
        with database.tenant(actor, accepted["workspace_id"]) as session:
            reference = reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials={"access_token": "replacement-access-token"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        context = context.model_copy(update={"connection_ref": reference.id})
    else:
        reader.runner.uncertain = True
    with pytest.raises(RedditUnavailable):
        reader.execute(
            request,
            database=database,
            store=store,
            context=context,
            continuation_ref=first.continuation_ref,
        )
    count = len(reader.runner.calls)
    assert count == (2 if change == "uncertain" else 1)
    with pytest.raises(RedditUnavailable):
        reader.execute(
            request,
            database=database,
            store=store,
            context=context,
            continuation_ref=first.continuation_ref,
        )
    assert len(reader.runner.calls) == count


def test_raw_cursor_rejected_and_repeated_provider_cursor_ends_chain(database, monkeypatch):
    _, _, _, store, context, reader = prepared(database, monkeypatch)
    with pytest.raises(RedditUnavailable):
        reader.execute(
            RedditSearch(query="fixture", cursor=RedditCursor(after="t3_raw123")),
            database=database,
            store=store,
            context=context,
        )
    assert reader.runner.calls == []
    reader.runner.repeat = True
    request = RedditSearch(query="fixture")
    first = reader.execute(request, database=database, store=store, context=context)
    second = reader.execute(
        request,
        database=database,
        store=store,
        context=context,
        continuation_ref=first.continuation_ref,
    )
    assert second.continuation_ref is None and second.has_more
    assert len(reader.runner.calls) == 2


def test_durable_workflow_pages_within_reserved_call_budget_and_replay_is_noop(
    database, monkeypatch
):
    actor, client, accepted, store, _, reader = prepared(database, monkeypatch)
    reader.runner.endless = True
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    provider = Provider()
    result = execute_discovery(
        database, payload, provider, reddit_reader=reader, connection_store=store
    )
    assert result["status"] == "checkpointed" and len(result["entity_ids"]) == 3
    assert len(reader.runner.calls) == 3 and provider.calls == 0
    assert [item.cursor.after if item.cursor else None for item in reader.runner.calls] == [
        None,
        "t3_cursor1",
        "t3_cursor2",
    ]
    assert (
        execute_discovery(
            database, payload, provider, reddit_reader=reader, connection_store=store
        )["status"]
        == "checkpointed"
    )
    assert len(reader.runner.calls) == 3
    with database.tenant(actor, accepted["workspace_id"]) as session:
        row = (
            session.execute(
                sa.select(reservations).where(reservations.c.job_id == accepted["job_id"])
            )
            .mappings()
            .one()
        )
        assert row["dimensions"]["search_calls"] == 3
    items = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"]
    assert len(items) == 3 and all(
        item["evidence_kind"] == "public_post" and item["qualification"] == "unverified"
        for item in items
    )


def test_foreign_workspace_cannot_consume_another_job_cursor(database, monkeypatch):
    _, _, _, store, context, reader = prepared(database, monkeypatch)
    first = reader.execute(
        RedditSearch(query="fixture"), database=database, store=store, context=context
    )
    _, _, _, other_store, other_context, other_reader = prepared(database, monkeypatch)
    with pytest.raises(RedditUnavailable):
        other_reader.execute(
            RedditSearch(query="fixture"),
            database=database,
            store=other_store,
            context=other_context,
            continuation_ref=first.continuation_ref,
        )
    assert other_reader.runner.calls == []


def test_rate_limit_on_following_page_retains_first_page_without_retry_or_fallback(
    database, monkeypatch
):
    actor, client, accepted, store, _, reader = prepared(database, monkeypatch)
    reader.runner.rate_limited = True
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    provider = Provider()
    result = execute_discovery(
        database, payload, provider, reddit_reader=reader, connection_store=store
    )
    assert result["status"] == "checkpointed" and len(result["entity_ids"]) == 1
    assert len(reader.runner.calls) == 2 and provider.calls == 0
    output = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    assert len(output["results"]) == 1 and output["state"] == "partial"
