from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from skriller.storage import (
    BlobIntegrityError,
    BlobTooLarge,
    BlobUnavailable,
    EvidenceStorage,
    LocalBlobBackend,
)

pytestmark = pytest.mark.integration_db


def test_evidence_storage_authorization_expiration_integrity_and_size(database, tmp_path):
    backend = LocalBlobBackend(tmp_path / "objects")
    service = EvidenceStorage(backend, max_bytes=8)
    actor = str(uuid4())
    a = database.create_workspace(actor, "Storage A")
    b = database.create_workspace(actor, "Storage B")
    with database.tenant(actor, a["id"]) as session:
        evidence = service.store(
            session,
            b"evidence",
            source_url="https://example.test",
            source_platform="web",
            collected_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        with pytest.raises(BlobTooLarge):
            service.store(
                session,
                b"too large",
                source_url="https://example.test",
                source_platform="web",
                collected_at=datetime.now(UTC),
            )
    with database.tenant(actor, b["id"]) as session, pytest.raises(BlobUnavailable):
        service.retrieve(session, evidence["id"])
    with database.tenant(actor, a["id"]) as session:
        assert service.retrieve(session, evidence["id"]) == b"evidence"
        (tmp_path / "objects" / evidence["object_key"]).write_bytes(b"tampered")
        with pytest.raises(BlobIntegrityError):
            service.retrieve(session, evidence["id"])
        session.execute(
            sa.text("UPDATE evidence SET expires_at=:expiry WHERE id=:id"),
            {
                "expiry": datetime.now(UTC) - timedelta(seconds=1),
                "id": evidence["id"],
            },
        )
        with pytest.raises(BlobUnavailable, match="expired"):
            service.retrieve(session, evidence["id"])


def test_evidence_reference_survives_backend_migration(database, tmp_path):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Migrated storage")
    first = LocalBlobBackend(tmp_path / "first")
    second = LocalBlobBackend(tmp_path / "second")
    with database.tenant(actor, workspace["id"]) as session:
        evidence = EvidenceStorage(first).store(
            session,
            b"stable evidence",
            source_url="https://example.test",
            source_platform="web",
            collected_at=datetime.now(UTC),
        )
    # Backend migration copies bytes under the same tenant key, not a new evidence ID.
    second.put(workspace["id"], evidence["object_key"], b"stable evidence")
    with database.tenant(actor, workspace["id"]) as session:
        assert EvidenceStorage(second).retrieve(session, evidence["id"]) == b"stable evidence"
