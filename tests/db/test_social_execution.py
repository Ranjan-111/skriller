"""Real tenant/owner/generation controls; browser output is a synthetic receipt."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_research_workflow import prepare

from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.facebook_read import FacebookRead
from skriller.connectors.facebook_read import parse_profile_response as facebook_profile
from skriller.connectors.instagram_read import InstagramRead
from skriller.connectors.instagram_read import parse_profile_response as instagram_profile
from skriller.connectors.social_executor import ConcreteSocialExecutor, SocialUnavailable
from skriller.connectors.switches import set_disabled
from skriller.contracts import ExecutionContext
from skriller.db import JobRepository, WorkspaceRepository
from skriller.jobs.control import cancel
from skriller.jobs.outbox import submit
from skriller.security.runner import RunResult
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


class Runner:
    def __init__(self, source):
        self.source = source
        self.calls = []
        self.after = None

    def run(self, operation, target, **kwargs):
        assert operation == self.source + "_profile"
        assert kwargs["cancel_check"]() is False
        material = kwargs["credential_material"].injection()
        expected = (
            {"INSTAGRAM_SESSION_COOKIE": "synthetic-session"}
            if self.source == "instagram"
            else {"FACEBOOK_SESSION_COOKIE": "synthetic-session", "FACEBOOK_USER_ID": "12345"}
        )
        assert material == expected
        request = json.loads(target)
        self.calls.append(request)
        if self.after:
            self.after()
        now = datetime.now(UTC)
        if self.source == "instagram":
            output = instagram_profile(
                [
                    {
                        "username": "synthetic",
                        "name": "Synthetic",
                        "private": False,
                        "followers": None,
                        "following": 0,
                        "posts": 12,
                        "verified": None,
                        "bio": "Fixture",
                    }
                ],
                InstagramRead(username=request["username"]),
                observed_at=now,
            )
        else:
            output = facebook_profile(
                [
                    {
                        "username": "synthetic",
                        "name": "Synthetic",
                        "friends": "-",
                        "followers": "1.2K followers",
                        "url": "https://www.facebook.com/synthetic",
                    }
                ],
                FacebookRead(username=request["username"]),
                observed_at=now,
            )
        return RunResult(
            "completed",
            0,
            json.dumps(
                {
                    "data": output.model_dump(mode="json"),
                    "network_requests_seen": 5,
                    "api_requests": 1 if self.source == "instagram" else 0,
                }
            ),
            "",
            1,
        )


def prepared(database, monkeypatch, source):
    actor = "social-" + uuid4().hex
    _, _, accepted = prepare(database, monkeypatch, actor, sources=[source], settings=Settings())
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    payload = {"session_cookie": "synthetic-session"}
    if source == "facebook":
        payload["user_id"] = "12345"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        connection = store.create(
            session,
            source,
            "session",
            SecretPayload(credentials=payload),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("read",),
        )
    context = ExecutionContext(
        workspace_id=UUID(accepted["workspace_id"]),
        job_id=UUID(accepted["job_id"]),
        actor_id=actor,
        plan_revision=1,
        connection_ref=connection.id,
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        attempt_budget=1,
    )
    executor = ConcreteSocialExecutor(source, "sha256:" + "a" * 64)
    executor.runner = Runner(source)
    request = (
        InstagramRead(username="synthetic")
        if source == "instagram"
        else FacebookRead(username="synthetic")
    )
    return actor, accepted, store, context, executor, request, payload


@pytest.mark.parametrize("source", ["instagram", "facebook"])
@pytest.mark.parametrize(
    "boundary",
    ["valid", "revoked", "wrong_generation", "read_disabled", "cancelled", "rotate_during"],
)
def test_scoped_read_discards_stale_credentials_before_or_after_worker(
    database, monkeypatch, source, boundary
):
    actor, accepted, store, context, executor, request, credentials = prepared(
        database, monkeypatch, source
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        material = store.load_for_runner(session, context, source + "_profile")
        if boundary == "revoked":
            store.revoke(session, context.connection_ref)
        elif boundary == "read_disabled":
            set_disabled(session, source, "read", True)
        elif boundary == "cancelled":
            cancel(session, accepted["job_id"])

    def rotate():
        with database.tenant(actor, accepted["workspace_id"]) as session:
            reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials={**credentials, "session_cookie": "replacement"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    if boundary == "rotate_during":
        executor.runner.after = rotate
    call = lambda: executor.execute(
        request,
        database=database,
        store=store,
        context=context,
        expected_credential_ref=uuid4()
        if boundary == "wrong_generation"
        else material.credential_ref,
    )
    if boundary == "valid":
        result = call()
        assert result.data.subject_identity == "unknown"
        assert result.network_requests_seen == 5
        if source == "instagram":
            assert result.data.followers is None
        else:
            assert result.data.followers_display == "1.2K followers"
    else:
        with pytest.raises(SocialUnavailable):
            call()
    assert len(executor.runner.calls) == (1 if boundary in {"valid", "rotate_during"} else 0)


@pytest.mark.parametrize("source", ["instagram", "facebook"])
@pytest.mark.parametrize("role", ["member", "owner"])
def test_another_workspace_initiator_cannot_reuse_the_source_owners_session(
    database, monkeypatch, source, role
):
    actor, accepted, store, context, executor, request, _ = prepared(database, monkeypatch, source)
    other = "social-other-" + uuid4().hex
    with database.tenant(actor, accepted["workspace_id"]) as session:
        WorkspaceRepository.add_member(session, other, role)
    with database.tenant(other, accepted["workspace_id"]) as session:
        previous = JobRepository.get(session, accepted["job_id"])
        job = submit(session, previous["conversation_id"], previous["plan_id"], uuid4().hex)
    context = context.model_copy(update={"actor_id": other, "job_id": UUID(job["id"])})
    with pytest.raises(SocialUnavailable):
        executor.execute(request, database=database, store=store, context=context)
    assert executor.runner.calls == []


@pytest.mark.parametrize("source", ["instagram", "facebook"])
@pytest.mark.parametrize("boundary", ["read_only", "discover_disabled"])
def test_search_requires_discover_scope_and_its_own_kill_switch(
    database, monkeypatch, source, boundary
):
    from skriller.connectors.facebook_read import FacebookSearch
    from skriller.connectors.instagram_read import InstagramSearch

    actor, accepted, store, context, executor, _, credentials = prepared(
        database, monkeypatch, source
    )
    if boundary == "discover_disabled":
        with database.tenant(actor, accepted["workspace_id"]) as session:
            replacement = reconnect(
                session,
                store,
                context.connection_ref,
                SecretPayload(credentials=credentials),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=("read", "discover"),
            )
            set_disabled(session, source, "discover", True)
        context = context.model_copy(update={"connection_ref": replacement.id})
    request = (
        InstagramSearch(query="synthetic")
        if source == "instagram"
        else FacebookSearch(query="synthetic")
    )
    with pytest.raises(SocialUnavailable):
        executor.execute(request, database=database, store=store, context=context)
    assert executor.runner.calls == []


def test_incomplete_facebook_session_never_reaches_a_worker(database, monkeypatch):
    actor, accepted, store, context, executor, request, _ = prepared(
        database, monkeypatch, "facebook"
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        replacement = store.create(
            session,
            "facebook",
            "session",
            SecretPayload(credentials={"session_cookie": "synthetic-only"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    context = context.model_copy(update={"connection_ref": replacement.id})
    with pytest.raises(SocialUnavailable):
        executor.execute(request, database=database, store=store, context=context)
    assert executor.runner.calls == []


@pytest.mark.parametrize("source", ["instagram", "facebook"])
def test_readiness_distinguishes_read_scope_from_discovery_and_never_claims_a_live_check(
    database, monkeypatch, source
):
    from skriller.connectors.diagnostics import diagnose

    actor, accepted, store, _, _, _, _ = prepared(database, monkeypatch, source)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        rows = diagnose(
            session, database=database, connection_store=store, social_image="sha256:" + "a" * 64
        )
    statuses = {row.capability.operation: row for row in rows if row.capability.source == source}
    assert statuses["read"].setup_state == "experimental"
    assert statuses["discover"].setup_state == "needs_connection"
    assert statuses["read"].credential_validation == "not_performed"
    assert statuses["read"].capability.engineering_status == "implemented"
