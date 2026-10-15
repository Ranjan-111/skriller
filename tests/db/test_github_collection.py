"""Controlled public API transport through real durable jobs, storage and ledger."""

from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from github_fixtures import repo_payload
from test_research_workflow import isolate_capacity

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.github import GitHubPublicReader
from skriller.connectors.search import SearchHit, SearchPage
from skriller.connectors.switches import set_disabled
from skriller.contracts import SearchPlan
from skriller.db import ResearchRepository
from skriller.jobs.budget import current_usage
from skriller.jobs.worker import CheckpointWorker
from skriller.qualification.service import qualify_entity
from skriller.research import collection
from skriller.research.service import execute_discovery
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
PROXY = "http://127.0.0.1:18080"


def prepare(database, monkeypatch, url="https://github.com/acme/demo"):
    actor = str(uuid4())
    app = create_app(Settings(public_collection_proxy_url=PROXY))
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={}).json()
    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={
            "content": "Find public GitHub projects",
            "options": {"sources": ["github"], "result_limit": 10},
        },
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    isolate_capacity(monkeypatch, accepted["job_id"])
    task = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    scheduled = CheckpointWorker(database, {}).schedule(task)

    class Provider:
        async def search(self, query, **kwargs):
            return SearchPage(
                hits=[
                    SearchHit(title="Indexed project", url=url, snippet="Search reference", rank=1)
                ],
                rejected=0,
                truncated=False,
            )

    execute_discovery(
        database,
        {**task, "attempt_id": scheduled["attempt_id"]},
        Provider(),
        collection_proxy_url=PROXY,
    )
    with database.tenant(actor, task["workspace_id"]) as session:
        import sqlalchemy as sa

        from skriller.db.schema import attempts

        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == task["job_id"], attempts.c.stage == "collecting"
                )
            )
            .mappings()
            .one()
        )
    task["attempt_id"] = attempt["id"]
    original = collection.collection_handler

    def isolated(*args, **kwargs):
        return replace(
            original(*args, **kwargs),
            capacity_source="gh-" + task["job_id"].replace("-", ""),
            capacity_host=task["job_id"] + ".example.invalid",
        )

    monkeypatch.setattr(collection, "collection_handler", isolated)
    return client, task, attempt["logical_key"].removeprefix("collecting:")


def test_public_repo_pipeline_budget_evidence_replay_and_no_company_promotion(
    database, tmp_path, monkeypatch
):
    client, task, entity_id = prepare(database, monkeypatch)
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=repo_payload(
                owner={
                    "login": "acme",
                    "type": "Organization",
                    "email": "must-not-retain@example.com",
                }
            ),
        )

    reader = GitHubPublicReader(transport=httpx.MockTransport(reply))
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    outcome = collection.execute_collection(
        database, task, PROXY, storage=storage, github_reader=reader, enable_extraction=True
    )
    assert outcome["status"] == "checkpointed"
    collection.execute_collection(database, task, PROXY, storage=storage, github_reader=reader)
    assert len(calls) == 1 and calls[0].url == "https://api.github.com/repos/acme/demo"
    assert "authorization" not in calls[0].headers
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        assert entity["attributes"]["collection"]["status"] == "read"
        assert entity["attributes"]["_source_native_id"] == {
            "namespace": "github_repository",
            "id": "1",
        }
        content = storage.retrieve(session, entity["attributes"]["_collection_body_evidence_id"])
        assert b"must-not-retain" not in content
        facts = ResearchRepository.claims_for(session, entity_id)
        assert len(facts) == 3 and all(row["status"] == "accepted" for row in facts)
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 1
        plan = SearchPlan(
            workspace_id=task["workspace_id"],
            conversation_id=uuid4(),
            revision=1,
            entity_type="company",
        )
        assert qualify_entity(session, plan, entity_id).status == "excluded"
    results = client.get(f"/v1/jobs/{task['job_id']}/results").json()
    row = results["results"][0]
    assert row["qualification"] == "unverified" and len(row["extraction"]["observations"]) == 3
    assert "_collection" not in str(results) and "_source_native" not in str(results)


def test_profile_id_and_published_counters_do_not_prove_company_identity(
    database, tmp_path, monkeypatch
):
    client, task, entity_id = prepare(database, monkeypatch, "https://github.com/acme")
    payload = {
        "id": 42,
        "login": "acme",
        "type": "Organization",
        "html_url": "https://github.com/acme",
        "name": "Acme",
        "bio": "Synthetic public profile",
        "public_repos": 4,
        "followers": 3,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "email": "must-not-retain@example.com",
    }
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    reader = GitHubPublicReader(transport=httpx.MockTransport(reply))
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    collection.execute_collection(database, task, PROXY, storage=storage, github_reader=reader)
    assert len(requests) == 1 and requests[0].url.path == "/users/acme"
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        assert entity["attributes"]["_source_native_id"] == {
            "namespace": "github_profile",
            "id": "42",
        }
        assert b"must-not-retain" not in storage.retrieve(
            session, entity["attributes"]["_collection_body_evidence_id"]
        )
        plan = SearchPlan(
            workspace_id=task["workspace_id"],
            conversation_id=uuid4(),
            revision=1,
            entity_type="company",
        )
        assert qualify_entity(session, plan, entity_id).status == "near_match"
    assert (
        client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]["qualification"]
        == "unverified"
    )


