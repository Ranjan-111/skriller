"""Copied saved-content node under actual tenant model-call accounting."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.extraction.cleanup import ContextChunk, EvidenceNode, PreparedContext
from skriller.extraction.graph import extract_saved
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import current_usage
from skriller.jobs.outbox import submit


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str | None


class Stub:
    def __init__(self, malformed=False):
        self.prompts = []
        self.malformed = malformed

    async def ainvoke(self, messages, config):
        self.prompts.append(messages)
        assert config["callbacks"] == []
        return AIMessage(
            content="invalid" if self.malformed else '{"company":"Aurora Ledger"}',
            usage_metadata=None
            if self.malformed
            else {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


def context_for(database, call_cap=2):
    actor = f"saved-graph-{uuid4()}"
    workspace = database.create_workspace(actor, "Saved graph fixture")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="company",
            limits=Limits(llm_calls=call_cap, token_cap=8192),
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
    return ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job["id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        attempt_budget=2,
    )


def prepared():
    # Saved-context consumer fixture: HTML cleanup/tokenizer asset integration is
    # verified separately. Provider tests must not fetch tokenizer assets.
    return PreparedContext(
        source_url="https://example.org/company",
        source_sha256="a" * 64,
        title="Company",
        chunks=(ContextChunk("fixture", "Aurora Ledger", 3),),
        evidence=(EvidenceNode("company-name", "/html/body/p", "Aurora Ledger", "text"),),
        input_bytes=90,
        total_chunks=1,
        omitted_chunks=0,
        omitted_evidence_nodes=0,
        omitted_scripts=0,
        issues=(),
    )


@pytest.mark.asyncio
async def test_saved_context_reuses_copied_node_without_fetch_and_accounts_call(
    database, monkeypatch
):
    from scrapegraphai.nodes import FetchNode

    monkeypatch.setattr(
        FetchNode, "execute", lambda *args: pytest.fail("Saved content must never fetch")
    )
    context = context_for(database)
    stub = Stub()
    result = await extract_saved(
        database,
        context,
        prepared(),
        "Extract company",
        Facts,
        operation_key="extract",
        model=LocalStructuredModel(model_instance=stub),
    )
    assert result.failure is None
    assert result.answers[0].data == {"company": "Aurora Ledger"}
    assert result.answers[0].evidence_ids
    assert result.qualification == "unverified"
    assert len(stub.prompts) == 1
    sent = stub.prompts[0][1].content
    assert "untrusted_source" in sent and result.answers[0].evidence_ids[0] in sent
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        usage = current_usage(session, str(context.job_id))
        assert usage[1]["llm_calls"] == 1
        assert usage[1]["tokens"] == 30


@pytest.mark.asyncio
async def test_chunks_sequential_stop_before_second_io_when_budget_exhausted(database):
    context = context_for(database, call_cap=1)
    source = replace(
        prepared(),
        chunks=(ContextChunk("a", "Aurora Ledger", 3), ContextChunk("b", "Another paragraph", 3)),
        total_chunks=2,
    )
    stub = Stub()
    result = await extract_saved(
        database,
        context,
        source,
        "Extract company",
        Facts,
        operation_key="extract",
        model=LocalStructuredModel(model_instance=stub),
    )
    assert len(stub.prompts) == len(result.answers) == 1
    assert result.failure.code == "budget_exhausted"
    assert result.omitted_chunks == 1 and not result.coverage_complete


@pytest.mark.asyncio
async def test_failed_answer_no_retry_and_uncertain_charge_retained(database):
    context = context_for(database)
    stub = Stub(malformed=True)
    result = await extract_saved(
        database,
        context,
        prepared(),
        "Extract company",
        Facts,
        operation_key="failed",
        model=LocalStructuredModel(model_instance=stub),
    )
    assert not result.answers
    assert result.failure.code == "schema_invalid"
    assert len(stub.prompts) == 1
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        usage = current_usage(session, str(context.job_id))
        assert usage[1]["llm_calls"] == 1
        assert usage[1]["tokens"] == 4096


@pytest.mark.asyncio
async def test_chunk_cap_does_not_spawn_parallel_or_merge_calls(database):
    context = context_for(database)
    source = replace(
        prepared(),
        chunks=(ContextChunk("a", "Aurora Ledger", 3), ContextChunk("b", "Another paragraph", 3)),
        total_chunks=2,
    )
    stub = Stub()
    result = await extract_saved(
        database,
        context,
        source,
        "Extract company",
        Facts,
        operation_key="cap",
        max_chunks=1,
        model=LocalStructuredModel(model_instance=stub),
    )
    assert len(stub.prompts) == 1 and result.omitted_chunks == 1
    assert not result.coverage_complete
    with pytest.raises(TypeError):
        await extract_saved(
            database, context, "https://example.org", "Extract company", Facts, operation_key="url"
        )


async def test_configured_groq_owned_client_uses_caller_loop_and_closes(database, monkeypatch):
    import asyncio

    import httpx
    from pydantic import SecretStr

    from skriller.extraction import graph
    from skriller.extraction.groq import GROQ_MODEL, GroqStructuredModel
    from skriller.settings import Settings

    loop = asyncio.get_running_loop()
    calls = []

    def transport(request):
        assert asyncio.get_running_loop() is loop
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": GROQ_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"company":"Aurora Ledger"}'},
                    }
                ],
                "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
            },
        )

    client = GroqStructuredModel(
        SecretStr("synthetic-not-real-key"),
        free_tier_confirmed=True,
        transport=httpx.MockTransport(transport),
    )
    settings = Settings(_env_file=None, model_provider="groq")

    def factory(selected):
        assert selected is settings
        return client

    monkeypatch.setattr(graph, "structured_model", factory)
    source = replace(
        prepared(),
        chunks=(ContextChunk("a", "Aurora Ledger", 3), ContextChunk("b", "Aurora Ledger", 3)),
        total_chunks=2,
    )
    result = await extract_saved(
        database,
        context_for(database),
        source,
        "Extract company",
        Facts,
        operation_key="configured-groq",
        settings=settings,
    )
    assert result.failure is None and len(result.answers) == len(calls) == 2
    assert all(answer.model == GROQ_MODEL for answer in result.answers)
    assert client.http_client.is_closed


async def test_injected_provider_client_remains_caller_owned(database):
    class Closable(LocalStructuredModel):
        closed = False

        async def aclose(self):
            self.closed = True

    client = Closable(model_instance=Stub())
    result = await extract_saved(
        database,
        context_for(database),
        prepared(),
        "Extract company",
        Facts,
        operation_key="caller-owned",
        model=client,
    )
    assert result.failure is None and not client.closed


async def test_owned_client_closes_after_bounded_inflight_call_and_stops_next_chunk(
    database, monkeypatch
):
    import asyncio

    from skriller.extraction import graph

    class Waiting(Stub):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.finish = asyncio.Event()

        async def ainvoke(self, messages, config):
            self.entered.set()
            await self.finish.wait()
            return await super().ainvoke(messages, config)

    class Closable(LocalStructuredModel):
        closed = False

        async def aclose(self):
            self.closed = True

    stub = Waiting()
    client = Closable(model_instance=stub)
    monkeypatch.setattr(graph, "structured_model", lambda _settings: client)
    source = replace(
        prepared(),
        chunks=(ContextChunk("a", "Aurora Ledger", 3), ContextChunk("b", "Aurora Ledger", 3)),
        total_chunks=2,
    )
    task = asyncio.create_task(
        extract_saved(
            database,
            context_for(database),
            source,
            "Extract company",
            Facts,
            operation_key="cancel-owned",
        )
    )
    await asyncio.wait_for(stub.entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not client.closed
    stub.finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.closed and len(stub.prompts) == 1
