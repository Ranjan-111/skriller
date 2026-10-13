import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, ValidationError

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.extraction.models import LocalStructuredModel, ModelBounds, ModelUnavailable
from skriller.jobs.budget import BudgetExhausted, current_usage
from skriller.jobs.outbox import submit

pytestmark = pytest.mark.integration_db


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    contact: str | None


def context_for(database, **limits):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Local model")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Model")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            limits=Limits(llm_calls=1, token_cap=5000, **limits),
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


class ModelFixture:
    def __init__(self, content='{"company":"Aurora","contact":null}', usage=True):
        self.calls = 0
        self.message = AIMessage(
            content=content,
            usage_metadata={"input_tokens": 60, "output_tokens": 20, "total_tokens": 80}
            if usage
            else None,
        )

    async def ainvoke(self, messages, config):
        assert config == {"callbacks": []}
        assert "untrusted data" in messages[0].content
        self.calls += 1
        await asyncio.sleep(0.01)
        return self.message


def reservation(database, context, key):
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        return dict(
            session.execute(sa.select(reservations).where(reservations.c.idempotency_key == key))
            .mappings()
            .one()
        )


async def test_copied_structured_parser_with_actual_token_ledger(database):
    context = context_for(database)
    fixture = ModelFixture()
    client = LocalStructuredModel(model_instance=fixture)
    answer = await client.invoke_job(
        database,
        context,
        "Extract supplied company. No contact stated.",
        Facts,
        operation_key="valid",
    )
    assert answer.data == {"company": "Aurora", "contact": None}
    assert answer.usage_status == "confirmed" and answer.tokens == 80
    row = reservation(database, context, "valid")
    assert row["dimensions"] == {"llm_calls": 1, "tokens": 4096}
    assert row["actual_dimensions"] == {"llm_calls": 1, "tokens": 80}
    assert row["actual_cost_usd"] == 0
    with pytest.raises(BudgetExhausted):
        await client.invoke_job(database, context, "More facts", Facts, operation_key="second")
    assert fixture.calls == 1


async def test_missing_metadata_keeps_conservative_estimate(database):
    context = context_for(database)
    answer = await LocalStructuredModel(model_instance=ModelFixture(usage=False)).invoke_job(
        database, context, "Extract company", Facts, operation_key="missing-usage"
    )
    assert answer.tokens == 4096 and answer.usage_status == "estimated"
    assert reservation(database, context, "missing-usage")["reconciliation_status"] == "estimated"


@pytest.mark.parametrize(
    "content",
    [
        '{"company":"Aurora"}',
        '{"company":123,"contact":null}',
        "raw secret credential abc",
        '{"company":"Aurora","contact":null,"invented":true}',
    ],
)
@pytest.mark.parametrize("known_usage", [True, False])
async def test_invalid_schema_is_redacted_and_accounted_without_retry(
    database, content, known_usage
):
    context = context_for(database)
    fixture = ModelFixture(content, usage=known_usage)
    with pytest.raises(ModelUnavailable, match="valid result") as caught:
        await LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "Source secret", Facts, operation_key="invalid"
        )
    assert caught.value.failure.code == "schema_invalid"
    assert "abc" not in str(caught.value) and "Source secret" not in str(caught.value)
    assert fixture.calls == 1
    assert reservation(database, context, "invalid")["reconciliation_status"] == (
        "confirmed" if known_usage else "estimated"
    )


