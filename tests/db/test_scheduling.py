"""Durable opt-in schedule leases reuse actual job/outbox/admission records."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_saved_lists import setup

from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.switches import set_disabled
from skriller.db import ConversationRepository, Database, WorkspaceAccessDenied, WorkspaceRepository
from skriller.db.schema import jobs, outbox
from skriller.entitlements import admissions, policies, policy_for
from skriller.lists import create_list
from skriller.scheduling import (
    claim_due,
    create_schedule,
    disable_schedule,
    execute_due,
    runs,
    schedules,
)

pytestmark = pytest.mark.integration_db


def configured(database, *, max_runs=1, required_connection=False):
    actor, workspace, entity, plan = setup(database)
    connection = None
    with database.tenant(actor, workspace) as session:
        revision = ConversationRepository.get_plan(session, plan)
        ConversationRepository.add_message(
            session, revision["conversation_id"], "user", "Find software companies"
        )
        revised = ConversationRepository.revise_plan(
            session,
            revision["conversation_id"],
            {**revision["interpretation"], "revision": revision["revision"] + 1},
            parent_id=revision["id"],
        )
        plan = revised["id"]
        if required_connection:
            connection = ConnectionStore(Keyring("v1", {"v1": b"k" * 32})).create(
                session,
                "linkedin",
                "session",
                SecretPayload(credentials={"session_cookie": "fixture-token"}),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        saved = create_list(session, "Scheduled fixture", plan, (entity,))
        schedule = create_schedule(
            session,
            saved["id"],
            opt_in=True,
            cadence_hours=1,
            max_runs=max_runs,
            required_connection_ids=(str(connection.id),) if connection else (),
        )
        session.execute(
            sa.update(schedules)
            .where(schedules.c.id == schedule["id"])
            .values(next_due_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    return actor, workspace, schedule, connection


def count(session, table):
    return session.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()


def test_restart_and_duplicate_lease_create_one_job_admission_and_outbox(database):
    actor, workspace, _schedule, _ = configured(database)
    with database.tenant(actor, workspace) as session:
        task = claim_due(session)
    restarted = Database(
        str(database.engine.url.render_as_string(hide_password=False)), pool_size=1
    )
    try:
        with restarted.tenant(actor, workspace) as session:
            assert claim_due(session) is None
            result = execute_due(session, task, search_enabled=True)
            assert result["status"] == "queued"
        with restarted.tenant(actor, workspace) as session:
            assert execute_due(session, task, search_enabled=True)["status"] == "stale_lease"
            assert claim_due(session) is None
            assert (
                count(session, runs)
                == count(session, jobs)
                == count(session, outbox)
                == count(session, admissions)
                == 1
            )
            saved = session.execute(sa.select(schedules)).mappings().one()
            assert saved["run_count"] == 1 and not saved["enabled"]
            assert saved["last_job_id"] == result["job_id"]
    finally:
        restarted.dispose()


def test_expired_claim_and_restart_preserve_due_occurrence(database):
    actor, workspace, _, _ = configured(database)
    with database.tenant(actor, workspace) as session:
        old = claim_due(session)
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(schedules).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with database.tenant(actor, workspace) as session:
        current = claim_due(session)
        assert current["lease_token"] != old["lease_token"]
        assert execute_due(session, old, search_enabled=True)["status"] == "stale_lease"
        assert execute_due(session, current, search_enabled=True)["status"] == "queued"
        assert count(session, runs) == 1


@pytest.mark.parametrize("block", ["source", "quota", "search", "connection"])
def test_disabled_or_exhausted_sources_and_quota_never_queue_job(database, block):
    actor, workspace, _, connection = configured(
        database, required_connection=block == "connection"
    )
    with database.tenant(actor, workspace) as session:
        if block == "source":
            set_disabled(session, "linkedin", "discover", True)
        elif block == "quota":
            policy_for(session)
            session.execute(sa.update(policies).values(enabled=False))
        elif block == "connection":
            ConnectionStore(None).revoke(session, connection.id)
        task = claim_due(session)
    with database.tenant(actor, workspace) as session:
        result = execute_due(session, task, search_enabled=block != "search")
        assert result["status"] in {
            "source_disabled",
            "workspace_disabled",
            "search_unavailable",
            "source_disconnected",
        }
        assert result["job_id"] is None
        assert count(session, jobs) == count(session, outbox) == count(session, admissions) == 0
        assert session.execute(sa.select(schedules.c.enabled)).scalar_one() is False


def test_no_opt_in_no_member_or_foreign_mutation_and_disable_fences_claim(database):
    actor, workspace, schedule, _ = configured(database)
    member = f"schedule-member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, member)
        with pytest.raises(ValueError):
            create_schedule(session, schedule["list_id"], opt_in=False, cadence_hours=1, max_runs=1)
        task = claim_due(session)
    with database.tenant(member, workspace) as session:
        assert session.execute(sa.select(schedules)).all() == []
        with pytest.raises(WorkspaceAccessDenied):
            claim_due(session)
    with database.tenant(actor, workspace) as session:
        disable_schedule(session, schedule["id"])
        assert execute_due(session, task, search_enabled=True)["status"] == "stale_lease"
        assert count(session, jobs) == 0
    other = database.create_workspace(actor, "Another schedule workspace")["id"]
    with database.tenant(actor, other) as session:
        assert execute_due(session, task, search_enabled=True)["status"] == "stale_lease"


def test_previous_unfinished_run_pauses_without_overlap(database):
    actor, workspace, _, _ = configured(database, max_runs=2)
    with database.tenant(actor, workspace) as session:
        task = claim_due(session)
        assert execute_due(session, task, search_enabled=True)["status"] == "queued"
        session.execute(
            sa.update(schedules).values(next_due_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with database.tenant(actor, workspace) as session:
        task = claim_due(session)
        assert (
            execute_due(session, task, search_enabled=True)["status"] == "previous_run_incomplete"
        )
        assert count(session, jobs) == 1


@pytest.mark.parametrize("change", ["revoke", "disable", "demote"])
def test_queued_schedule_rechecks_authority_and_connection_before_worker_call(database, change):
    from skriller.db.schema import memberships
    from skriller.entitlements import execution_allowed

    actor, workspace, schedule, connection = configured(database, required_connection=True)
    with database.tenant(actor, workspace) as session:
        task = claim_due(session)
        job = execute_due(session, task, search_enabled=True)["job_id"]
    with database.tenant(actor, workspace) as session:
        if change == "revoke":
            ConnectionStore(None).revoke(session, connection.id)
        elif change == "disable":
            disable_schedule(session, schedule["id"])
        else:
            WorkspaceRepository.add_member(session, "other-owner-" + str(uuid4()), "owner")
            session.execute(
                sa.update(memberships).where(memberships.c.actor_id == actor).values(role="member")
            )
    with database.tenant(actor, workspace) as session:
        assert not execution_allowed(session, job)
        row = session.execute(sa.select(jobs).where(jobs.c.id == job)).mappings().one()
        assert row["state"] == "paused"
        assert row["failure_code"] in {
            "source_disconnected",
            "schedule_disabled",
            "schedule_unavailable",
        }


def test_scheduled_worker_keeps_original_prompt_after_followup_and_accounts_once(
    database, monkeypatch
):
    from test_research_workflow import Provider, run

    from skriller.db import JobRepository

    actor, workspace, _, _ = configured(database)
    with database.tenant(actor, workspace) as session:
        task = claim_due(session)
        job_id = execute_due(session, task, search_enabled=True)["job_id"]
        job = JobRepository.get(session, job_id)
        ConversationRepository.add_message(
            session, job["conversation_id"], "user", "Find unrelated automobile manufacturers"
        )

    class RecordingProvider(Provider):
        def __init__(self):
            super().__init__()
            self.objectives = []

        async def search(self, query, **kwargs):
            self.objectives.append(kwargs["objective"])
            return await super().search(query, **kwargs)

    provider = RecordingProvider()
    _payload, outcome = run(
        database, actor, {"workspace_id": workspace, "job_id": job_id}, provider, monkeypatch
    )
    assert outcome["status"] == "checkpointed"
    assert provider.calls == 2
    assert all("software" in query and "automobile" not in query for query in provider.objectives)
    with database.tenant(actor, workspace) as session:
        assert JobRepository.get(session, job_id)["state"] == "completed"
        assert count(session, admissions) == 1


def test_full_workspace_run_allowance_prevents_another_scheduled_admission(database):
    from skriller.entitlements import admit
    from skriller.jobs.outbox import submit
    from skriller.lists import saved_lists

    actor, workspace, schedule, _ = configured(database)
    with database.tenant(actor, workspace) as session:
        plan_id = session.execute(
            sa.select(saved_lists.c.plan_id).where(saved_lists.c.id == schedule["list_id"])
        ).scalar_one()
        revision = ConversationRepository.get_plan(session, plan_id)
        for index in range(25):
            job = submit(session, revision["conversation_id"], plan_id, f"quota-fixture:{index}")
            assert admit(session, job["id"]) is None
        task = claim_due(session)
    with database.tenant(actor, workspace) as session:
        assert execute_due(session, task, search_enabled=True) == {
            "status": "entitlement_exhausted",
            "job_id": None,
        }
        assert count(session, admissions) == count(session, jobs) == 25
        assert count(session, runs) == 0
