"""Real durable profile evidence lifecycle with synthetic isolated-worker receipts."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_research_workflow import Provider, isolate_capacity, prepare
from test_social_discovery import Runner as DiscoveryRunner
from test_social_execution import Runner as ProfileRunner

from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.db.schema import attempts, entities, evidence
from skriller.erasure import erase
from skriller.jobs.budget import current_usage
from skriller.jobs.worker import CheckpointWorker
from skriller.research import collection
from skriller.research.service import execute_discovery
from skriller.retention import cleanup_expired
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


class Runner:
    def __init__(self, source, api_requests):
        self.api_requests = api_requests
        self.discovery = DiscoveryRunner(source, False, profile_link=True)
        self.profile = ProfileRunner(source)

    def run(self, operation, target, **kwargs):
        delegate = self.discovery if operation.endswith("search") else self.profile
        result = delegate.run(operation, target, **kwargs)
        if operation.endswith("profile"):
            payload = json.loads(result.stdout)
            payload["api_requests"] = self.api_requests
            result = replace(result, stdout=json.dumps(payload))
        return result


@pytest.mark.parametrize(
    "source,source_api_requests", [("instagram", 1), ("instagram", 3), ("facebook", 0)]
)
@pytest.mark.parametrize("lifecycle", ["read", "stale_connection", "expiry", "erasure"])
def test_profile_checkpoint_private_storage_replay_and_expired_view_removal(
    database, monkeypatch, tmp_path, source, source_api_requests, lifecycle
):
    from skriller.connectors.social_executor import ConcreteSocialExecutor

    actor = "social-read-" + uuid4().hex
    settings = Settings(public_collection_proxy_url="http://127.0.0.1:18080")
    _, client, accepted = prepare(database, monkeypatch, actor, sources=[source], settings=settings)
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    credentials = {"session_cookie": "synthetic-session"}
    if source == "facebook":
        credentials["user_id"] = "12345"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        reference = store.create(
            session,
            source,
            "session",
            SecretPayload(credentials=credentials),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("read", "discover"),
        )
    reader = ConcreteSocialExecutor(source, "sha256:" + "a" * 64)
    reader.runner = runner = Runner(source, source_api_requests)
    options = {source + "_reader": reader, "connection_store": store}
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    assert (
        execute_discovery(
            database, payload, Provider(), collection_proxy_url="http://127.0.0.1:18080", **options
        )["status"]
        == "checkpointed"
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == accepted["job_id"], attempts.c.stage == "collecting"
                )
            )
            .mappings()
            .one()
        )
        identifier = attempt["logical_key"].removeprefix("collecting:")
        if lifecycle == "stale_connection":
            reconnect(
                session,
                store,
                reference.id,
                SecretPayload(credentials={**credentials, "session_cookie": "replacement"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
    original = collection.collection_handler
    monkeypatch.setattr(
        collection,
        "collection_handler",
        lambda *args, **kwargs: replace(
            original(*args, **kwargs),
            capacity_source="social-read-" + accepted["job_id"],
            capacity_host=accepted["job_id"] + ".example.invalid",
        ),
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    read_payload = {**payload, "attempt_id": str(attempt["id"])}
    outcome = collection.execute_collection(
        database,
        read_payload,
        "http://127.0.0.1:18080",
        storage=storage,
        enable_extraction=True,
        **options,
    )
    assert outcome["status"] == "checkpointed", outcome
    collection.execute_collection(
        database, read_payload, "http://127.0.0.1:18080", storage=storage, **options
    )
    assert runner.discovery.calls == 1
    assert len(runner.profile.calls) == (0 if lifecycle == "stale_connection" else 1)
    endpoint = f"/v1/jobs/{accepted['job_id']}/results?workspace_id={accepted['workspace_id']}"
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    if lifecycle == "stale_connection":
        assert row["social_read"] is None and row["collection"]["failure_code"] == "auth_required"
        return
    resource = row["social_read"]["resource"]
    assert resource["subject_identity"] == "unknown" and row["qualification"] == "unverified"
    assert row["platform_reference"] is None
    if source == "instagram":
        assert resource["followers"] is None and resource["owner_analytics"] == "unavailable"
    else:
        assert resource["followers_display"] == "1.2K followers"
        assert resource["visibility"] == "unknown" and resource["company_identity"] == "unknown"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        saved = (
            session.execute(sa.select(entities).where(entities.c.id == identifier)).mappings().one()
        )
        assert saved["kind"] == "other"
        evidence_id = saved["attributes"]["_collection_body_evidence_id"]
        assert b"Synthetic" in storage.retrieve(session, evidence_id)
        stages = (
            session.execute(
                sa.select(attempts.c.stage).where(attempts.c.job_id == accepted["job_id"])
            )
            .scalars()
            .all()
        )
        assert "extracting" not in stages
        usage = current_usage(session, accepted["job_id"])
        assert usage[1]["fetch_attempts"] == (source_api_requests if source == "instagram" else 1)
        if lifecycle == "expiry":
            session.execute(
                sa.update(evidence)
                .where(evidence.c.id == evidence_id)
                .values(
                    collected_at=datetime.now(UTC) - timedelta(days=9),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        elif lifecycle == "erasure":
            erase(session, storage, identifier, request_key="fixture-social-erasure")
    if lifecycle == "expiry":
        assert client.get(endpoint).json()["results"][0]["social_read"] is None
        with database.tenant(actor, accepted["workspace_id"]) as session:
            assert cleanup_expired(session, storage)["removed"] == 1
            attributes = session.execute(
                sa.select(entities.c.attributes).where(entities.c.id == identifier)
            ).scalar_one()
            assert "social_read" not in attributes
    elif lifecycle == "erasure":
        assert client.get(endpoint).json()["results"] == []
