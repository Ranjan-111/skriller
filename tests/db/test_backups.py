"""Actual encrypted dump/object roundtrip into a fresh isolated PostgreSQL DB."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from psycopg import sql

from skriller.backups import (
    create_backup,
    export_journal,
    prune_backups,
    restore_backup,
    seal,
    unseal,
)
from skriller.connections.keys import Keyring
from skriller.contracts import SearchPlan
from skriller.db import (
    ConversationRepository,
    Database,
    JobRepository,
    ResearchRepository,
    WorkspaceAccessDenied,
)
from skriller.erasure import erase, suppressed
from skriller.jobs.outbox import submit
from skriller.settings import Settings
from skriller.storage import BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
BIN = Path(".runtime/postgres/bin")


@pytest.fixture
def isolated_databases(database):
    if not (BIN / "pg_dump").is_file():
        pytest.skip("Explicit local PostgreSQL client runtime not installed")
    settings = Settings()
    admin_url = sa.engine.make_url(settings.database_url)
    names = ["skriller_restore_" + uuid4().hex for _ in range(2)]
    admin = sa.create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        for name in names:
            connection.connection.driver_connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
            )
    owner_urls = [admin_url.set(database=name) for name in names]
    app_urls = [
        sa.engine.make_url(settings.application_database_url).set(database=name) for name in names
    ]
    config = Config("alembic.ini")
    config.attributes["database_url"] = owner_urls[0]
    command.upgrade(config, "head")
    try:
        yield owner_urls, app_urls
    finally:
        with admin.connect() as connection:
            for name in names:
                connection.connection.driver_connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )
        admin.dispose()


def test_actual_restore_replays_newer_deletion_and_retains_other_tenant(
    isolated_databases, tmp_path
):
    owners, apps = isolated_databases
    database = Database(apps[0])
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Erase after snapshot")["id"]
    other_actor = str(uuid4())
    other_workspace = database.create_workspace(other_actor, "Retained tenant")["id"]
    backend = LocalBlobBackend(tmp_path / "source_objects")
    storage = EvidenceStorage(backend)
    try:
        records = []
        for person, scope in [(actor, workspace), (other_actor, other_workspace)]:
            with database.tenant(person, scope) as session:
                body = storage.store(
                    session,
                    b"Synthetic Aurora Ledger",
                    source_url="https://example.com/about",
                    source_platform="web",
                    collected_at=datetime.now(UTC),
                )
                entity = ResearchRepository.entity(
                    session,
                    "company",
                    "Synthetic Aurora Ledger",
                    attributes={
                        "url": "https://example.com/about",
                        "_collection_body_evidence_id": body["id"],
                    },
                )
                ResearchRepository.claim(
                    session,
                    entity["id"],
                    "company_name",
                    "Synthetic Aurora Ledger",
                    mode="observed",
                    status="unverified",
                    evidence_ids=[body["id"]],
                )
                records.append((body, entity))
        key = Keyring.create_file(tmp_path / "keys" / "backup.json")
        with database.tenant(other_actor, other_workspace) as session:
            conversation = ConversationRepository.create(session, "Queued synthetic research")
            plan = ConversationRepository.revise_plan(
                session,
                conversation["id"],
                SearchPlan(
                    workspace_id=other_workspace,
                    conversation_id=conversation["id"],
                    revision=1,
                    entity_type="company",
                ).model_dump(mode="json"),
            )
            queued = submit(session, conversation["id"], plan["id"], "restore-queued-job")
        archive = tmp_path / "archive" / "snapshot.enc"
        backup_report = create_backup(owners[0], backend.directory, archive, key, BIN)
        assert archive.stat().st_mode & 0o077 == 0
        assert b"Synthetic Aurora" not in archive.read_bytes()
        with database.tenant(actor, workspace) as session:
            erase(session, storage, records[0][1]["id"], request_key="after-snapshot")
        receipt = tmp_path / "journal.enc"
        export_journal(owners[0], receipt, key)
        with pytest.raises(ValueError, match="newest deletion receipt"):
            restore_backup(
                archive,
                key,
                owners[0],
                owners[1],
                apps[1],
                tmp_path / "refused_objects",
                BIN,
                journal_path=receipt,
            )
        database.dispose()
        admin = sa.create_engine(owners[0].set(database="postgres"), isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as connection:
                connection.connection.driver_connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(owners[0].database)
                    )
                )
        finally:
            admin.dispose()
        objects = tmp_path / "restored_objects"
        report = restore_backup(
            archive,
            key,
            owners[0],
            owners[1],
            apps[1],
            objects,
            BIN,
            journal_path=receipt,
            journal_is_current=True,
        )
        assert report["traffic_enabled"] is False and report["replayed_entities"] == 1
        restored = Database(apps[1])
        restored_storage = EvidenceStorage(LocalBlobBackend(objects))
        try:
            with restored.tenant(actor, workspace) as session:
                assert ResearchRepository.get_entity(session, records[0][1]["id"])[
                    "attributes"
                ] == {"erased": True}
                assert not ResearchRepository.claims_for(session, records[0][1]["id"])
                assert suppressed(session, url="https://example.com/about")
                with pytest.raises(BlobUnavailable):
                    restored_storage.retrieve(session, records[0][0]["id"])
            with restored.tenant(other_actor, other_workspace) as session:
                assert (
                    restored_storage.retrieve(session, records[1][0]["id"])
                    == b"Synthetic Aurora Ledger"
                )
                assert len(ResearchRepository.claims_for(session, records[1][1]["id"])) == 1
                assert JobRepository.get(session, queued["id"])["state"] == "cancelled"
            with pytest.raises(WorkspaceAccessDenied), restored.tenant(actor, other_workspace):
                pass
        finally:
            restored.dispose()
        # Non-sensitive measured recovery evidence only, no source URLs/credentials.
        Path("docs/completions/LOCAL-BACKUP-RESTORE.json").write_text(
            json.dumps(
                {
                    "fixture": "two synthetic tenants; backup precedes owner deletion; source DB destroyed; independent current encrypted receipt",
                    "backup": backup_report,
                    "restore": report,
                    "checks": [
                        "deleted claims/blob removed",
                        "retained evidence hash",
                        "tenant isolation",
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        with pytest.raises(ValueError, match="empty"):
            restore_backup(
                archive, key, owners[0], owners[1], apps[1], tmp_path / "another_objects", BIN
            )
    finally:
        database.dispose()


def test_authenticated_envelope_rejects_corruption_wrong_key_and_expiry(tmp_path):
    key = Keyring.create_file(tmp_path / "key.json")
    payload = {"expires_at": "2099-01-01T00:00:00+00:00", "synthetic": "fixture"}
    archive = tmp_path / "snapshot.enc"
    archive.write_text(seal(payload, key))
    assert unseal(archive, key) == payload
    wrong = Keyring.create_file(tmp_path / "wrong.json")
    with pytest.raises(ValueError):
        unseal(archive, wrong)
    envelope = json.loads(archive.read_text())
    envelope["ciphertext"] = "AAAA"
    archive.write_text(json.dumps(envelope))
    with pytest.raises(ValueError):
        unseal(archive, key)
    archive.write_text(seal({"expires_at": "2000-01-01T00:00:00+00:00"}, key))
    with pytest.raises(ValueError):
        unseal(archive, key)
    assert prune_backups(tmp_path, key)["expired_archives_removed"] == 1
    assert not archive.exists()
