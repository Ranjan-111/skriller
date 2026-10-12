import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from skriller.connectors.search import ExaKeylessSearch, parse_hits
from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.jobs.budget import BudgetExhausted, current_usage
from skriller.jobs.outbox import submit

pytestmark = pytest.mark.integration_db


def context_for(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Free search")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Search")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            limits=Limits(search_calls=1),
        )
        row = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], row["id"], str(uuid4()))
    return ExecutionContext(
        workspace_id=workspace,
        job_id=job["id"],
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        attempt_budget=1,
    )


class SearchFixture(ExaKeylessSearch):
    calls = 0

    async def search(self, *_args, **_kwargs):
        self.calls += 1
        await asyncio.sleep(0.02)
        return parse_hits(
            "Title: Aurora\nURL: https://aurora.example\nPublished: N/A\nAuthor: N/A\nHighlights:\nFintech",
            1,
        )


async def test_one_page_budget_prevents_second_network_operation(database):
    context = context_for(database)
    client = SearchFixture()
    result = await client.search_job(
        database, context, "fintech", operation_key="one", objective="company pages"
    )
    assert result.hits[0].evidence_kind == "search_snippet"
    with pytest.raises(BudgetExhausted):
        await client.search_job(
            database, context, "more", operation_key="two", objective="more pages"
        )
    assert client.calls == 1
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["search_calls"] == 1


async def test_duplicate_operation_cannot_share_reservation_and_call_twice(database):
    context = context_for(database)
    client = SearchFixture()

    async def call():
        return await client.search_job(
            database, context, "fintech", operation_key="same", objective="company pages"
        )

    results = await asyncio.gather(call(), call(), return_exceptions=True)
    assert sum(isinstance(value, ValueError) for value in results) == 1
    assert client.calls == 1


async def test_cancelled_search_keeps_explicit_uncertain_attempt_accounting(database):
    import sqlalchemy as sa

    from skriller.db.schema import reservations

    context = context_for(database)
    entered = asyncio.Event()

    class WaitingSearch(ExaKeylessSearch):
        async def search(self, *_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(
        WaitingSearch().search_job(
            database, context, "fintech", operation_key="cancelled", objective="company pages"
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        row = (
            session.execute(
                sa.select(reservations).where(reservations.c.idempotency_key == "cancelled")
            )
            .mappings()
            .one()
        )
        assert row["state"] == "committed" and row["reconciliation_status"] == "estimated"
        assert current_usage(session, str(context.job_id))[1]["search_calls"] == 1
