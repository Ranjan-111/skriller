"""Durable initial planning with real restricted-role ledger and outbox."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage

from skriller.contracts import Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.schema import attempts, jobs, outbox, plans, reservations, stage_checkpoints
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import current_usage, reserve
from skriller.jobs.control import cancel
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker
from skriller.research.bootstrap import execute_planning
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db
SETTINGS = Settings(_env_file=None, enable_ai_planning=True)


class Fixture:
    calls = 0

    def __init__(self, output=None):
        self.output = output or {"entity_type": "person", "entity_quote": "founders"}

    async def ainvoke(self, *_args, **_kwargs):
        self.calls += 1
        return AIMessage(
            content=json.dumps(self.output),
            usage_metadata={"input_tokens": 60, "output_tokens": 20, "total_tokens": 80},
        )


def setup(database, prompt="Find founders"):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Planning bootstrap")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Fixture")
        ConversationRepository.add_message(session, conversation["id"], "user", prompt)
        seed = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="person",
            sources=["web"],
            limits=Limits(
                llm_calls=1, token_cap=4096, search_calls=1, fetch_attempts=0, deadline_seconds=120
            ),
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], seed.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        session.execute(sa.update(jobs).where(jobs.c.id == job["id"]).values(purpose="planning"))
    payload = {"workspace_id": workspace, "job_id": job["id"], "actor_id": actor}
    outcome = CheckpointWorker(database, {}).schedule(payload)
    payload["attempt_id"] = outcome["attempt_id"]
    return payload


def run(database, payload, fixture):
    return execute_planning(
        database, payload, SETTINGS, LocalStructuredModel(model_instance=fixture)
    )


def test_successor_binding_checkpoint_and_discovery_outbox_are_idempotent(database):
    payload = setup(database)
    fixture = Fixture()
    outcome = run(database, payload, fixture)
    assert outcome["planning_status"] == "ready" and fixture.calls == 1
    assert run(database, payload, fixture) == {"status": "checkpointed"} and fixture.calls == 1
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        job = JobRepository.get(session, payload["job_id"])
        assert (
            job["plan_id"] == outcome["plan_id"]
            and job["stage"] == "discovering"
            and job["purpose"] == "research"
        )
        revision = ConversationRepository.get_plan(session, job["plan_id"])
        assert revision["revision"] == 2 and revision["parent_id"]
        assert revision["interpretation"]["limits"]["llm_calls"] == 1
        assert current_usage(session, job["id"])[1]["tokens"] == 80
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(stage_checkpoints)
                .where(stage_checkpoints.c.job_id == job["id"])
            ).scalar_one()
            == 1
        )
        rows = (
            session.execute(
                sa.select(outbox).where(
                    outbox.c.job_id == job["id"], outbox.c.attempt_id.is_not(None)
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2 and all(
            set(JobRepository.broker_payload(row))
            <= {"workspace_id", "job_id", "actor_id", "attempt_id"}
            for row in rows
        )


@pytest.mark.parametrize(
    "output,status",
    [
        ({"entity_type": "person", "entity_quote": "invented"}, "ungrounded_quote"),
        (
            {"entity_type": "person", "entity_quote": "founders", "invented": "secret"},
            "schema_invalid",
        ),
    ],
)
def test_invalid_planning_is_visible_pause_and_never_empty_completion(database, output, status):
    payload = setup(database)
    fixture = Fixture(output)
    assert run(database, payload, fixture)["status"] == status
    assert run(database, payload, fixture)["status"] == "not_dispatchable"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        job = JobRepository.get(session, payload["job_id"])
        assert job["state"] == "paused" and job["failure_code"] == status and fixture.calls == 1
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(plans)
                .where(plans.c.conversation_id == job["conversation_id"])
            ).scalar_one()
            == 1
        )
        assert any(
            event["kind"] == "planning_summary" and event["details"]["status"] == status
            for event in JobRepository.events_after(session, job["id"])
        )


def test_clarification_commits_grounded_plan_without_search_dispatch(database):
    payload = setup(database, "Find founders in Paris")
    fixture = Fixture(
        {
            "entity_type": "person",
            "entity_quote": "founders",
            "rules": [["must_have", "location", "contains", "Paris", "in Paris"]],
        }
    )
    assert run(database, payload, fixture)["planning_status"] == "clarification_required"
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        job = JobRepository.get(session, payload["job_id"])
        assert job["state"] == "paused" and job["stage"] == "planning"
        assert ConversationRepository.get_plan(session, job["plan_id"])["interpretation"][
            "clarification"
        ]
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(attempts)
                .where(attempts.c.job_id == job["id"], attempts.c.stage == "discovering")
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("control", ["cancel", "deadline", "disabled"])
def test_controls_block_model_io(database, control):
    payload = setup(database)
    fixture = Fixture()
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        if control == "cancel":
            cancel(session, payload["job_id"])
        elif control == "deadline":
            session.execute(
                sa.update(jobs)
                .where(jobs.c.id == payload["job_id"])
                .values(created_at=datetime.now(UTC) - timedelta(hours=1))
            )
    execute_planning(
        database,
        payload,
        Settings(_env_file=None) if control == "disabled" else SETTINGS,
        LocalStructuredModel(model_instance=fixture),
    )
    assert fixture.calls == 0


def test_expired_planning_lease_with_lost_reserved_call_pauses_without_retry(database):
    payload = setup(database)
    fixture = Fixture()
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        JobRepository.transition(session, payload["job_id"], "running", stage="planning")
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == payload["attempt_id"])
            .values(
                state="running",
                lease_owner=str(uuid4()),
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                generation=1,
            )
        )
        reservation = reserve(
            session,
            payload["job_id"],
            f"planning:{payload['attempt_id']}",
            0,
            {"llm_calls": 1, "tokens": 4096},
        )
    assert (
        run(database, payload, fixture)["status"] == "planning_interrupted" and fixture.calls == 0
    )
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        row = (
            session.execute(sa.select(reservations).where(reservations.c.id == reservation["id"]))
            .mappings()
            .one()
        )
        assert row["reconciliation_status"] == "estimated"


def test_cancellation_during_model_call_keeps_charge_without_successor(database):
    payload = setup(database)

    class Cancelling(Fixture):
        async def ainvoke(self, *args, **kwargs):
            with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
                cancel(session, payload["job_id"])
            return await super().ainvoke(*args, **kwargs)

    fixture = Cancelling()
    assert run(database, payload, fixture)["status"] == "lost_lease"
    assert fixture.calls == 1
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        job = JobRepository.get(session, payload["job_id"])
        assert job["state"] == "cancelled" and job["purpose"] == "planning"
        assert current_usage(session, job["id"])[1]["tokens"] == 80
        assert (
            session.execute(
                sa.select(sa.func.count())
                .select_from(plans)
                .where(plans.c.conversation_id == job["conversation_id"])
            ).scalar_one()
            == 1
        )