def test_known_native_id_stays_suppressed_after_profile_url_changes(
    database, tmp_path, monkeypatch
):
    import sqlalchemy as sa

    from skriller.db.schema import entities
    from skriller.erasure import erase, journal, replay_erasures, suppressed
    from skriller.jobs.worker import TaskIdentity
    from skriller.research.github_collection import github_collection_handler

    _, task, entity_id = prepare(database, monkeypatch, "https://github.com/acme")
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    native = {"namespace": "github_profile", "id": "42"}
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        session.execute(
            sa.update(entities)
            .where(entities.c.id == entity_id)
            .values(
                attributes={
                    "url": "https://github.com/acme",
                    "source": "github",
                    "_source_native_id": native,
                }
            )
        )
        alias = ResearchRepository.entity(
            session,
            "other",
            "Known alias",
            attributes={
                "url": "https://github.com/renamed",
                "source": "github",
                "_source_native_id": native,
            },
        )
        erase(session, storage, entity_id, request_key="native-delete")
        assert ResearchRepository.get_entity(session, alias["id"])["attributes"] == {"erased": True}
        assert suppressed(session, native_id=native)
        assert not suppressed(session, native_id={"namespace": "github_repository", "id": "42"})
        assert all(
            len(digest) == 64 and digest != native["id"]
            for row in session.execute(sa.select(journal)).mappings()
            for digest in row["native_hashes"]
        )
        resurrected = ResearchRepository.entity(
            session,
            "other",
            "Restored unknown URL",
            attributes={
                "url": "https://github.com/another-name",
                "source": "github",
                "_source_native_id": native,
            },
        )
        replay_erasures(session, storage)
        assert ResearchRepository.get_entity(session, resurrected["id"])["attributes"] == {
            "erased": True
        }
    # A new indexed alias may not reveal its stable ID until the API reply.
    profile = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "id": 42,
                    "login": "third-name",
                    "type": "User",
                    "html_url": "https://github.com/third-name",
                    "public_repos": 1,
                    "followers": 1,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                },
            )
        )
    )
    import asyncio

    data = asyncio.run(profile.profile("third-name"))
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        unknown = ResearchRepository.entity(
            session,
            "other",
            "Indexed name",
            attributes={"url": data.source_url, "source": "github"},
        )
    handler = github_collection_handler(
        database,
        TaskIdentity.model_validate(task),
        {"url": data.source_url, "source": "github"},
        unknown["id"],
        PROXY,
        storage,
    )
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert handler.persist(session, (data, None, 0.1)) == []
        assert ResearchRepository.get_entity(session, unknown["id"])["attributes"] == {
            "erased": True
        }
        assert not ResearchRepository.claims_for(session, unknown["id"])


@pytest.mark.parametrize("status,code", [(404, "not_found"), (429, "rate_limited")])
def test_unavailable_api_is_bounded_accounted_and_no_claims(
    database, tmp_path, monkeypatch, status, code
):
    client, task, entity_id = prepare(database, monkeypatch)
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(status)

    reader = GitHubPublicReader(transport=httpx.MockTransport(reply))
    collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        github_reader=reader,
    )
    assert len(calls) == 1
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert not ResearchRepository.claims_for(session, entity_id)
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 1
    assert (
        client.get(f"/v1/jobs/{task['job_id']}/results").json()["results"][0]["collection"][
            "failure_code"
        ]
        == code
    )


@pytest.mark.parametrize(
    "disabled,url",
    [
        (True, "https://github.com/acme/demo"),
        (False, "https://github.com/acme/demo/issues"),
        (False, "https://attacker.example/acme"),
    ],
)
def test_disabled_or_invalid_resource_never_calls_api(
    database, tmp_path, monkeypatch, disabled, url
):
    _, task, entity_id = prepare(database, monkeypatch, url)
    if disabled:
        with database.tenant(task["actor_id"], task["workspace_id"]) as session:
            set_disabled(session, "github", "read", True)
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(lambda _: pytest.fail("API IO must be denied"))
    )
    collection.execute_collection(
        database,
        task,
        PROXY,
        storage=EvidenceStorage(LocalBlobBackend(tmp_path)),
        github_reader=reader,
    )
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        assert not ResearchRepository.claims_for(session, entity_id)
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 0


@pytest.mark.live
@pytest.mark.parametrize(
    "source_url", ["https://github.com/octocat/Hello-World", "https://github.com/octocat"]
)
def test_one_live_public_repo_read_through_proxy_and_job(database, monkeypatch, source_url):
    import json
    from pathlib import Path

    client, task, entity_id = prepare(database, monkeypatch, source_url)
    settings = Settings()
    storage = EvidenceStorage(LocalBlobBackend(settings.object_directory))
    result = collection.execute_collection(database, task, PROXY, storage=storage)
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        summary = entity["attributes"]["collection"]
        _, counters = current_usage(session, task["job_id"])
        assert summary["status"] == "read", summary
        assert counters["fetch_attempts"] == 1
        facts = ResearchRepository.claims_for(session, entity_id)
        assert len(facts) == 3 and all(row["status"] == "accepted" for row in facts)
        assert storage.retrieve(session, entity["attributes"]["_collection_body_evidence_id"])
    response = client.get(f"/v1/jobs/{task['job_id']}/results")
    assert (
        response.status_code == 200
        and response.json()["results"][0]["qualification"] == "unverified"
    )
    kind = "PROFILE" if source_url.endswith("/octocat") else "REPOSITORY"
    Path(f"docs/completions/GITHUB-COLLECTION-LIVE-{kind}.json").write_text(
        json.dumps(
            {
                "status": result["status"],
                "fixture": "public GitHub resource",
                "source_url": source_url,
                "route": "fixed GitHub API through configured loopback GuardedProxy",
                "fetch_attempts": 1,
                "source_facts": len(facts),
                "lead_fit": "unverified",
                "model_calls": 0,
                "currency_cost": 0,
                "no_auth_header": True,
                "observed_at": summary["observed_at"],
            },
            indent=2,
        )
        + "\n"
    )
