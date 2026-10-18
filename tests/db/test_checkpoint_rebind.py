"""Explicit consent replaces only undispatched bindings, without resetting work."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from test_linkedin_execution import prepared
from test_linkedin_resource_execution import Runner
from test_reddit_continuation import prepared as reddit_prepared
from test_reddit_thread_execution import Runner as RedditRunner
from test_research_workflow import Provider, isolate_capacity

from skriller.auth import Identity, require_identity
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import SecretPayload
from skriller.connections.tables import connections, proxy_routes
from skriller.connectors.switches import set_disabled
from skriller.db import JobRepository, WorkspaceRepository
from skriller.db.repositories import insert_row
from skriller.db.schema import attempts, entities, jobs, outbox
from skriller.jobs.budget import current_usage
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.collection import execute_collection
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


def setup(database, monkeypatch, *, source="linkedin"):
    settings = Settings(
        **{f"public_{source}_image": "sha256:" + "a" * 64},
        public_collection_proxy_url="http://127.0.0.1:18080",
    )
    actor, client, accepted, store, context, reader = (
        prepared if source == "linkedin" else reddit_prepared
    )(database, monkeypatch, settings=settings)
    client.app.state.connection_store = store
    reader.runner = Runner() if source == "linkedin" else RedditRunner()
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    isolate_capacity(monkeypatch, task["job_id"])
    handler = collection.collection_handler

    def isolated_handler(*args, **options):
        work = handler(*args, **options)
        return replace(
            work,
            capacity_source=task["job_id"] + work.capacity_source,
            capacity_host=task["job_id"] + work.capacity_host,
        )

    monkeypatch.setattr(collection, "collection_handler", isolated_handler)
    discovery = CheckpointWorker(database, {}).schedule(task)
    assert (
        execute_discovery(
            database,
            {**task, "attempt_id": discovery["attempt_id"]},
            Provider(),
            **{f"{source}_reader": reader},
            connection_store=store,
            collection_proxy_url=settings.public_collection_proxy_url,
        )["status"]
        == "checkpointed"
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"],
                    attempts.c.stage == "collecting",
                )
            )
            .mappings()
            .one()
        )
        entity = attempt["logical_key"].removeprefix("collecting:")
        original = session.execute(
            sa.select(entities.c.attributes).where(entities.c.id == entity)
        ).scalar_one()
        replacement = reconnect(
            session,
            store,
            context.connection_ref,
            SecretPayload(
                credentials={"session_cookie": "synthetic-session"}
                if source == "linkedin"
                else {"access_token": "fixture-access-token"}
            ),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        usage = current_usage(session, task["job_id"])
    calls = len(reader.runner.calls)
    stopped = execute_collection(
        database,
        {**task, "attempt_id": attempt["id"]},
        settings.public_collection_proxy_url,
        **{f"{source}_reader": reader},
        connection_store=store,
    )
    assert stopped == {"status": "connection_required"}
    assert len(reader.runner.calls) == calls
    with database.tenant(actor, task["workspace_id"]) as session:
        paused = JobRepository.get(session, task["job_id"])
        saved = (
            session.execute(sa.select(attempts).where(attempts.c.id == attempt["id"]))
            .mappings()
            .one()
        )
        assert saved["state"] == "pending" and saved["reservation_id"] is None
        assert current_usage(session, task["job_id"]) == usage
    body = {
        "source": source,
        "previous_connection_ref": str(context.connection_ref),
        "replacement_connection_ref": str(replacement.id),
        "expected_job_version": paused["version"],
        "entity_ids": [entity],
    }
    return actor, client, task, store, reader, dict(attempt), paused, original, body, usage


@pytest.mark.parametrize("source", ["linkedin", "reddit"])
def test_explicit_rebind_is_atomic_idempotent_and_resumes_saved_read(
    database, monkeypatch, tmp_path, source
):
    actor, client, task, store, reader, attempt, paused, original, body, usage = setup(
        database, monkeypatch, source=source
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        insert_row(
            session,
            proxy_routes,
            job_id=task["job_id"],
            source=source,
            account_connection_id=body["previous_connection_ref"],
            configuration_digest="direct",
            attempts=1,
            traffic_bytes=31,
            created_by=actor,
        )
    endpoint = f"/v1/jobs/{task['job_id']}/rebind-and-resume"
    options = client.get(f"/v1/jobs/{task['job_id']}/rebind-options")
    assert options.status_code == 200
    assert options.json()["options"] == [
        {
            "source": source,
            "previous_connection_ref": body["previous_connection_ref"],
            "entity_ids": body["entity_ids"],
        }
    ]
    assert original["_read_credential_ref"] not in options.text
    assert "synthetic-session" not in options.text
    headers = {"Idempotency-Key": "explicit-owner-consent"}
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "queued"
    assert client.post(endpoint, json=body, headers=headers).json() == response.json()
    assert (
        client.post(
            endpoint, json={**body, "replacement_connection_ref": str(uuid4())}, headers=headers
        ).status_code
        == 409
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        job = JobRepository.get(session, task["job_id"])
        attributes = session.execute(
            sa.select(entities.c.attributes).where(entities.c.id == body["entity_ids"][0])
        ).scalar_one()
        assert attributes["_read_connection_ref"] == body["replacement_connection_ref"]
        assert attributes["_read_credential_ref"] != original["_read_credential_ref"]
        assert job["created_at"] == paused["created_at"] and job["plan_id"] == paused["plan_id"]
        assert current_usage(session, task["job_id"]) == usage
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(outbox)
                .where(
                    outbox.c.job_id == task["job_id"],
                    outbox.c.idempotency_key.like("resume:%"),
                )
            ).scalar_one()
            == 1
        )
        route = (
            session.execute(sa.select(proxy_routes).where(proxy_routes.c.job_id == task["job_id"]))
            .mappings()
            .one()
        )
        assert route["account_connection_id"] == body["replacement_connection_ref"]
        assert route["attempts"] == 1 and route["traffic_bytes"] == 31
    reader.runner.calls.clear()
    result = execute_collection(
        database,
        {**task, "attempt_id": str(attempt["id"])},
        "http://127.0.0.1:18080",
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        **{f"{source}_reader": reader},
        connection_store=store,
    )
    assert result["status"] == "checkpointed", result
    assert len(reader.runner.calls) == 1


@pytest.mark.parametrize(
    "barrier",
    [
        "stale_version",
        "wrong_prior",
        "wrong_entity",
        "revoked",
        "disabled",
        "deadline",
        "cancelled",
        "uncertain",
        "member",
        "coowner",
        "failed_route",
        "expired_connection",
        "missing_scope",
        "wrong_source",
    ],
)
def test_rebind_barriers_leave_job_and_bindings_unchanged(database, monkeypatch, barrier):
    actor, client, task, store, reader, attempt, _paused, original, body, usage = setup(
        database, monkeypatch
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        if barrier == "stale_version":
            body["expected_job_version"] += 1
        elif barrier == "wrong_prior":
            body["previous_connection_ref"] = str(uuid4())
        elif barrier == "wrong_entity":
            body["entity_ids"] = [str(uuid4())]
        elif barrier == "revoked":
            store.revoke(session, UUID(body["replacement_connection_ref"]))
        elif barrier == "disabled":
            set_disabled(session, "linkedin", "read", True)
        elif barrier == "failed_route":
            insert_row(
                session,
                proxy_routes,
                job_id=task["job_id"],
                source="linkedin",
                account_connection_id=body["previous_connection_ref"],
                configuration_digest="direct",
                failed=True,
                created_by=actor,
            )
        elif barrier in {"expired_connection", "missing_scope", "wrong_source"}:
            values = {
                "expired_connection": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
                "missing_scope": {"scopes": ["discover"]},
                "wrong_source": {"source": "reddit"},
            }[barrier]
            session.execute(
                sa.update(connections)
                .where(
                    connections.c.id == body["replacement_connection_ref"],
                )
                .values(**values)
            )
        elif barrier == "deadline":
            session.execute(
                sa.update(jobs)
                .where(jobs.c.id == task["job_id"])
                .values(created_at=datetime.now(UTC) - timedelta(hours=1))
            )
        elif barrier == "cancelled":
            from skriller.jobs.control import cancel

            cancel(session, task["job_id"])
        elif barrier == "uncertain":
            session.execute(
                sa.update(attempts).where(attempts.c.id == attempt["id"]).values(state="failed")
            )
        elif barrier in {"member", "coowner"}:
            other = "other-" + uuid4().hex
            WorkspaceRepository.add_member(
                session, other, "owner" if barrier == "coowner" else "member"
            )
            client.app.dependency_overrides[require_identity] = lambda: Identity(other)
    response = client.post(
        f"/v1/jobs/{task['job_id']}/rebind-and-resume?workspace_id={task['workspace_id']}",
        json=body,
        headers={"Idempotency-Key": "blocked"},
    )
    assert response.status_code == (403 if barrier in {"member", "coowner"} else 409), response.text
    if barrier in {"member", "coowner"}:
        assert (
            client.get(
                f"/v1/jobs/{task['job_id']}/rebind-options?workspace_id={task['workspace_id']}"
            ).status_code
            == 403
        )
    with database.tenant(actor, task["workspace_id"]) as session:
        attributes = session.execute(
            sa.select(entities.c.attributes).where(
                entities.c.id == attempt["logical_key"].removeprefix("collecting:")
            )
        ).scalar_one()
        assert attributes == original
        assert JobRepository.get(session, task["job_id"])["state"] == (
            "cancelled" if barrier == "cancelled" else "paused"
        )
        assert current_usage(session, task["job_id"]) == usage
    assert not any(
        getattr(call, "operation", None) == "read_profile" for call in reader.runner.calls
    )
