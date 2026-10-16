"""Actual encrypted dump/object roundtrip into a fresh isolated PostgreSQL DB."""

import json
from datetime import UTC, datetime, timedelta
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
    WorkspaceRepository,
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
    isolated_databases, tmp_path, monkeypatch
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
            ConversationRepository.add_message(
                session, conversation["id"], "user", "Find software companies"
            )
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
            from skriller.lists import create_list, refresh_list
            from skriller.scheduling import create_schedule, schedules
            from skriller.security.urls import Destination
            from skriller.webhooks import transport
            from skriller.webhooks.service import create_endpoint
            from skriller.webhooks.tables import deliveries, endpoints

            monkeypatch.setattr(
                transport,
                "resolve_public_destination",
                lambda url: Destination(url, "receiver.example", 443, ("93.184.216.34",)),
            )
            saved = create_list(
                session, "Restored automation fixture", plan["id"], (records[1][1]["id"],)
            )
            create_schedule(session, saved["id"], opt_in=True, cadence_hours=1, max_runs=1)
            endpoint = create_endpoint(
                session, saved["id"], "https://receiver.example/hook", opt_in=True, keyring=key
            )
            refreshed = refresh_list(
                session, saved["id"], (records[1][1]["id"],), expected_revision=1
            )
            # Recovery fixture needs a pending delivery. SKR-081 intentionally
            # suppresses natural events for an unchanged snapshot.
            from skriller.db.repositories import insert_row

            insert_row(session, deliveries, endpoint_id=endpoint["id"], snapshot_id=refreshed["id"])
            analytics_actor = "analytics-coowner-" + str(uuid4())
            WorkspaceRepository.add_member(session, analytics_actor, role="owner")
        from urllib.parse import parse_qs, urlsplit

        from skriller.analytics.google import SCOPES, OAuthConfiguration
        from skriller.analytics.service import AnalyticsStore
        from skriller.analytics.tables import grants as analytics_grants

        analytics_store = AnalyticsStore(key)
        oauth_config = OAuthConfiguration(
            "fixture-client", "fixture-secret", "http://localhost:3000/callback"
        )
        with database.tenant(analytics_actor, other_workspace) as session:
            consent = analytics_store.start(session, oauth_config, opt_in=True)
            state = parse_qs(urlsplit(consent["authorization_url"]).query)["state"][0]
            _, version = analytics_store.consume(session, oauth_config, consent["grant_id"], state)
            analytics_store.activate(
                session,
                oauth_config,
                consent["grant_id"],
                version,
                {
                    "access_token": "SYNTHETIC_ANALYTICS",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": " ".join(SCOPES),
                },
                "UC" + "a" * 22,
            )
        from skriller.billing.access import bind_subscription, bindings
        from skriller.crm.queue import deliveries as crm_deliveries
        from skriller.crm.store import DestinationStore
        from skriller.entitlements import policy_for

        crm_store = DestinationStore(key)
        with database.tenant(other_actor, other_workspace) as session:
            from urllib.parse import parse_qs, urlsplit

            from skriller.crm.consents import ConsentStore
            from skriller.crm.oauth import SalesforceConfiguration

            crm_consent_store = ConsentStore(crm_store)
            crm_config = SalesforceConfiguration(
                "fixture-client", "fixture-secret", "http://localhost:3000/callback"
            )
            crm_consent = crm_consent_store.start(session, crm_config, opt_in=True)
            crm_state = parse_qs(urlsplit(crm_consent["authorization_url"]).query)["state"][0]
            _, crm_version = crm_consent_store.consume(
                session, crm_config, crm_consent["consent_id"], crm_state
            )
            crm_destination = crm_consent_store.activate(
                session,
                crm_config,
                crm_consent["consent_id"],
                crm_version,
                {
                    "instance_url": "https://fixture.my.salesforce.com",
                    "access_token": "fixture-crm-token-only",
                    "refresh_token": "fixture-crm-refresh-only",
                    "token_type": "Bearer",
                },
            )
            pending_crm_consent = crm_consent_store.start(session, crm_config, opt_in=True)

            # Seed a pending delivery to verify recovery cancels outbound work.
            insert_row(
                session,
                crm_deliveries,
                created_by=other_actor,
                destination_id=crm_destination["id"],
                destination_generation=1,
                plan_id=plan["id"],
                entity_id=records[1][1]["id"],
                selected_near=True,
                field_map={"last_name": "LastName", "company": "Company"},
                idempotency_key="restore-crm-fixture",
                request_hash="a" * 64,
            )
        source_operator = sa.create_engine(owners[0])
        try:
            with source_operator.begin() as connection:
                bind_subscription(
                    connection,
                    other_workspace,
                    provider="stripe",
                    account_scope="self:test",
                    subscription_id="sub_" + uuid4().hex,
                )
                connection.execute(
                    sa.update(bindings)
                    .where(bindings.c.workspace_id == other_workspace)
                    .values(enabled=True, valid_until=datetime.now(UTC) + timedelta(hours=1))
                )
        finally:
            source_operator.dispose()
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
                assert policy_for(session)["enabled"] is False
                crm_row = crm_store.get(session, crm_destination["id"])
                assert crm_row["enabled"] is False and crm_row["ciphertext"] == b""
                for consent_id in (crm_consent["consent_id"], pending_crm_consent["consent_id"]):
                    consent_row = crm_consent_store.get(session, consent_id)
                    assert consent_row["state"] == "revoked" and consent_row["ciphertext"] == b""

                assert (
                    session.execute(sa.select(crm_deliveries.c.state)).scalar_one() == "cancelled"
                )
                assert (
                    restored_storage.retrieve(session, records[1][0]["id"])
                    == b"Synthetic Aurora Ledger"
                )
                assert len(ResearchRepository.claims_for(session, records[1][1]["id"])) == 1
                assert JobRepository.get(session, queued["id"])["state"] == "cancelled"
                assert session.execute(sa.select(schedules.c.enabled)).scalar_one() is False
                assert session.execute(sa.select(endpoints.c.enabled)).scalar_one() is False
                assert session.execute(sa.select(endpoints.c.secret_ciphertext)).scalar_one() == b""
                assert session.execute(sa.select(deliveries.c.state)).scalar_one() == "cancelled"
            with restored.tenant(analytics_actor, other_workspace) as session:
                restored_grant = session.execute(sa.select(analytics_grants)).mappings().one()
                assert restored_grant["state"] == "revoked" and restored_grant["ciphertext"] == b""
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
                        "restored automations disabled and webhook signing ciphertext removed",
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
