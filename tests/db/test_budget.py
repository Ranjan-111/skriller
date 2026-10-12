from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest

from skriller.contracts import Limits, SearchPlan
from skriller.db import ConversationRepository, Database, JobRepository
from skriller.jobs.budget import BudgetExhausted, current_usage, reconcile, reserve

pytestmark = pytest.mark.integration_db


def job_fixture(database, cap="0.01", token_cap=100):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Budget")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Budgeted research")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            limits=Limits(currency_cap=cap, token_cap=token_cap),
        )
        record = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = JobRepository.create(session, conversation["id"], record["id"], str(uuid4()))
        JobRepository.transition(session, job["id"], "queued")
    return actor, workspace, job["id"]


def test_parallel_reservations_cannot_spend_last_budget_twice(database):
    actor, workspace, job = job_fixture(database)
    db = Database(database.engine.url, pool_size=2)

    def worker(index):
        try:
            with db.tenant(actor, workspace) as session:
                return reserve(session, job, str(index), "0.01", {"llm_calls": 1, "tokens": 80})[
                    "id"
                ]
        except BudgetExhausted:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(worker, range(2)))
        assert sum(value is not None for value in outcomes) == 1
        with db.tenant(actor, workspace) as session:
            cost, counters = current_usage(session, job)
            assert cost == Decimal("0.01") and counters["tokens"] == 80
    finally:
        db.dispose()


def test_uncertain_charge_is_retained_then_confirmed_once_even_without_results(database):
    actor, workspace, job = job_fixture(database)
    with database.tenant(actor, workspace) as session:
        row = reserve(session, job, "call", "0.01", {"llm_calls": 1, "tokens": 100})
        reconcile(session, job, row["id"], status="estimated")
        assert current_usage(session, job)[0] == Decimal("0.01")
        with pytest.raises(BudgetExhausted):
            reserve(session, job, "next", "0.001", {"llm_calls": 1})
    with database.tenant(actor, workspace) as session:
        outcome = reconcile(
            session,
            job,
            row["id"],
            status="confirmed",
            cost="0.003",
            actual_dimensions={"llm_calls": 1, "tokens": 20},
        )
        assert outcome["reconciliation_status"] == "confirmed"
        assert current_usage(session, job) == (
            Decimal("0.003"),
            {"search_calls": 0, "candidates": 0, "fetch_attempts": 0, "llm_calls": 1, "tokens": 20},
        )
        assert (
            reconcile(
                session,
                job,
                row["id"],
                status="confirmed",
                cost="0.003",
                actual_dimensions={"llm_calls": 1, "tokens": 20},
            )["id"]
            == row["id"]
        )
        with pytest.raises(ValueError, match="Conflicting"):
            reconcile(
                session,
                job,
                row["id"],
                status="confirmed",
                cost="0.004",
                actual_dimensions={"llm_calls": 1},
            )
        events = JobRepository.events_after(session, job)
        assert [r["details"]["status"] for r in events if r["kind"] == "usage_reconciled"] == [
            "estimated",
            "confirmed",
        ]


def test_no_charge_release_and_overrun_remain_truthful(database):
    actor, workspace, job = job_fixture(database)
    with database.tenant(actor, workspace) as session:
        row = reserve(session, job, "no-call", "0.01", {"tokens": 100})
        reconcile(session, job, row["id"], status="not_charged")
        assert current_usage(session, job)[0] == 0
        next_row = reserve(session, job, "provider-overrun", "0.01", {"tokens": 100})
        reconcile(
            session,
            job,
            next_row["id"],
            status="confirmed",
            cost="0.02",
            actual_dimensions={"tokens": 101},
        )
        assert current_usage(session, job)[0] == Decimal("0.02")
        assert JobRepository.get(session, job)["state"] == "paused"
        with pytest.raises(ValueError, match="permit new calls"):
            reserve(session, job, "after-overrun", 0, {"tokens": 1})


def test_dimensions_and_unreserved_ledger_are_not_ignored(database):
    actor, workspace, job = job_fixture(database, cap="0.02")
    with database.tenant(actor, workspace) as session:
        JobRepository.usage(session, job, "legacy-charge", "tokens", 99, "0.01")
        with pytest.raises(BudgetExhausted):
            reserve(session, job, "too-many-tokens", 0, {"tokens": 2})
        with pytest.raises(BudgetExhausted):
            reserve(session, job, "too-much-money", "0.02", {"llm_calls": 1})
        with pytest.raises(ValueError):
            reserve(session, job, "arbitrary-kind", 0, {"shell_command": 1})
        row = reserve(session, job, "valid", 0, {"tokens": 1})
        assert reserve(session, job, "valid", 0, {"tokens": 1})["id"] == row["id"]
        with pytest.raises(ValueError, match="different"):
            reserve(session, job, "valid", 0, {"tokens": 2})
