import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.extraction.models import LocalStructuredModel, ModelUnavailable
from skriller.jobs.budget import current_usage
from skriller.jobs.outbox import submit
from skriller.research.planner import (
    Interpretation,
    PlanningInvalid,
    PlanScope,
    PromptPlanner,
    grounded_plan,
    persist_revision,
)

pytestmark = pytest.mark.integration_db


def setup(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Planner")["id"]
    limits = Limits(
        result_limit=10,
        search_calls=2,
        candidates=20,
        fetch_attempts=10,
        llm_calls=2,
        token_cap=8192,
        deadline_seconds=90,
    )
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Prompt")
        initial = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="person",
            limits=limits,
        )
        parent = ConversationRepository.revise_plan(
            session, conversation["id"], initial.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], parent["id"], str(uuid4()))
    context = ExecutionContext(
        workspace_id=workspace,
        job_id=job["id"],
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        attempt_budget=1,
    )
    scope = PlanScope(
        workspace_id=workspace,
        conversation_id=conversation["id"],
        revision=2,
        limits=limits,
        allowed_sources=["linkedin", "reddit", "web"],
    )
    return context, scope, parent["id"]


class Fixture:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        assert "No inferred preferences" in messages[1].content
        assert config == {"callbacks": []}
        return AIMessage(
            content=json.dumps(self.answer),
            usage_metadata={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
        )


async def test_founder_geography_exclusion_preference_server_caps_and_immutable_revision(database):
    context, scope, parent = setup(database)
    prompt = "Find fintech founders in Bengaluru on LinkedIn. Exclude agencies. Prefer companies hiring engineers."
    fixture = Fixture(
        {
            "entity_type": "person",
            "entity_quote": "founders",
            "rules": [
                ["must_have", "role", "contains", "founder", "founders"],
                ["must_have", "industry", "contains", "fintech", "fintech founders"],
                ["must_have", "person_location", "eq", "Bengaluru", "founders in Bengaluru"],
                ["exclude", "company_type", "contains", "agencies", "Exclude agencies"],
                [
                    "preference",
                    "hiring_role",
                    "contains",
                    "engineers",
                    "Prefer companies hiring engineers",
                ],
            ],
            "sources": [["linkedin", "LinkedIn"]],
        }
    )
    plan = await PromptPlanner(LocalStructuredModel(model_instance=fixture)).interpret(
        database, context, prompt, scope, operation_key="founder-plan"
    )
    assert plan.workspace_id == context.workspace_id and plan.revision == 2
    assert plan.sources == ["linkedin"]
    assert plan.limits == scope.limits
    assert [(rule.field, rule.value) for rule in plan.preferences] == [("hiring_role", "engineers")]
    assert plan.must_have[-1].field == "person_location" and plan.must_have[-1].value == "Bengaluru"
    assert plan.exclusions[0].value == "agencies"
    row = persist_revision(database, context, plan, parent_id=parent)
    assert row["revision"] == 2 and row["parent_id"] == parent
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        old = ConversationRepository.get_plan(session, parent)
        assert old["revision"] == 1
        assert current_usage(session, str(context.job_id))[1]["tokens"] == 300
    with pytest.raises(ValueError, match="latest immutable"):
        persist_revision(database, context, plan, parent_id=parent)
    assert fixture.calls == 1


async def test_ambiguous_geography_requests_clarification(database):
    context, scope, _ = setup(database)
    prompt = "Find founders at companies in London."
    fixture = Fixture(
        {
            "entity_type": "person",
            "entity_quote": "founders",
            "rules": [["must_have", "location", "eq", "London", "companies in London"]],
        }
    )
    plan = await PromptPlanner(LocalStructuredModel(model_instance=fixture)).interpret(
        database, context, prompt, scope, operation_key="ambiguous"
    )
    assert "person" in plan.clarification and "headquarters" in plan.clarification
    assert not plan.must_have


async def test_private_field_is_explicitly_unsupported_not_invented_contact(database):
    context, scope, _ = setup(database)
    prompt = "Find founders and their private email."
    fixture = Fixture(
        {
            "entity_type": "person",
            "entity_quote": "founders",
            "fields": [["private_email", "private email"]],
        }
    )
    plan = await PromptPlanner(LocalStructuredModel(model_instance=fixture)).interpret(
        database, context, prompt, scope, operation_key="private"
    )
    assert plan.unsupported_criteria == ["private email"]
    assert "private_email" not in plan.requested_fields


@pytest.mark.parametrize(
    "injection",
    [
        {"limits": {"currency_cap": 100}},
        {"workspace_id": str(uuid4())},
        {"provider": "cloud"},
        {"code": "eval(prompt)"},
    ],
)
async def test_model_cannot_set_ids_budget_provider_or_code(database, injection):
    context, scope, _ = setup(database)
    fixture = Fixture({"entity_type": "person", "entity_quote": "founders", **injection})
    with pytest.raises(ModelUnavailable) as caught:
        await PromptPlanner(LocalStructuredModel(model_instance=fixture)).interpret(
            database, context, "Find founders", scope, operation_key="injection"
        )
    assert caught.value.failure.code == "schema_invalid"
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["tokens"] == 300


def test_ungrounded_criteria_and_invented_preferences_are_rejected():
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    for rule in [
        ["must_have", "industry", "contains", "healthcare", "fintech founders"],
        ["preference", "industry", "contains", "fintech", "fintech founders"],
    ]:
        with pytest.raises(PlanningInvalid):
            grounded_plan(
                "Find fintech founders",
                Interpretation(entity_type="person", entity_quote="founders", rules=[rule]),
                scope,
            )


def test_source_and_requested_field_grounding_keep_unsupported_intent_visible():
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    plan = grounded_plan(
        "Find founders on LinkedIn; include names and URLs.",
        Interpretation(
            entity_type="person",
            entity_quote="founders",
            sources=[("linkedin", "LinkedIn")],
            fields=[("name", "names"), ("source_url", "URLs")],
        ),
        scope,
    )
    assert plan.unsupported_criteria == ["LinkedIn"]
    assert plan.requested_fields == ["name", "source_url"]
    with pytest.raises(PlanningInvalid):
        grounded_plan(
            "Find founders",
            Interpretation(
                entity_type="person",
                entity_quote="founders",
                fields=[("public_contact", "founders")],
            ),
            scope,
        )


def test_persistence_rejects_mismatched_identity_and_revision(database):
    context, scope, parent = setup(database)
    plan = grounded_plan(
        "Find founders", Interpretation(entity_type="person", entity_quote="founders"), scope
    )
    for wrong in [
        plan.model_copy(update={"workspace_id": uuid4()}),
        plan.model_copy(update={"revision": 3}),
        plan.model_copy(update={"conversation_id": uuid4()}),
    ]:
        with pytest.raises(PlanningInvalid):
            persist_revision(database, context, wrong, parent_id=parent)