async def test_timeout_and_cancelled_call_preserve_uncertain_usage(database):
    class WaitingModel:
        calls = 0

        def __init__(self):
            self.entered = asyncio.Event()

        async def ainvoke(self, *_args, **_kwargs):
            self.calls += 1
            self.entered.set()
            await asyncio.Event().wait()

    context = context_for(database)
    fixture = WaitingModel()
    client = LocalStructuredModel(ModelBounds(timeout_seconds=0.02), model_instance=fixture)
    with pytest.raises(ModelUnavailable) as caught:
        await client.invoke_job(database, context, "Extract", Facts, operation_key="timeout")
    assert caught.value.failure.code == "deadline_exceeded" and fixture.calls == 1
    assert reservation(database, context, "timeout")["reconciliation_status"] == "estimated"
    other = context_for(database)
    waiting = WaitingModel()
    task = asyncio.create_task(
        LocalStructuredModel(model_instance=waiting).invoke_job(
            database, other, "Extract", Facts, operation_key="cancelled"
        )
    )
    await asyncio.wait_for(waiting.entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reservation(database, other, "cancelled")["reconciliation_status"] == "estimated"


async def test_concurrent_duplicate_operation_invokes_once(database):
    context = context_for(database)
    fixture = ModelFixture()
    client = LocalStructuredModel(model_instance=fixture)

    async def call():
        return await client.invoke_job(database, context, "Extract", Facts, operation_key="same")

    answers = await asyncio.gather(call(), call(), return_exceptions=True)
    assert sum(isinstance(item, ValueError) for item in answers) == 1
    assert fixture.calls == 1


async def test_bounds_revision_deadline_and_pre_reserved_context_block_io(database):
    context = context_for(database)
    fixture = ModelFixture()
    client = LocalStructuredModel(model_instance=fixture)
    with pytest.raises(ValueError, match="token bound"):
        await client.invoke_job(database, context, "x" * 5000, Facts, operation_key="too-large")
    with pytest.raises(ValueError, match="revision"):
        await client.invoke_job(
            database,
            context.model_copy(update={"plan_revision": 2}),
            "Extract",
            Facts,
            operation_key="revision",
        )
    with pytest.raises(ValueError, match="Pre-reserved"):
        await client.invoke_job(
            database,
            context.model_copy(update={"reservation_id": uuid4()}),
            "Extract",
            Facts,
            operation_key="pre-reserved",
        )
    with pytest.raises(ModelUnavailable):
        await client.invoke_job(
            database,
            context.model_copy(update={"deadline": datetime.now(UTC) - timedelta(seconds=1)}),
            "Extract",
            Facts,
            operation_key="expired",
        )
    assert fixture.calls == 0
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["llm_calls"] == 0


def test_only_local_allowlisted_models_and_finite_bounds():
    for kwargs in [
        {"model": "openai/gpt"},
        {"timeout_seconds": float("inf")},
        {"output_tokens": 2000},
        {"token_bound": 5000},
        {"output_tokens": True},
    ]:
        with pytest.raises(ValidationError):
            ModelBounds(**kwargs)


async def test_actual_usage_overrun_is_recorded_and_pauses_job(database):
    from skriller.db import JobRepository

    context = context_for(database)
    fixture = ModelFixture()
    fixture.message = AIMessage(
        content='{"company":"Aurora","contact":null}',
        usage_metadata={"input_tokens": 4500, "output_tokens": 500, "total_tokens": 5000},
    )
    with pytest.raises(ModelUnavailable) as caught:
        await LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "Extract", Facts, operation_key="overrun"
        )
    assert caught.value.failure.code == "budget_exhausted"
    row = reservation(database, context, "overrun")
    assert (
        row["actual_dimensions"]["tokens"] == 5000 and row["reconciliation_status"] == "confirmed"
    )
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert JobRepository.get(session, str(context.job_id))["state"] == "paused"


async def test_persisted_job_deadline_blocks_call_even_with_future_context(database):
    from skriller.db import JobRepository
    from skriller.db.schema import jobs

    context = context_for(database)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        session.execute(
            sa.update(jobs)
            .where(jobs.c.id == str(context.job_id))
            .values(created_at=sa.func.now() - sa.text("interval '1 hour'"))
        )
    fixture = ModelFixture()
    with pytest.raises(ModelUnavailable):
        await LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "Extract", Facts, operation_key="job-expired"
        )
    assert fixture.calls == 0
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert JobRepository.get(session, str(context.job_id))["state"] == "paused"
        assert current_usage(session, str(context.job_id))[1]["llm_calls"] == 0


def test_production_client_has_no_cloud_route_and_explicit_output_timeout_limits():
    client = LocalStructuredModel(
        ModelBounds(model="deepseek-r1:8b", timeout_seconds=12, output_tokens=100)
    )
    assert client.model.base_url == "http://127.0.0.1:11434"
    assert client.model.model == "deepseek-r1:8b"
    assert client.model.num_predict == 100 and client.model.num_ctx == 4096
    assert client.model.reasoning is False
    assert client.model.client_kwargs == {"timeout": 12, "trust_env": False}


async def test_provider_error_is_redacted_without_retry(database, caplog):
    class Broken:
        calls = 0

        async def ainvoke(self, *_args, **_kwargs):
            self.calls += 1
            raise RuntimeError("secret SDK credential abc")

    context = context_for(database)
    fixture = Broken()
    with pytest.raises(ModelUnavailable) as caught:
        await LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "private prompt abc", Facts, operation_key="provider-failed"
        )
    assert caught.value.failure.code == "source_unavailable"
    assert "abc" not in str(caught.value) and "abc" not in caplog.text
    assert fixture.calls == 1
    assert reservation(database, context, "provider-failed")["reconciliation_status"] == "estimated"


async def test_output_token_limit_refuses_result_but_keeps_actual_accounting(database):
    context = context_for(database)
    fixture = ModelFixture()
    fixture.message = AIMessage(
        content='{"company":"Aurora","contact":null}',
        usage_metadata={"input_tokens": 60, "output_tokens": 600, "total_tokens": 660},
    )
    with pytest.raises(ModelUnavailable, match="output limit"):
        await LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "Extract", Facts, operation_key="output-overrun"
        )
    assert reservation(database, context, "output-overrun")["actual_dimensions"]["tokens"] == 660


