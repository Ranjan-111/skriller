"""Deletion propagation, linked URL suppression and late-write/restore fences."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from test_collection_workflow import discover

from skriller.db import (
    JobRepository,
    ResearchRepository,
    WorkspaceAccessDenied,
    WorkspaceRepository,
)
from skriller.db.schema import entities, evidence
from skriller.erasure import erase, journal, replay_erasures, suppressed
from skriller.jobs.worker import TaskIdentity
from skriller.qualification.identity import identity_reviews
from skriller.research.collection import collection_handler
from skriller.storage import BlobUnavailable, EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def test_indexed_native_alias_stays_suppressed_without_account_read(
    database, monkeypatch, tmp_path
):
    from test_research_workflow import prepare, run

    from skriller.connectors.search import SearchHit, SearchPage

    actor = f"erasure-indexed-native-{uuid4()}"

    class IndexedProvider:
        def __init__(self, url):
            self.urls = [url] if isinstance(url, str) else url

        async def search(self, query, **options):
            hits = (
                [
                    SearchHit(
                        title="Synthetic post", url=url, snippet="Indexed only", rank=index + 1
                    )
                    for index, url in enumerate(self.urls)
                ]
                if options["domains"]
                else []
            )
            return SearchPage(hits=hits, rejected=0, truncated=False)

    _, client, accepted = prepare(database, monkeypatch, actor)
    run(
        database,
        actor,
        accepted,
        IndexedProvider(
            [
                "https://www.linkedin.com/posts/example-activity-123456789-example",
                "https://www.linkedin.com/feed/update/urn:li:activity:123456789/",
            ]
        ),
        monkeypatch,
    )
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"][0]
    assert result["qualification"] == "unverified" and "_source_native_id" not in result
    assert len(result["provenance"]) == 2
    with database.tenant(actor, accepted["workspace_id"]) as session:
        stored = ResearchRepository.get_entity(session, result["id"])
        assert stored["attributes"]["_source_native_id"] == {
            "namespace": "linkedin_activity",
            "id": "123456789",
        }
        erase(
            session,
            EvidenceStorage(LocalBlobBackend(tmp_path)),
            result["id"],
            request_key="indexed-post-delete",
        )
    _, client, next_run = prepare(database, monkeypatch, actor)
    assert next_run["workspace_id"] == accepted["workspace_id"]
    run(
        database,
        actor,
        next_run,
        IndexedProvider("https://linkedin.com/feed/update/urn:li:activity:123456789/"),
        monkeypatch,
    )
    assert client.get(f"/v1/jobs/{next_run['job_id']}/results").json()["results"] == []


def fixture(database, tmp_path):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Erasure fixture")["id"]
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(actor, workspace) as session:
        body = storage.store(
            session,
            b"Aurora Ledger",
            source_url="https://example.com/about",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="Aurora Ledger",
        )
        target = ResearchRepository.entity(
            session,
            "company",
            "Aurora Ledger",
            attributes={
                "url": "https://example.com/about",
                "_collection_body_evidence_id": body["id"],
            },
        )
        claim = ResearchRepository.claim(
            session,
            target["id"],
            "company_name",
            "Aurora Ledger",
            mode="observed",
            status="unverified",
            evidence_ids=[body["id"]],
        )
    return actor, workspace, storage, target, body, claim


def test_erasure_removes_private_data_and_replay_is_noop(database, tmp_path):
    actor, workspace, storage, target, body, _ = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        assert erase(session, storage, target["id"], request_key="delete-1")["status"] == "erased"
        assert ResearchRepository.get_entity(session, target["id"])["attributes"] == {
            "erased": True
        }
        assert not ResearchRepository.claims_for(session, target["id"])
        assert suppressed(session, url="https://example.com/about?utm_source=index")
        assert erase(session, storage, target["id"], request_key="delete-1")["status"] == "erased"
        row = session.execute(sa.select(journal)).mappings().one()
        assert "Aurora" not in str(row) and "https://" not in str(row)
    with database.tenant(actor, workspace) as session, pytest.raises(BlobUnavailable):
        storage.retrieve(session, body["id"])
    assert not (tmp_path / body["object_key"]).exists()


def test_api_requires_owner_and_idempotency_header(database, tmp_path):
    from fastapi.testclient import TestClient

    from skriller.api import create_app
    from skriller.auth import Identity, require_identity
    from skriller.settings import Settings

    actor, workspace, storage, target, _, _ = fixture(database, tmp_path)
    member = str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    app = create_app(Settings())
    app.state.database = database
    app.state.evidence_storage = storage
    path = f"/v1/workspaces/{workspace}/entities/{target['id']}"
    with TestClient(app) as client:
        app.state.evidence_storage = storage
        app.dependency_overrides[require_identity] = lambda: Identity(uid=member)
        assert client.delete(path, headers={"Idempotency-Key": "api-erase"}).status_code == 403
        app.dependency_overrides[require_identity] = lambda: Identity(uid=actor)
        assert client.delete(path).status_code == 422
        assert client.delete(path, headers={"Idempotency-Key": "api-erase"}).status_code == 200
        assert client.delete(path, headers={"Idempotency-Key": "api-erase"}).status_code == 200


async def test_new_discovery_and_cache_writes_honor_suppression(database, tmp_path, monkeypatch):
    from scrapling.engines.toolbelt.custom import Response
    from test_research_workflow import prepare

    from skriller.connectors.cache import CacheKey, ScopedResponseCache
    from skriller.connectors.search import SearchHit, SearchPage
    from skriller.research.service import discovery_handler

    actor, workspace, storage, target, _, _ = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        erase(session, storage, target["id"], request_key="before-new-run")
    _, _, accepted = prepare(database, monkeypatch, actor)
    assert accepted["workspace_id"] == workspace
    handler = discovery_handler(database, actor, accepted["job_id"])
    page = SearchPage(
        hits=[
            SearchHit(
                title="Old name rediscovered",
                url="https://example.com/about",
                snippet="Old private value",
                rank=1,
            )
        ],
        rejected=0,
        truncated=False,
    )
    with database.tenant(actor, workspace) as session:
        assert handler.persist(session, [{"source": "web", "page": page, "error": None}]) == []
    key = CacheKey(
        source="web",
        source_url=page.hits[0].url,
        entity_type="company",
        schema_hash="a" * 64,
        extractor_version="v1",
    )
    response = Response(
        url=key.source_url,
        content=b"Old private value",
        status=200,
        reason="OK",
        encoding="utf-8",
        cookies={},
        headers={},
        request_headers={},
        method="GET",
    )
    cache = ScopedResponseCache(storage)
    with pytest.raises(BlobUnavailable, match="Suppressed"):
        await cache.put(database, actor, workspace, key, response, collected_at=datetime.now(UTC))


def test_inflight_export_cannot_survive_erasure(database, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from test_exports import fixture as export_fixture

    from skriller import exports
    from skriller.db import Database

    actor, workspace, target, _, plan, storage = export_fixture(database, tmp_path)
    concurrent = Database(database.engine.url, pool_size=2)
    copying, release, deleting, erased = Event(), Event(), Event(), Event()
    original = exports.serialize

    def serialize(*args, **kwargs):
        copying.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(exports, "serialize", serialize)

    def export():
        with concurrent.tenant(actor, workspace) as session:
            return exports.create_export(session, storage, plan, (target,), format="json")

    def delete():
        deleting.set()
        with concurrent.tenant(actor, workspace) as session:
            erase(session, storage, target, request_key="during-export")
        erased.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            exported = pool.submit(export)
            assert copying.wait(3)
            deletion = pool.submit(delete)
            assert deleting.wait(3)
            assert not erased.wait(0.1)
            release.set()
            result = exported.result(timeout=3)
            deletion.result(timeout=3)
        with concurrent.tenant(actor, workspace) as session:
            with pytest.raises(BlobUnavailable):
                exports.download_export(session, storage, result["id"])
            with pytest.raises(LookupError):
                ResearchRepository.claim(
                    session, target, "name", None, mode="unavailable", evidence_ids=[]
                )
    finally:
        release.set()
        concurrent.dispose()


def test_linked_alternate_urls_suppressed_and_restored_rows_erased_before_serving(
    database, tmp_path
):
    actor, workspace, storage, target, _body, _ = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        alternate = ResearchRepository.entity(
            session, "company", "Alternate", attributes={"url": "https://example.net/team"}
        )
        session.execute(
            sa.insert(identity_reviews).values(
                workspace_id=workspace,
                id=str(uuid4()),
                source_id=target["id"],
                target_id=alternate["id"],
                state="linked",
                reason="fixture_review",
                created_by=actor,
                reviewed_by=actor,
            )
        )
        erase(session, storage, target["id"], request_key="linked-delete")
        assert suppressed(session, url="https://example.net/team")
        # Simulate restored older entity data while retaining the newest deletion journal.
        session.execute(
            sa.update(entities)
            .where(entities.c.id == target["id"])
            .values(attributes=target["attributes"], display_name="Restored old value")
        )
        resurrected = ResearchRepository.entity(
            session, "company", "Rediscovery", attributes={"url": "https://example.net/team"}
        )
        replay_erasures(session, storage)
        assert ResearchRepository.get_entity(session, target["id"])["display_name"] is None
        assert ResearchRepository.get_entity(session, resurrected["id"])["attributes"] == {
            "erased": True
        }


def test_member_cannot_erase_and_other_tenant_data_is_retained(database, tmp_path):
    actor, workspace, storage, target, _body, _ = fixture(database, tmp_path)
    member = str(uuid4())
    other = database.create_workspace(actor, "Other retained")["id"]
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
    with pytest.raises(WorkspaceAccessDenied), database.tenant(member, workspace) as session:
        erase(session, storage, target["id"], request_key="forbidden")
    with database.tenant(actor, other) as session:
        retained = storage.store(
            session,
            b"Retained",
            source_url="https://example.org",
            source_platform="web",
            collected_at=datetime.now(UTC),
        )
    with database.tenant(actor, workspace) as session:
        erase(session, storage, target["id"], request_key="owner-delete")
    with database.tenant(actor, other) as session:
        assert storage.retrieve(session, retained["id"]) == b"Retained"


def test_late_collected_result_cannot_repopulate_erased_candidate(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    actor = f"erasure-flight-{uuid4()}"
    _, accepted, _, tasks, _ = discover(database, monkeypatch, actor, endpoint, ["company"])
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    identity = TaskIdentity.model_validate(tasks[0])
    handler = collection_handler(database, identity, endpoint, storage)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        from skriller.jobs.control import plan_for_job

        plan = plan_for_job(session, JobRepository.get(session, accepted["job_id"]))
        entity = session.execute(sa.select(entities)).mappings().one()
    data, _, _ = handler.run_with_deadline(plan, 30)
    assert requests == ["/company"]
    with database.tenant(actor, accepted["workspace_id"]) as session:
        erase(session, storage, entity["id"], request_key="in-flight-delete")
    with database.tenant(actor, accepted["workspace_id"]) as session:
        assert handler.persist(session, data) == []
        assert JobRepository.get(session, accepted["job_id"])["state"] == "cancelled"
        assert session.execute(sa.select(sa.func.count()).select_from(evidence)).scalar_one() == 0


def test_snapshots_cache_and_exports_invalidated_and_normal_immutability_remains(
    database, tmp_path
):
    from skriller.contracts import SearchPlan
    from skriller.db import ConversationRepository
    from skriller.lists import list_snapshots, saved_lists

    actor, workspace, storage, target, _body, _claim = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Derivative copies")
        plan = ConversationRepository.revise_plan(
            session,
            conversation["id"],
            SearchPlan(
                workspace_id=workspace,
                conversation_id=conversation["id"],
                revision=1,
                entity_type="company",
            ).model_dump(mode="json"),
        )
        list_id = str(uuid4())
        snapshot_id = str(uuid4())
        session.execute(
            sa.insert(saved_lists).values(
                workspace_id=workspace,
                id=list_id,
                name="Private list",
                plan_id=plan["id"],
                created_by=actor,
            )
        )
        session.execute(
            sa.insert(list_snapshots).values(
                workspace_id=workspace,
                id=snapshot_id,
                list_id=list_id,
                revision=1,
                plan_id=plan["id"],
                payload={"copied_name": "Aurora Ledger"},
                created_by=actor,
            )
        )
        cached = storage.store(
            session,
            b"Cached private value",
            source_url="https://example.com/cache",
            source_platform="web",
            collected_at=datetime.now(UTC),
        )
        ResearchRepository.entity(
            session,
            "other",
            canonical_key="response-cache:fixture",
            attributes={"evidence_id": cached["id"]},
        )
        exported = storage.store(
            session,
            b"Exported private value",
            source_url="https://skriller.invalid/export",
            source_platform="skriller_export",
            collected_at=datetime.now(UTC),
        )
    with pytest.raises(sa.exc.DBAPIError), database.tenant(actor, workspace) as session:
        session.execute(sa.delete(list_snapshots).where(list_snapshots.c.id == snapshot_id))
    with database.tenant(actor, workspace) as session:
        erase(session, storage, target["id"], request_key="all-derivatives")
        assert (
            session.execute(sa.select(sa.func.count()).select_from(list_snapshots)).scalar_one()
            == 0
        )
        assert session.execute(
            sa.select(entities.c.attributes).where(entities.c.id != target["id"])
        ).scalar_one() == {"erased": True}
    for row in (cached, exported):
        assert not (tmp_path / row["object_key"]).exists()
