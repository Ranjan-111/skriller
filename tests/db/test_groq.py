"""Real ledger/capacity and official OpenAI-compatible client, no network."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, SecretStr

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.extraction.groq import (
    GROQ_BASE_URL,
    GROQ_MODEL,
    GroqStructuredModel,
    structured_model,
)
from skriller.extraction.models import ModelUnavailable
from skriller.jobs.outbox import submit
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    contact: str | None


def context_for(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Groq fixture")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Fixture")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
            limits=Limits(llm_calls=1, token_cap=5000),
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


def response(content):
    return {
        "id": "fixture",
        "object": "chat.completion",
        "created": 1,
        "model": GROQ_MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
    }


async def test_sdk_schema_endpoint_usage_and_no_shared_mutation(database):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=response('{"company":"Aurora","contact":null}'))

    client = GroqStructuredModel(
        SecretStr("synthetic-not-real-key"),
        free_tier_confirmed=True,
        transport=httpx.MockTransport(transport),
    )
    try:
        answer = await client.invoke_job(
            database, context_for(database), "Extract supplied Aurora", Facts, operation_key="valid"
        )
        assert answer.tokens == 80 and answer.model == GROQ_MODEL and answer.data["contact"] is None
        assert len(calls) == 1 and str(calls[0].url) == GROQ_BASE_URL + "/chat/completions"
        payload = json.loads(calls[0].content)
        assert payload["max_completion_tokens"] == 512 and payload["stream"] is False
        assert payload["response_format"]["json_schema"]["schema"] == Facts.model_json_schema()
        assert payload["response_format"]["json_schema"]["strict"] is False
        assert client.model.max_retries == 0 and "response_format" not in client.model.model_kwargs
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status,code", [(429, "rate_limited"), (503, "source_unavailable"), (401, "source_unavailable")]
)
async def test_sdk_error_one_call_redacted_estimated_and_capacity_released(
    database, status, code, caplog, monkeypatch
):
    from skriller.extraction import models

    releases = []
    original_release = models.release

    def recorded_release(*args, **kwargs):
        result = original_release(*args, **kwargs)
        releases.append(result)
        return result

    monkeypatch.setattr(models, "release", recorded_release)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Retry-After": "2"},
            json={"error": {"message": "secret-provider-detail", "type": "fixture"}},
        )

    client = GroqStructuredModel(
        SecretStr("synthetic-not-real-key"),
        free_tier_confirmed=True,
        transport=httpx.MockTransport(transport),
    )
    context = context_for(database)
    try:
        with pytest.raises(ModelUnavailable) as caught:
            await client.invoke_job(database, context, "Source", Facts, operation_key="failed")
        assert caught.value.failure.code == code and len(calls) == 1
        assert (
            "secret-provider-detail" not in str(caught.value)
            and "secret-provider-detail" not in caplog.text
        )
        if status == 429:
            assert caught.value.failure.retry_after_seconds == 2
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            row = (
                session.execute(
                    sa.select(reservations).where(reservations.c.idempotency_key == "failed")
                )
                .mappings()
                .one()
            )
            assert row["reconciliation_status"] == "estimated" and row["amount_usd"] == 0
        assert releases == [True]
    finally:
        await client.aclose()
        if status == 429:
            await asyncio.sleep(2.1)  # Persisted Retry-After cadence spans workspaces.


async def test_transport_bounds_and_schema_invalid_known_usage(database):
    def transport(request):
        return httpx.Response(200, json=response('{"company":42,"contact":null}'))

    client = GroqStructuredModel(
        SecretStr("synthetic-not-real-key"),
        free_tier_confirmed=True,
        transport=httpx.MockTransport(transport),
    )
    context = context_for(database)
    try:
        with pytest.raises(ModelUnavailable) as caught:
            await client.invoke_job(
                database, context, "Extract", Facts, operation_key="invalid-schema"
            )
        assert caught.value.failure.code == "schema_invalid"
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            row = (
                session.execute(
                    sa.select(reservations).where(
                        reservations.c.idempotency_key == "invalid-schema"
                    )
                )
                .mappings()
                .one()
            )
            assert row["actual_dimensions"]["tokens"] == 80
    finally:
        await client.aclose()


def test_settings_secret_local_default_and_explicit_groq_opt_in():
    settings = Settings(_env_file=None, GROQ_API_KEY="synthetic-not-real-key")
    assert settings.model_provider == "ollama" and "synthetic" not in repr(settings)
    assert structured_model(settings).source == "ollama"
    with pytest.raises(ValueError, match="confirmation"):
        structured_model(settings.model_copy(update={"model_provider": "groq"}))
    with pytest.raises(ValueError, match="requires"):
        structured_model(
            settings.model_copy(update={"model_provider": "groq", "groq_api_key": None})
        )


async def test_bounded_transport_denies_other_hosts_and_oversized_body():
    from skriller.extraction.groq import BoundedTransport

    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 131073)

    async with httpx.AsyncClient(
        transport=BoundedTransport(httpx.MockTransport(transport))
    ) as client:
        with pytest.raises(ValueError, match="endpoint"):
            await client.get("https://example.com/")
        assert not calls
        with pytest.raises(ValueError, match="transport limit"):
            await client.get(GROQ_BASE_URL + "/chat/completions")
        assert len(calls) == 1