async def test_shared_model_capacity_blocks_other_job_then_releases_after_cancellation(database):
    from skriller.jobs.capacity import CapacityUnavailable

    class Waiting:
        def __init__(self):
            self.entered = asyncio.Event()
            self.stopped = False

        async def ainvoke(self, *_args, **_kwargs):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.stopped = True

    first = context_for(database)
    second = context_for(database)
    waiting = Waiting()
    task = asyncio.create_task(
        LocalStructuredModel(model_instance=waiting).invoke_job(
            database, first, "Extract", Facts, operation_key="holding-model"
        )
    )
    await asyncio.wait_for(waiting.entered.wait(), 2)
    fixture = ModelFixture()
    other = LocalStructuredModel(model_instance=fixture)
    with pytest.raises(CapacityUnavailable):
        await other.invoke_job(database, second, "Extract", Facts, operation_key="blocked-model")
    assert fixture.calls == 0
    with database.tenant(second.actor_id, str(second.workspace_id)) as session:
        assert current_usage(session, str(second.job_id))[1]["llm_calls"] == 0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert waiting.stopped
    answer = await other.invoke_job(
        database, second, "Extract", Facts, operation_key="blocked-model"
    )
    assert answer.usage_status == "confirmed" and fixture.calls == 1


async def test_cancellation_during_reservation_releases_unused_ledger_and_capacity(
    database, monkeypatch
):
    import threading

    from skriller.extraction import models

    entered = threading.Event()
    proceed = threading.Event()
    original = models.acquire

    def slow_acquire(*args, **kwargs):
        lease = original(*args, **kwargs)
        entered.set()
        assert proceed.wait(timeout=2)
        return lease

    monkeypatch.setattr(models, "acquire", slow_acquire)
    context = context_for(database)
    fixture = ModelFixture()
    task = asyncio.create_task(
        LocalStructuredModel(model_instance=fixture).invoke_job(
            database, context, "Extract", Facts, operation_key="cancel-prepare"
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fixture.calls == 0
    assert (
        reservation(database, context, "cancel-prepare")["reconciliation_status"] == "not_charged"
    )
    monkeypatch.setattr(models, "acquire", original)
    result = await LocalStructuredModel(model_instance=fixture).invoke_job(
        database, context, "Extract", Facts, operation_key="next-call"
    )
    assert result.usage_status == "confirmed"


async def test_copied_graph_schema_instructions_are_not_duplicated(database):
    from scrapegraphai.utils.output_parser import get_pydantic_output_parser

    class InspectModel(ModelFixture):
        async def ainvoke(self, messages, config):
            assert "JSON schema" not in messages[0].content
            assert "JSON schema" in messages[1].content
            return await super().ainvoke(messages, config)

    context = context_for(database)
    prompt = (
        "Extract supplied company.\n" + get_pydantic_output_parser(Facts).get_format_instructions()
    )
    answer = await LocalStructuredModel(model_instance=InspectModel()).invoke_job(
        database, context, prompt, Facts, operation_key="graph-schema", prompt_includes_schema=True
    )
    assert answer.data["contact"] is None


async def test_official_ollama_sdk_sends_schema_format_without_shared_mutation(database):
    import json

    import httpx
    from langchain_ollama import ChatOllama

    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/x-ndjson"},
            content=json.dumps(
                {
                    "model": "llama3.2:3b",
                    "created_at": "2026-10-13T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": '{"company":"Aurora","contact":null}',
                    },
                    "done": True,
                    "prompt_eval_count": 60,
                    "eval_count": 20,
                }
            )
            + "\n",
        )

    official = ChatOllama(
        model="llama3.2:3b",
        base_url="http://127.0.0.1:11434",
        format="json",
        num_predict=512,
        num_ctx=4096,
        reasoning=False,
        client_kwargs={"timeout": 5, "trust_env": False},
        async_client_kwargs={"transport": httpx.MockTransport(transport)},
    )
    context = context_for(database)
    answer = await LocalStructuredModel(model_instance=official).invoke_job(
        database, context, "Extract", Facts, operation_key="official-sdk"
    )
    assert answer.data["contact"] is None and answer.tokens == 80
    assert len(requests) == 1 and str(requests[0].url) == "http://127.0.0.1:11434/api/chat"
    payload = json.loads(requests[0].content)
    assert payload["format"] == Facts.model_json_schema()
    assert payload["model"] == "llama3.2:3b" and payload["options"]["num_predict"] == 512
    assert payload["options"]["num_ctx"] == 4096 and payload["think"] is False
    assert official.format == "json"


async def test_official_sdk_failure_has_one_request_without_fallback(database):
    import httpx
    from langchain_ollama import ChatOllama

    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(500, json={"error": "private local provider details"})

    official = ChatOllama(
        model="llama3.2:3b",
        base_url="http://127.0.0.1:11434",
        format="json",
        num_predict=512,
        client_kwargs={"timeout": 5, "trust_env": False},
        async_client_kwargs={"transport": httpx.MockTransport(transport)},
    )
    context = context_for(database)
    with pytest.raises(ModelUnavailable) as caught:
        await LocalStructuredModel(model_instance=official).invoke_job(
            database, context, "Extract", Facts, operation_key="official-sdk-failure"
        )
    assert caught.value.failure.code == "source_unavailable"
    assert len(requests) == 1 and requests[0].url.host == "127.0.0.1"
    assert "provider details" not in str(caught.value)
