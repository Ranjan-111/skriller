"""Real quota races, queued dispatch, tenant/owner boundaries and provider gates."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from fastapi.testclient import TestClient
from test_outbox import planned

from skriller.api import create_app
from skriller.auth import Identity, require_identity
from skriller.connectors.fetch import FetchUnavailable, HTTPFetcher
from skriller.db import Database, JobRepository, WorkspaceRepository
from skriller.db.schema import outbox
from skriller.entitlements import (
    admissions,
    execution_allowed,
    policies,
    policy_view,
    update_settings,
)
from skriller.entitlements import (
    provision_manual_pilot as provision,
)
from skriller.jobs.control import permit_call
from skriller.jobs.outbox import DispatchScope, OutboxDispatcher, submit
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


def allowance(workspace, runs=1):
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            provision(
                connection,
                workspace,
                runs=runs,
                results=25,
                sources=3,
                invoice_reference="synthetic-manual-pilot",
            )
    finally:
        engine.dispose()


def queued(database, actor, workspace, conversation, plan):
    with database.tenant(actor, workspace) as session:
        return submit(session, conversation, plan, str(uuid4()))["id"]


def test_last_run_admission_is_atomic_and_replay_is_not_another_run(database):
    actor, workspace, conversation, plan = planned(database)
    allowance(workspace)
    ids = [queued(database, actor, workspace, conversation, plan) for _ in range(2)]
    db = Database(database.engine.url, pool_size=2)

    def admit(identifier):
        with db.tenant(actor, workspace) as session:
            return execution_allowed(session, identifier)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(admit, ids))
        assert sorted(outcomes) == [False, True]
        winner = ids[outcomes.index(True)]
        with db.tenant(actor, workspace) as session:
            assert execution_allowed(session, winner)
            assert (
                policy_view(session)["used_runs"] == 1
                and policy_view(session)["remaining_runs"] == 0
            )
            blocked = JobRepository.get(session, ids[outcomes.index(False)])
            assert (
                blocked["state"] == "paused" and blocked["failure_code"] == "entitlement_exhausted"
            )
    finally:
        db.dispose()


def test_exhausted_queued_job_is_discarded_without_publication(database):
    actor, workspace, conversation, plan = planned(database)
    allowance(workspace)
    first = queued(database, actor, workspace, conversation, plan)
    second = queued(database, actor, workspace, conversation, plan)
    with database.tenant(actor, workspace) as session:
        assert execution_allowed(session, first)

    class Publisher:
        def __init__(self):
            self.calls = []

        def publish(self, *args):
            self.calls.append(args)

    publisher = Publisher()
    OutboxDispatcher(database, publisher).dispatch_batch(DispatchScope(actor, workspace))
    assert len(publisher.calls) == 1 and publisher.calls[0][2]["job_id"] == first
    with database.tenant(actor, workspace) as session:
        row = session.execute(sa.select(outbox).where(outbox.c.job_id == second)).mappings().one()
        assert row["discarded_at"] is not None and row["published_at"] is None
        assert JobRepository.get(session, second)["failure_code"] == "entitlement_exhausted"


def test_members_can_execute_but_only_owner_changes_effective_settings(database):
    owner, workspace, conversation, plan = planned(database)
    member = f"entitlement-member-{uuid4()}"
    with database.tenant(owner, workspace) as session:
        WorkspaceRepository.add_member(session, member)
        policy_view(session)
    job = queued(database, member, workspace, conversation, plan)
    with database.tenant(member, workspace) as session:
        assert execution_allowed(session, job)
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(owner)
    client = TestClient(app)
    path = f"/v1/workspaces/{workspace}/entitlements"
    settings = {"enabled": True, "result_limit": 10, "source_limit": 2}
    assert client.put(path, json=settings).status_code == 200
    assert client.get(path).json()["can_manage"] is True
    assert client.put(path, json={**settings, "run_limit": 1000}).status_code == 422
    assert client.put(path, json={**settings, "result_limit": 100}).status_code == 422
    app.dependency_overrides[require_identity] = lambda: Identity(member)
    assert client.get(path).json()["used_runs"] == 1
    assert client.get(path).json()["can_manage"] is False
    assert client.put(path, json=settings).status_code == 403
    app.dependency_overrides[require_identity] = lambda: Identity(f"foreign-{uuid4()}")
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("attack", ["raise_cap", "change_tier", "refund_usage", "exceed_admission"])
def test_application_role_cannot_self_provision_or_refund(database, attack):
    actor, workspace, conversation, plan = planned(database)
    allowance(workspace)
    first = queued(database, actor, workspace, conversation, plan)
    with database.tenant(actor, workspace) as session:
        assert execution_allowed(session, first)
    second = queued(database, actor, workspace, conversation, plan)
    with pytest.raises(sa.exc.DBAPIError), database.tenant(actor, workspace) as session:
        if attack == "raise_cap":
            session.execute(
                sa.update(policies)
                .where(policies.c.workspace_id == workspace)
                .values(run_limit=1000)
            )
        elif attack == "change_tier":
            session.execute(
                sa.update(policies).where(policies.c.workspace_id == workspace).values(tier="trial")
            )
        elif attack == "refund_usage":
            session.execute(sa.delete(admissions).where(admissions.c.workspace_id == workspace))
        else:
            session.execute(
                sa.insert(admissions).values(workspace_id=workspace, job_id=second, actor_id=actor)
            )


def test_disabled_workspace_stops_direct_fetch_before_io(database, proxy):
    context = test_fetch.ctx(database)
    endpoint, requests, _ = proxy
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        update_settings(session, enabled=False, result_limit=25, source_limit=3)
    with pytest.raises(FetchUnavailable):
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            context, "http://example.com/company", source="web", operation_key="blocked-entitlement"
        )
    assert not requests
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert permit_call(session, str(context.job_id)) == 0
        assert (
            JobRepository.get(session, str(context.job_id))["failure_code"] == "workspace_disabled"
        )
        assert policy_view(session)["used_runs"] == 0


def test_request_limits_cannot_raise_spend_or_allocate_job(database, monkeypatch):
    from skriller.db import ConversationRepository
    from skriller.db.schema import jobs

    actor, workspace, _, _ = planned(database)
    with database.tenant(actor, workspace) as session:
        update_settings(session, enabled=True, result_limit=10, source_limit=2)
        conversation = ConversationRepository.create(session, "Entitlement request fixture")
    app = create_app(Settings())
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    path = f"/v1/conversations/{conversation['id']}/messages"
    for options in [
        {"sources": ["web"], "result_limit": 11},
        {"sources": ["web", "linkedin", "reddit"], "result_limit": 10},
    ]:
        response = client.post(path, json={"content": "Find companies", "options": options})
        assert (
            response.status_code == 422
            and response.headers["X-Skriller-Failure"] == "entitlement_limits"
        )
    response = client.post(
        path,
        json={
            "content": "Find companies",
            "limits": {"currency_cap": 100},
            "options": {"sources": ["web"], "result_limit": 10},
        },
    )
    assert response.status_code == 422
    with database.tenant(actor, workspace) as session:
        assert session.execute(sa.select(sa.func.count()).select_from(jobs)).scalar_one() == 0
    accepted = client.post(
        path,
        json={"content": "Find companies", "options": {"sources": ["web"], "result_limit": 10}},
    )
    assert accepted.status_code == 202
    with database.tenant(actor, workspace) as session:
        update_settings(session, enabled=True, result_limit=5, source_limit=2)

    class Publisher:
        def publish(self, *args):
            pytest.fail("Owner-lowered limits must stop queued dispatch")

    OutboxDispatcher(database, Publisher()).dispatch_batch(DispatchScope(actor, workspace))
    with database.tenant(actor, workspace) as session:
        assert (
            JobRepository.get(session, accepted.json()["job_id"])["failure_code"]
            == "entitlement_limits"
        )
        assert policy_view(session)["used_runs"] == 0


def test_manual_allowance_revisions_preserve_consumed_runs(database):
    actor, workspace, conversation, plan = planned(database)
    allowance(workspace)
    job = queued(database, actor, workspace, conversation, plan)
    with database.tenant(actor, workspace) as session:
        assert execution_allowed(session, job)
    allowance(workspace, runs=2)
    with database.tenant(actor, workspace) as session:
        assert (
            policy_view(session)["used_runs"] == 1 and policy_view(session)["remaining_runs"] == 1
        )
        with pytest.raises(PermissionError):
            provision(
                session.connection(),
                workspace,
                runs=1000,
                results=100,
                sources=9,
                invoice_reference="not-approved",
            )


def test_expired_queued_work_does_not_consume_trial_run(database):
    from skriller.db.schema import jobs

    actor, workspace, conversation, plan = planned(database)
    job = queued(database, actor, workspace, conversation, plan)
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.update(jobs)
                .where(jobs.c.workspace_id == workspace, jobs.c.id == job)
                .values(created_at=sa.func.now() - sa.text("interval '2 hours'"))
            )
    finally:
        engine.dispose()

    class Publisher:
        def publish(self, *args):
            pytest.fail("Expired jobs must not be published or admitted")

    OutboxDispatcher(database, Publisher()).dispatch_batch(DispatchScope(actor, workspace))
    with database.tenant(actor, workspace) as session:
        assert policy_view(session)["used_runs"] == 0
        assert JobRepository.get(session, job)["failure_code"] == "deadline_exceeded"
