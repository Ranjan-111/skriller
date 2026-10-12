"""Copied saved-content node under actual tenant model-call accounting."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.extraction.cleanup import ContextChunk, PreparedContext, prepare_context
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
    value = prepare_context(
        "<html><head><title>Company</title></head><body><p>Aurora Ledger</p></body></html>",
        "https://example.org/company",
    )
    assert isinstance(value, PreparedContext)
    return value


@pytest.mark.asyncio
async def test_saved_html_reuses_copied_node_without_fetch_and_accounts_call(database, monkeypatch):
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
