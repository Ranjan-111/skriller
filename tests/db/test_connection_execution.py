"""Real vault/controls; controlled executors are not live platform authorization."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_connections import create, setup

from skriller.connections.execution import run_connected
from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connections.tables import connections
from skriller.security.runner import RunResult

pytestmark = pytest.mark.integration_db


def prepared(database):
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    actor, workspace, context = setup(database)
    with database.tenant(actor, workspace) as session:
        reference = create(session, store)
    return store, actor, workspace, context.model_copy(update={"connection_ref": reference.id})


def test_loaded_generation_is_exact_and_polls_do_not_decrypt_or_add_load_audits(database):
    from skriller.connections.tables import connection_audit

    store, actor, workspace, context = prepared(database)
    with database.tenant(actor, workspace) as session:
        material = store.load_for_runner(session, context, "linkedin_read")
        assert store.runner_current(session, context, material)
        assert store.runner_current(session, context, material)
        assert not store.runner_current(session, context, replace(material, credential_ref=uuid4()))
        assert not store.runner_current(session, context, replace(material, runner="reddit_read"))
        assert not store.runner_current(
            session, context.model_copy(update={"attempt_budget": 0}), material
        )
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(connection_audit)
                .where(
                    connection_audit.c.connection_id == str(context.connection_ref),
                    connection_audit.c.action == "loaded",
                )
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("action", ["revoke", "reconnect", "expire"])
def test_connection_change_stops_running_executor_and_discards_late_output(database, action):
    store, actor, workspace, context = prepared(database)

    class Executor:
        def run(self, operation, target, *, cancel_check, credential_material, **kwargs):
            assert operation == "linkedin_read"
            assert credential_material.connection_ref == context.connection_ref
            assert not cancel_check()
            with database.tenant(actor, workspace) as session:
                if action == "revoke":
                    store.revoke(session, context.connection_ref)
                elif action == "reconnect":
                    new = reconnect(
                        session,
                        store,
                        context.connection_ref,
                        SecretPayload(credentials={"session_cookie": "replacement-synthetic"}),
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                    assert new.id != context.connection_ref
                else:
                    session.execute(
                        sa.update(connections)
                        .where(connections.c.id == str(context.connection_ref))
                        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                    )
            assert cancel_check()
            return RunResult("completed", 0, "late source output", "", 1)

    result = run_connected(database, store, context, Executor(), "linkedin_read", "fixture")
    assert result.status == "needs_connection" and result.stdout == ""


def test_invalid_connection_never_dispatches_and_cleanup_failure_stays_visible(database):
    store, actor, workspace, context = prepared(database)

    class Executor:
        def run(self, *args, **kwargs):
            with database.tenant(actor, workspace) as session:
                store.revoke(session, context.connection_ref)
            return RunResult("cleanup_failed", 1, "", "cleanup failed", 1)

    assert (
        run_connected(database, store, context, Executor(), "linkedin_read", "fixture").status
        == "cleanup_failed"
    )
    # The same invalid reference must not reach the executor again.
    assert (
        run_connected(database, store, context, None, "linkedin_read", "fixture").status
        == "needs_connection"
    )


def test_reddit_session_cookie_is_distinct_from_an_oauth_access_token(database):
    from skriller.db import ConversationRepository

    store, actor, workspace, context = prepared(database)
    with database.tenant(actor, workspace) as session:
        # This is a separate explicit Reddit plan, not an implicit platform fallback.
        from uuid import UUID

        from skriller.contracts import SearchPlan
        from skriller.jobs.outbox import submit

        conversation = ConversationRepository.create(session, "Reddit credential contract")
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
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        for auth_kind, credential_field, environment_key in [
            ("session", "session_cookie", "REDDIT_SESSION_COOKIE"),
            ("oauth", "access_token", "REDDIT_ACCESS_TOKEN"),
        ]:
            reference = store.create(
                session,
                "reddit",
                auth_kind,
                SecretPayload(credentials={credential_field: "synthetic"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            bound = context.model_copy(
                update={"job_id": UUID(job["id"]), "connection_ref": reference.id}
            )
            material = store.load_for_runner(session, bound, "reddit_read")
            assert material.injection() == {environment_key: "synthetic"}
            assert store.runner_current(session, bound, material)


def test_executor_exception_never_exposes_loaded_secret(database):
    store, _actor, _workspace, context = prepared(database)

    class Executor:
        def run(self, *args, credential_material, **kwargs):
            raise RuntimeError(credential_material.injection()["LINKEDIN_SESSION_COOKIE"])

    result = run_connected(database, store, context, Executor(), "linkedin_read", "fixture")
    assert result.status == "unavailable"
    assert "fixture-session-token" not in repr(result)
