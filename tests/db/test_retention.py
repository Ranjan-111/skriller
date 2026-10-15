"""Tenant TTL, durable cleanup leases, retries and current-citation filtering."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from skriller.db import ResearchRepository
from skriller.db.schema import evidence
from skriller.retention import cleanup_expired, current_observations, expiry_for
from skriller.retention_runtime import (
    claim_due,
    execute_cleanup,
    register,
    run_cleanup_child,
    schedules,
)
from skriller.storage import BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


def store(session, storage, *, source="web"):
    return storage.store(
        session,
        b"Aurora Ledger",
        source_url="https://example.com/company",
        source_platform=source,
        collected_at=datetime.now(UTC),
        excerpt="Aurora Ledger",
    )


def expire(session, identifier):
    session.execute(
        sa.update(evidence)
        .where(evidence.c.workspace_id == session.info["workspace_id"], evidence.c.id == identifier)
        .values(expires_at=sa.func.clock_timestamp() - sa.text("interval '1 second'"))
    )


def test_source_ceilings_and_export_expiry_cannot_be_extended(database, tmp_path):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "TTL")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    now = datetime.now(UTC)
    assert expiry_for("linkedin", now, now + timedelta(days=365)) == now + timedelta(days=7)
    assert expiry_for("web", now) == now + timedelta(days=30)
    with database.tenant(actor, workspace) as session:
        row = store(session, storage, source="skriller_export")
        assert (
            timedelta(seconds=3599)
            <= row["expires_at"] - row["collected_at"]
            <= timedelta(seconds=3600)
        )
        expire(session, row["id"])
    with database.tenant(actor, workspace) as session:
        with pytest.raises(BlobUnavailable):
            storage.retrieve(session, row["id"])
        assert cleanup_expired(session, storage)["removed"] == 1
    assert not (Path(tmp_path) / row["object_key"]).exists()


def test_cleanup_duplicate_delivery_preserves_other_tenant_and_current_data(database, tmp_path):
    actor = str(uuid4())
    a = database.create_workspace(actor, "Expired A")["id"]
    b = database.create_workspace(actor, "Retained B")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, a) as session:
        old = store(session, storage)
        fresh = store(session, storage)
        expire(session, old["id"])
        register(session)
        session.execute(
            sa.update(schedules)
            .where(schedules.c.workspace_id == a)
            .values(next_due_at=sa.func.clock_timestamp() - sa.text("interval '2 days'"))
        )
    with database.tenant(actor, b) as session:
        other = store(session, storage)
    payload = next(row for row in claim_due(database, 100) if row["workspace_id"] == a)
    assert execute_cleanup(database, payload, storage)["removed"] == 1
    assert execute_cleanup(database, payload, storage)["status"] == "stale_lease"
    with database.tenant(actor, a) as session:
        assert cleanup_expired(session, storage)["removed"] == 0
        assert storage.retrieve(session, fresh["id"]) == b"Aurora Ledger"
    with database.tenant(actor, b) as session:
        assert storage.retrieve(session, other["id"]) == b"Aurora Ledger"
    assert not (Path(tmp_path) / old["object_key"]).exists()


def test_expired_evidence_drops_cached_observation_from_current_view(database, tmp_path):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Current citation")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, workspace) as session:
        row = store(session, storage)
        entity = ResearchRepository.entity(session, "company", "Aurora Ledger")
        claim = ResearchRepository.claim(
            session,
            entity["id"],
            "company_name",
            "Aurora Ledger",
            mode="observed",
            status="unverified",
            evidence_ids=[row["id"]],
        )
        observation = {
            "claim_id": claim["id"],
            "field": "company_name",
            "value": "Aurora Ledger",
            "quote": "Aurora Ledger",
            "status": "unverified",
        }
        assert current_observations(session, entity["id"], [observation]) == (
            [{**observation, "evidence_ids": [row["id"]]}], 0
        )
        expire(session, row["id"])
        assert current_observations(session, entity["id"], [observation]) == ([], 1)
        cleanup_expired(session, storage)
        assert current_observations(session, entity["id"], [observation]) == ([], 1)


def test_failed_blob_delete_retains_pointer_for_retry(database, tmp_path, monkeypatch):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Delete retry")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, workspace) as session:
        row = store(session, storage)
        expire(session, row["id"])
    delete = storage.backend.delete
    monkeypatch.setattr(
        storage.backend,
        "delete",
        lambda *_: (_ for _ in ()).throw(OSError("synthetic backend failure")),
    )
    with pytest.raises(OSError), database.tenant(actor, workspace) as session:
        cleanup_expired(session, storage)
    with database.tenant(actor, workspace) as session:
        assert (
            ResearchRepository.get_evidence(session, row["id"])["object_key"] == row["object_key"]
        )
    monkeypatch.setattr(storage.backend, "delete", delete)
    with database.tenant(actor, workspace) as session:
        assert cleanup_expired(session, storage)["removed"] == 1


def test_cleanup_executes_in_bounded_child_with_its_scoped_storage(database, tmp_path, monkeypatch):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Bounded cleanup")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, workspace) as session:
        row = store(session, storage)
        expire(session, row["id"])
        register(session)
        session.execute(
            sa.update(schedules)
            .where(schedules.c.workspace_id == workspace)
            .values(next_due_at=sa.func.clock_timestamp() - sa.text("interval '3 days'"))
        )
    payload = next(item for item in claim_due(database, 100) if item["workspace_id"] == workspace)
    monkeypatch.setenv("SKRILLER_OBJECT_DIRECTORY", str(tmp_path))
    assert run_cleanup_child(payload) == {"status": "completed", "removed": 1}
    assert not (Path(tmp_path) / row["object_key"]).exists()
    assert run_cleanup_child(payload)["status"] == "stale_lease"


def test_expired_excerpt_without_blob_is_erased_and_stale_lease_reclaimed(database, tmp_path):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Lease retry")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, workspace) as session:
        row = ResearchRepository.add_evidence(
            session,
            source_url="https://example.com",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="Old source data",
        )
        expire(session, row["id"])
        register(session)
        session.execute(
            sa.update(schedules)
            .where(schedules.c.workspace_id == workspace)
            .values(next_due_at=sa.func.clock_timestamp() - sa.text("interval '4 days'"))
        )
    first = next(item for item in claim_due(database, 100) if item["workspace_id"] == workspace)
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(schedules)
            .where(schedules.c.workspace_id == workspace)
            .values(lease_expires_at=sa.func.clock_timestamp() - sa.text("interval '1 second'"))
        )
    second = next(item for item in claim_due(database, 100) if item["workspace_id"] == workspace)
    assert first["lease_token"] != second["lease_token"]
    assert execute_cleanup(database, first, storage)["status"] == "stale_lease"
    assert execute_cleanup(database, second, storage)["removed"] == 1
    with database.tenant(actor, workspace) as session:
        assert ResearchRepository.get_evidence(session, row["id"])["excerpt"] is None
