"""Release fault injection against real scoped PostgreSQL transactions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
import sqlalchemy as sa
from test_worker import context, handler

from skriller.db import Database, JobRepository, ResearchRepository
from skriller.jobs.budget import current_usage, usage_report
from skriller.jobs.worker import CheckpointWorker

pytestmark = pytest.mark.integration_db


def test_commit_acknowledgment_error_returns_the_already_saved_checkpoint(database, monkeypatch):
    from contextlib import contextmanager

    payload = context(database)
    original = database.tenant
    armed, raised = False, False
    calls = []

    @contextmanager
    def ambiguous_commit(*args, **kwargs):
        nonlocal raised
        with original(*args, **kwargs) as session:
            yield session
        if armed and not raised:
            raised = True
            raise OSError("synthetic lost commit acknowledgment")

    def run(_plan):
        calls.append(1)
        return "Committed", 0, {"tokens": 4}

    def persist(session, data):
        nonlocal armed
        row = ResearchRepository.entity(session, "company", display_name=data)
        armed = True
        return [row["id"]]

    monkeypatch.setattr(database, "tenant", ambiguous_commit)
    worker = CheckpointWorker(database, {"discovering": replace(handler(run), persist=persist)})
    first = worker.execute(payload)
    assert first["status"] == "checkpointed" and raised
    assert worker.execute(payload) == first
    assert calls == [1]
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert current_usage(session, payload["job_id"])[1]["tokens"] == 4
        assert session.execute(sa.text("SELECT count(*) FROM stage_checkpoints")).scalar_one() == 1
        assert not any(
            row["kind"] == "checkpoint_failed"
            for row in JobRepository.events_after(session, payload["job_id"])
        )


@pytest.mark.parametrize("fault", ["exception", "sql_error", "foreign_reference", "invalid_usage"])
def test_post_reply_failure_keeps_usage_and_rolls_back_results_without_replay(database, fault):
    payload = context(database)
    other = context(database)
    with database.tenant(other["actor_id"], other["workspace_id"]) as session:
        foreign = ResearchRepository.entity(session, "company", display_name="Other tenant")
    calls = []

    def run(_plan):
        calls.append(1)
        return (
            "untrusted page text",
            0,
            {"tokens": -1} if fault == "invalid_usage" else {"tokens": 4},
        )

    def persist(session, _data):
        ResearchRepository.entity(session, "company", display_name="Must roll back")
        if fault == "exception":
            raise RuntimeError("sensitive source payload must not be recorded")
        if fault == "sql_error":
            session.execute(sa.text("SELECT 1 / 0"))
        return [foreign["id"]]

    worker = CheckpointWorker(database, {"discovering": replace(handler(run), persist=persist)})
    assert worker.execute(payload) == {"status": "checkpoint_failed"}
    assert worker.execute(payload) == {"status": "not_dispatchable"}
    assert calls == [1]
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert JobRepository.get(session, payload["job_id"])["state"] == "paused"
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 0
        assert session.execute(sa.text("SELECT count(*) FROM stage_checkpoints")).scalar_one() == 0
        assert current_usage(session, payload["job_id"])[1]["tokens"] == (
            10 if fault == "invalid_usage" else 4
        )
        amounts, counts = usage_report(session, payload["job_id"])
        bucket = "estimated" if fault == "invalid_usage" else "confirmed"
        assert counts[bucket]["tokens"] == (10 if fault == "invalid_usage" else 4)
        assert sum(amounts.values()) == 0
        events = JobRepository.events_after(session, payload["job_id"])
        failure = next(event for event in events if event["kind"] == "checkpoint_failed")
        assert failure["details"]["result_status"] == "not_committed"
        assert failure["details"]["cost_status"] == bucket
        assert "sensitive source payload" not in str(events)
        assert "untrusted page text" not in str(events)
        assert foreign["id"] not in str(events)


def test_duplicate_delivery_while_provider_runs_then_cancel_discards_late_result(database):
    payload = context(database)
    concurrent = Database(database.engine.url, pool_size=3)
    entered, finish = Event(), Event()
    calls = []

    def run(_plan):
        calls.append(1)
        entered.set()
        assert finish.wait(5)
        return "Late result", 0, {"tokens": 4}

    worker = CheckpointWorker(concurrent, {"discovering": handler(run)})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker.execute, payload)
            try:
                assert entered.wait(3)
                assert pool.submit(worker.execute, payload).result(timeout=3) == {
                    "status": "leased"
                }
                with concurrent.tenant(payload["actor_id"], payload["workspace_id"]) as session:
                    JobRepository.transition(session, payload["job_id"], "cancelled")
            finally:
                finish.set()
            assert first.result(timeout=3) == {"status": "lease_lost"}
        assert worker.execute(payload) == {"status": "not_dispatchable"}
        assert calls == [1]
        with concurrent.tenant(payload["actor_id"], payload["workspace_id"]) as session:
            assert current_usage(session, payload["job_id"])[1]["tokens"] == 4
            assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 0
            assert session.execute(sa.text("SELECT count(*) FROM reservations")).scalar_one() == 1
    finally:
        finish.set()
        concurrent.dispose()


def test_process_death_inside_result_transaction_retains_uncertainty_and_single_checkpoint(
    database,
):
    import json
    import select
    import subprocess
    import sys

    from skriller.db.schema import attempts

    payload = context(database)
    child_source = """
import json,signal,sys
from decimal import Decimal
from skriller.db import Database, ResearchRepository
from skriller.jobs.worker import CheckpointWorker, StageHandler
from skriller.settings import Settings
db=Database(Settings().application_database_url)
def persist(session,data):
    ResearchRepository.entity(session,"company",display_name="Uncommitted result")
    print("RESULT TRANSACTION OPEN",flush=True)
    signal.pause()
handler=StageHandler(lambda _: ("synthetic reply",0,{"tokens":2}),persist,Decimal(0),{"tokens":10})
CheckpointWorker(db,{"discovering":handler}).execute(json.loads(sys.argv[1]))
"""
    child = subprocess.Popen(
        [sys.executable, "-c", child_source, json.dumps(payload)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        ready, _, _ = select.select([child.stdout], [], [], 10)
        assert ready and child.stdout.readline().strip() == "RESULT TRANSACTION OPEN"
    finally:
        child.kill()
        child.communicate(timeout=5)

    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 0
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == payload["attempt_id"])
            .values(lease_expires_at=sa.func.now() - sa.text("interval '1 second'"))
        )
    worker = CheckpointWorker(
        database, {"discovering": handler(lambda _: ("Recovered", 0, {"tokens": 3}))}
    )
    result = worker.execute(payload)
    assert result["status"] == "checkpointed"
    assert worker.execute(payload) == result
    with database.tenant(payload["actor_id"], payload["workspace_id"]) as session:
        assert session.execute(sa.text("SELECT count(*) FROM entities")).scalar_one() == 1
        assert session.execute(sa.text("SELECT count(*) FROM stage_checkpoints")).scalar_one() == 1
        assert session.execute(
            sa.text("SELECT state FROM external_calls ORDER BY generation")
        ).scalars().all() == ["uncertain", "confirmed"]
        _, counters = usage_report(session, payload["job_id"])
        assert counters["estimated"]["tokens"] == 10
        assert counters["confirmed"]["tokens"] == 3
