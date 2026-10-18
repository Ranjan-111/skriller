"""Real RLS and single-use renewal; all provider receipts are synthetic."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from test_reddit_oauth import setup, start

from skriller.connections.reddit_renewal import RedditAccessRenewal
from skriller.connections.store import SecretPayload
from skriller.connections.tables import connections
from skriller.connections.x_oauth import refresh_consent
from skriller.connectors.reddit_oauth import RedditOAuthUnavailable, configuration
from skriller.connectors.switches import set_disabled
from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, WorkspaceRepository
from skriller.db.schema import jobs
from skriller.jobs.control import cancel, plan_for_job
from skriller.jobs.outbox import submit

pytestmark = pytest.mark.integration_db


def prepared(database):
    actor, workspace, app, client, path = setup(database)
    body = start(client, path)
    response = client.post(path + "/complete", json=body)
    assert response.status_code == 201, response.text
    reference = response.json()["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "renewal fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="discussion",
            sources=["reddit"],
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], uuid4().hex)
        session.execute(
            sa.update(connections)
            .where(connections.c.id == reference, connections.c.workspace_id == workspace)
            .values(expires_at=datetime.now(UTC) + timedelta(seconds=20))
        )
    renewal = RedditAccessRenewal(
        database,
        app.state.reddit_consent_store,
        configuration(app.state.settings),
        app.state.reddit_oauth_provider,
    )
    return actor, workspace, app, body, reference, job, renewal


def test_due_access_renews_once_without_extending_consent_retention(database):
    actor, workspace, app, body, previous, job, renewal = prepared(database)
    store = app.state.reddit_consent_store
    with database.tenant(actor, workspace) as session:
        retained_until = store.get(session, body["consent_id"])["expires_at"]
    assert renewal.prepare(actor, workspace, job["id"]) is True
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 1
    with database.tenant(actor, workspace) as session:
        row = store.get(session, body["consent_id"])
        assert row["connection_id"] != previous
        assert row["expires_at"] == retained_until
        assert store.connections.metadata(session, UUID(previous)).state == "revoked"
        assert store.open(row)["refresh_token"] == "Reddit_REFRESH_ROTATED_123"


def test_member_and_other_owner_do_not_open_or_renew_initiator_grant(database):
    actor, workspace, app, _, _, job, renewal = prepared(database)
    for role in ("member", "owner"):
        other = role + uuid4().hex
        with database.tenant(actor, workspace) as session:
            WorkspaceRepository.add_member(session, other, role)
        assert renewal.prepare(other, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 0


def test_cancelled_job_does_not_consume_due_refresh_grant(database):
    actor, workspace, app, body, _, job, renewal = prepared(database)
    with database.tenant(actor, workspace) as session:
        cancel(session, job["id"])
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 0
    with database.tenant(actor, workspace) as session:
        assert app.state.reddit_consent_store.get(session, body["consent_id"])["state"] == "active"


def test_renewal_does_not_extend_a_job_near_its_deadline(database):
    actor, workspace, app, _, _, job, renewal = prepared(database)
    with database.tenant(actor, workspace) as session:
        plan = plan_for_job(session, job)
        session.execute(
            sa.update(jobs)
            .where(jobs.c.id == job["id"])
            .values(
                created_at=datetime.now(UTC) - timedelta(seconds=plan.limits.deadline_seconds - 5)
            )
        )
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 0


def test_another_eligible_account_prevents_implicit_renewal_selection(database):
    actor, workspace, app, _, _, job, renewal = prepared(database)
    with database.tenant(actor, workspace) as session:
        app.state.reddit_consent_store.connections.create(
            session,
            "reddit",
            "oauth",
            SecretPayload(credentials={"access_token": "other-token"}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("read", "discover"),
        )
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 0


@pytest.mark.parametrize("operation", ["discover", "read"])
def test_source_kill_switch_prevents_token_io(database, operation):
    actor, workspace, app, _, _, job, renewal = prepared(database)
    with database.tenant(actor, workspace) as session:
        set_disabled(session, "reddit", operation, True)
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 0


def test_uncertain_renewal_is_revoked_and_never_retried(database):
    actor, workspace, app, body, _, job, renewal = prepared(database)

    def failed():
        raise RuntimeError("PRIVATE_PROVIDER_SENTINEL")

    app.state.reddit_oauth_provider.hook = failed
    with pytest.raises(RedditOAuthUnavailable, match="configuration or reconnection") as error:
        renewal.prepare(actor, workspace, job["id"])
    assert "SENTINEL" not in str(error.value)
    assert renewal.prepare(actor, workspace, job["id"]) is False
    assert app.state.reddit_oauth_provider.refreshes == 1
    with database.tenant(actor, workspace) as session:
        assert app.state.reddit_consent_store.get(session, body["consent_id"])["state"] == "revoked"


def test_stale_renewal_selection_cannot_consume_replacement_grant(database):
    actor, workspace, app, body, previous, job, renewal = prepared(database)
    assert renewal.prepare(actor, workspace, job["id"]) is True
    with pytest.raises(RedditOAuthUnavailable):
        refresh_consent(
            database,
            app.state.reddit_consent_store,
            configuration(app.state.settings),
            app.state.reddit_oauth_provider,
            actor,
            workspace,
            UUID(body["consent_id"]),
            expected_connection=UUID(previous),
        )
    assert app.state.reddit_oauth_provider.refreshes == 1


@pytest.mark.parametrize("uncertain", [False, True])
def test_durable_discovery_renews_before_read_and_does_not_fallback_on_uncertainty(
    database, monkeypatch, uncertain
):
    import json
    from urllib.parse import parse_qs, urlsplit

    from test_reddit_continuation import listing
    from test_reddit_continuation import prepared as prepare_workflow
    from test_reddit_oauth import Provider as TokenProvider
    from test_research_workflow import Provider as IndexedProvider
    from test_research_workflow import isolate_capacity

    from skriller.connections.reddit_oauth import RedditConsentStore
    from skriller.connections.x_oauth import complete_consent
    from skriller.connectors.reddit_oauth import RedditOAuthConfiguration
    from skriller.jobs.worker import CheckpointWorker
    from skriller.research.service import execute_discovery
    from skriller.security.runner import RunResult

    actor, _, accepted, access_store, context, reader = prepare_workflow(database, monkeypatch)
    config = RedditOAuthConfiguration(
        "fixture-client", "PRIVATE_CLIENT", "http://localhost:3000/callback", "skriller-fixture/0.1"
    )
    store = RedditConsentStore(access_store.keyring)
    token_provider = TokenProvider()
    with database.tenant(actor, accepted["workspace_id"]) as session:
        access_store.revoke(session, context.connection_ref)
        consent = store.start(session, config, opt_in=True)
    state = parse_qs(urlsplit(consent["authorization_url"]).query)["state"][0]
    reference = complete_consent(
        database,
        store,
        config,
        token_provider,
        actor,
        accepted["workspace_id"],
        UUID(consent["consent_id"]),
        state,
        "fixture-code",
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        session.execute(
            sa.update(connections)
            .where(connections.c.id == str(reference.id))
            .values(expires_at=datetime.now(UTC) + timedelta(seconds=20))
        )

    class RenewedRunner:
        calls = 0

        def run(self, operation, target, **kwargs):
            self.calls += 1
            assert kwargs["credential_material"].injection() == {
                "REDDIT_ACCESS_TOKEN": "Reddit_ACCESS_ROTATED_123"
            }
            assert not kwargs["cancel_check"]()
            return RunResult("completed", 0, json.dumps(listing(1, after=None)), "", 1)

    reader.runner = RenewedRunner()
    if uncertain:

        def failed():
            raise RuntimeError("PRIVATE_TOKEN_FAILURE")

        token_provider.hook = failed
    renewal = RedditAccessRenewal(database, store, config, token_provider)
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
        "actor_id": actor,
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    indexed = IndexedProvider()
    outcome = execute_discovery(
        database,
        payload,
        indexed,
        reddit_reader=reader,
        connection_store=access_store,
        reddit_renewal=renewal.prepare,
    )
    assert indexed.calls == 0
    assert token_provider.refreshes == 1
    assert reader.runner.calls == (0 if uncertain else 1)
    if not uncertain:
        assert outcome["status"] == "checkpointed" and len(outcome["entity_ids"]) == 1
        execute_discovery(
            database,
            payload,
            indexed,
            reddit_reader=reader,
            connection_store=access_store,
            reddit_renewal=renewal.prepare,
        )
        assert token_provider.refreshes == 1 and reader.runner.calls == 1
