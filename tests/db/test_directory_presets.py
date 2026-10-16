"""Directory presets use the copied graph and real shared PostgreSQL ledger."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from test_saved_graph import prepared

from skriller.contracts import ExecutionContext
from skriller.db import ConversationRepository
from skriller.extraction.cleanup import ContextChunk, EvidenceNode
from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.presets import extract_directory_page
from skriller.jobs.budget import current_usage
from skriller.jobs.outbox import submit

pytestmark = pytest.mark.integration_db


class Stub:
    async def ainvoke(self, messages, config):
        assert config["callbacks"] == []
        assert "company_name" in messages[1].content
        return AIMessage(
            content=(
                '{"claims":[{"field":"company_name","value":"Aurora Ledger",'
                '"quote":"Aurora Ledger"}]}'
            ),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


class ExpiredJobStub:
    async def ainvoke(self, messages, config):
        assert config["callbacks"] == []
        return AIMessage(
            content=(
                '{"claims":['
                '{"field":"job_title","value":"Senior Engineer",'
                '"quote":"Senior Engineer — Open listing expired."},'
                '{"field":"job_listing_status","value":"Open",'
                '"quote":"Open listing expired"}]}'
            ),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


def context_for(database):
    actor = f"directory-preset-{uuid4()}"
    workspace = database.create_workspace(actor, "Directory preset fixture")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Fixture")
        plan = {
            "workspace_id": workspace,
            "conversation_id": conversation["id"],
            "revision": 1,
            "entity_type": "company",
            "limits": {"llm_calls": 1, "token_cap": 8192},
        }

        revision = ConversationRepository.revise_plan(session, conversation["id"], plan)
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
    return ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job["id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        attempt_budget=1,
    )


@pytest.mark.asyncio
async def test_company_preset_uses_shared_ledger_and_keeps_claim_source_specific(database):
    context = context_for(database)
    result = await extract_directory_page(
        database,
        context,
        prepared(),
        "company",
        operation_key="directory:company:1",
        model=LocalStructuredModel(model_instance=Stub()),
    )
    assert result.failure_code is None and result.coverage_complete
    assert len(result.claims) == 1
    assert result.claims[0].field == "company_name"
    assert result.claims[0].status == "source_specific_unverified"
    assert result.claims[0].evidence_ids == ("company-name",)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        usage = current_usage(session, str(context.job_id))
        assert usage[1]["llm_calls"] == 1 and usage[1]["tokens"] == 30


@pytest.mark.asyncio
async def test_expired_job_preset_does_not_emit_current_status(database):
    context = context_for(database)
    source = replace(
        prepared(),
        source_url="https://example.org/jobs/123",
        chunks=(ContextChunk("job", "Senior Engineer — Open listing expired.", 7),),
        evidence=(
            EvidenceNode(
                "job-status", "/html/body/p", "Senior Engineer — Open listing expired.", "text"
            ),
        ),
    )
    result = await extract_directory_page(
        database,
        context,
        source,
        "jobs",
        operation_key="directory:jobs:expired",
        model=LocalStructuredModel(model_instance=ExpiredJobStub()),
    )
    assert [claim.field for claim in result.claims] == ["job_title"]
    assert result.rejected_claims == 1
    assert all(claim.status == "source_specific_unverified" for claim in result.claims)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        usage = current_usage(session, str(context.job_id))
        assert usage[1]["llm_calls"] == 1 and usage[1]["tokens"] == 30
