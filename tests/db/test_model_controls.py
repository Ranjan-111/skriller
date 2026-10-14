"""Persisted stop controls interrupt official SDK async IO, with real ledger cleanup."""

import asyncio
from dataclasses import replace
from time import monotonic

import httpx
import pytest
import sqlalchemy as sa
from langchain_ollama import ChatOllama
from pydantic import SecretStr
from test_models import Facts, context_for, reservation
from test_saved_graph import prepared

from skriller.db import JobRepository
from skriller.db.schema import jobs
from skriller.extraction.cleanup import ContextChunk
from skriller.extraction.graph import extract_saved
from skriller.extraction.groq import GroqStructuredModel
from skriller.extraction.models import LocalStructuredModel, ModelUnavailable
from skriller.jobs.control import cancel

pytestmark = pytest.mark.integration_db


def client_for(provider, transport):
    if provider == "groq":
        return GroqStructuredModel(
            SecretStr("synthetic-not-real-key"),
            free_tier_confirmed=True,
            transport=httpx.MockTransport(transport),
        )
    return LocalStructuredModel(
        model_instance=ChatOllama(
            model="llama3.2:3b",
            base_url="http://127.0.0.1:11434",
            format="json",
            num_predict=512,
            client_kwargs={"timeout": 20, "trust_env": False},
            async_client_kwargs={"transport": httpx.MockTransport(transport)},
        )
    )


def persisted_stop(database, context, reason):
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        if reason == "cancelled":
            cancel(session, str(context.job_id))
        else:
            session.execute(
                sa.update(jobs)
                .where(jobs.c.id == str(context.job_id))
                .values(created_at=sa.func.now() - sa.text("interval '1 hour'"))
            )


@pytest.mark.parametrize("provider", ["ollama", "groq"])
@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
async def test_persisted_stop_interrupts_official_sdk_and_keeps_uncertain_reservation(
    database, provider, reason, caplog, monkeypatch
):
    from skriller.extraction import models

    entered, stopped = asyncio.Event(), asyncio.Event()
    calls, releases = [], []
    original_release = models.release

    def record_release(*args, **kwargs):
        result = original_release(*args, **kwargs)
        releases.append(result)
        return result

    monkeypatch.setattr(models, "release", record_release)

    async def transport(request):
        calls.append(request)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    context = context_for(database)
    client = client_for(provider, transport)
    task = asyncio.create_task(
        client.invoke_job(
            database, context, "private source fixture", Facts, operation_key="persisted-model-stop"
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        started = monotonic()
        await asyncio.to_thread(persisted_stop, database, context, reason)
        with pytest.raises(ModelUnavailable) as caught:
            await asyncio.wait_for(task, 5)
        assert monotonic() - started < 5
        assert caught.value.failure.code == reason
        assert stopped.is_set() and len(calls) == 1
        assert "private source fixture" not in caplog.text
        row = reservation(database, context, "persisted-model-stop")
        assert row["reconciliation_status"] == "estimated"
        assert row["dimensions"] == {"llm_calls": 1, "tokens": 4096}
        assert releases == [True]
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            assert JobRepository.get(session, str(context.job_id))["state"] == (
                "cancelled" if reason == "cancelled" else "paused"
            )
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if hasattr(client, "aclose"):
            await client.aclose()


@pytest.mark.parametrize("provider", ["ollama", "groq"])
async def test_persisted_model_stop_ends_saved_graph_without_second_chunk(database, provider):
    entered, stopped = asyncio.Event(), asyncio.Event()
    calls = []

    async def transport(request):
        calls.append(request)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    context = context_for(database)
    client = client_for(provider, transport)
    content = replace(
        prepared(),
        chunks=(
            ContextChunk("first", "Aurora Ledger", 3),
            ContextChunk("second", "Aurora Ledger", 3),
        ),
        total_chunks=2,
    )
    task = asyncio.create_task(
        extract_saved(
            database, context, content, "Extract", Facts, operation_key="stop-graph", model=client
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.to_thread(persisted_stop, database, context, "cancelled")
        result = await asyncio.wait_for(task, 5)
        assert result.failure.code == "cancelled"
        assert result.answers == () and result.omitted_chunks == 2
        assert stopped.is_set() and len(calls) == 1
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            from skriller.db.schema import reservations

            rows = session.execute(sa.select(reservations)).mappings().all()
            assert len(rows) == 1 and rows[0]["reconciliation_status"] == "estimated"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if hasattr(client, "aclose"):
            await client.aclose()


async def test_cancelled_late_response_is_refused_but_known_tokens_are_confirmed(database):
    from langchain_core.messages import AIMessage

    context = context_for(database)

    class LateResponse:
        calls = 0

        async def ainvoke(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.to_thread(persisted_stop, database, context, "cancelled")
            return AIMessage(
                content='{"company":"Aurora","contact":null}',
                usage_metadata={"input_tokens": 60, "output_tokens": 20, "total_tokens": 80},
            )

    provider = LateResponse()
    with pytest.raises(ModelUnavailable) as caught:
        await LocalStructuredModel(model_instance=provider).invoke_job(
            database, context, "Extract", Facts, operation_key="late-model-response"
        )
    assert caught.value.failure.code == "cancelled" and provider.calls == 1
    row = reservation(database, context, "late-model-response")
    assert row["reconciliation_status"] == "confirmed"
    assert row["actual_dimensions"] == {"llm_calls": 1, "tokens": 80}
