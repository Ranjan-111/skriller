"""Real tenant/job/credential controls with controlled copied-backend receipts."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_research_workflow import Provider, isolate_capacity, prepare

from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.linkedin_discovery import LinkedInSearch
from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor, LinkedInUnavailable
from skriller.connectors.switches import set_disabled
from skriller.contracts import ExecutionContext
from skriller.db import WorkspaceRepository
from skriller.jobs.control import cancel
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker
from skriller.research.service import execute_discovery
from skriller.security.runner import RunResult
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


class Runner:
    def __init__(self):
        self.calls = []
        self.after = None
        self.failed = False

    def run(self, operation, target, **kwargs):
        assert operation == "linkedin_search" and not kwargs["cancel_check"]()
        assert kwargs["credential_material"].injection() == {
            "LINKEDIN_SESSION_COOKIE": "synthetic-session"
        }
        request = LinkedInSearch.model_validate_json(target)
        self.calls.append(request)
        if self.after:
            self.after()
        if self.failed:
            return RunResult("failed", 2, "", "PRIVATE UPSTREAM ERROR", 0)
        return RunResult(
            "completed",
            0,
            json.dumps(
                {
                    "url": request.search_url(),
                    "sections": {
                        "search_results": "UNALIGNED PAGE TEXT NEVER ASSIGNED TO A PERSON"
                    },
                    "references": {
                        "search_results": [
                            {
                                "kind": "person",
                                "url": "https://www.linkedin.com/in/synthetic/",
                                "text": "Synthetic name",
                            }
                        ]
                    },
                }
            ),
            "",
            1,
        )


def prepared(database, monkeypatch, *, scopes=("read", "discover"), settings=None):
    actor = "linkedin-exec-" + uuid4().hex
    _, client, accepted = prepare(
        database, monkeypatch, actor, sources=["linkedin"], settings=settings or Settings()
    )
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    with database.tenant(actor, accepted["workspace_id"]) as session:
        reference = store.create(
            session,
            "linkedin",
            "session",
            SecretPayload(credentials={"session_cookie": "synthetic-session"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=scopes,
        )
    context = ExecutionContext(
        workspace_id=UUID(accepted["workspace_id"]),
        job_id=UUID(accepted["job_id"]),
        actor_id=actor,
        plan_revision=1,
        connection_ref=reference.id,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        attempt_budget=1,
    )
    reader = ConcreteLinkedInExecutor("sha256:" + "a" * 64)
    reader.runner = Runner()
    return actor, client, accepted, store, context, reader


def test_search_reference_never_claims_a_profile_or_aligned_post_read(database, monkeypatch):
    _, _, _, store, context, reader = prepared(database, monkeypatch)
    page = reader.search_page("founder", limit=3, database=database, store=store, context=context)
    assert page.hits[0].provider == "linkedin_mcp"
    assert page.hits[0].evidence_kind == "search_reference"
    assert page.hits[0].snippet == "Synthetic name"
    assert "UNALIGNED" not in page.model_dump_json() and not page.pagination_supported


@pytest.mark.parametrize(
    "boundary", ["read_scope", "cancelled", "expired", "read_disabled", "discover_disabled"]
)
def test_invalid_authority_never_calls_the_worker(database, monkeypatch, boundary):
    actor, _, accepted, store, context, reader = prepared(
        database,
        monkeypatch,
        scopes=("read",) if boundary == "read_scope" else ("read", "discover"),
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        if boundary == "cancelled":
            cancel(session, accepted["job_id"])
        elif boundary.endswith("disabled"):
            set_disabled(session, "linkedin", boundary.split("_")[0], True)
    if boundary == "expired":
        context = context.model_copy(update={"deadline": datetime.now(UTC) - timedelta(seconds=1)})
    with pytest.raises(LinkedInUnavailable):
        reader.execute(
            LinkedInSearch(operation="search_people", keywords="founder"),
            database=database,
            store=store,
            context=context,
        )
    assert not reader.runner.calls


def test_revocation_during_execution_discards_even_successful_output(database, monkeypatch):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)

    def revoke():
        with database.tenant(actor, accepted["workspace_id"]) as session:
            store.revoke(session, context.connection_ref)

    reader.runner.after = revoke
    with pytest.raises(LinkedInUnavailable):
        reader.execute(
            LinkedInSearch(operation="search_posts", keywords="hiring"),
            database=database,
            store=store,
            context=context,
        )
    assert len(reader.runner.calls) == 1


@pytest.mark.parametrize("role", ["member", "owner"])
def test_other_initiators_cannot_open_the_connected_owners_session(database, monkeypatch, role):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)
    other = "other-" + uuid4().hex
    with database.tenant(actor, accepted["workspace_id"]) as session:
        WorkspaceRepository.add_member(session, other, role)
    with database.tenant(other, accepted["workspace_id"]) as session:
        # A separate job belongs to this initiator, but the source session does not.
        from skriller.db import JobRepository

        previous = JobRepository.get(session, accepted["job_id"])
        job = submit(session, previous["conversation_id"], previous["plan_id"], uuid4().hex)
    context = context.model_copy(update={"actor_id": other, "job_id": UUID(job["id"])})
    with pytest.raises(LinkedInUnavailable):
        reader.execute(
            LinkedInSearch(operation="search_people", keywords="founder"),
            database=database,
            store=store,
            context=context,
        )
    assert not reader.runner.calls


def test_replacing_credentials_during_execution_never_rebinds_old_call(database, monkeypatch):
    actor, _, accepted, store, context, reader = prepared(database, monkeypatch)

    def rotate():
        with database.tenant(actor, accepted["workspace_id"]) as session:
            reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials={"session_cookie": "replacement"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    reader.runner.after = rotate
    with pytest.raises(LinkedInUnavailable):
        reader.execute(
            LinkedInSearch(operation="search_people", keywords="founder"),
            database=database,
            store=store,
            context=context,
        )
    assert len(reader.runner.calls) == 1


@pytest.mark.parametrize("failed", [False, True])
def test_durable_workflow_accounts_and_replays_without_native_or_indexed_retry(
    database, monkeypatch, failed
):
    actor, client, accepted, store, _, reader = prepared(database, monkeypatch)
    isolate_capacity(monkeypatch, accepted["job_id"])
    reader.runner.failed = failed
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    provider = Provider()
    outcome = execute_discovery(
        database, payload, provider, linkedin_reader=reader, connection_store=store
    )
    assert outcome["status"] in {"checkpointed", "source_unavailable"}, outcome
    assert len(reader.runner.calls) == 1 and provider.calls == 0
    execute_discovery(database, payload, provider, linkedin_reader=reader, connection_store=store)
    assert len(reader.runner.calls) == 1 and provider.calls == 0
    result = client.get(
        f"/v1/jobs/{accepted['job_id']}/results?workspace_id={accepted['workspace_id']}"
    )
    assert result.status_code == 200, result.text
    rows = result.json()["results"]
    if not failed:
        assert (
            rows[0]["provider"] == "linkedin_mcp" and rows[0]["evidence_kind"] == "search_reference"
        )
        assert rows[0]["snippet"] == "Synthetic name"
        reference = rows[0]["platform_reference"]
        assert reference["discovery_backend"] == "linkedin_mcp"
        assert reference["access"] == "connected_search_reference_only"
        assert (
            reference["direct_read_status"] == "not_attempted"
            and reference["subject_identity"] == "unknown"
        )
    else:
        assert not rows and "PRIVATE UPSTREAM" not in result.text
