import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage

from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.db.schema import jobs, messages
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


def test_cancelled_planning_job_cannot_publish_a_late_successor(database):
    from skriller.jobs.control import cancel

    context, scope, parent = setup(database)
    plan = grounded_plan(
        "Find founders", Interpretation(entity_type="person", entity_quote="founders"), scope
    )
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        cancel(session, str(context.job_id))
    with pytest.raises(PlanningInvalid, match="no longer permits"):
        persist_revision(database, context, plan, parent_id=parent)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert ConversationRepository.get_plan(session, parent)["revision"] == 1


def test_clarification_reply_keeps_context_and_queues_bounded_new_revision(database, monkeypatch):
    from fastapi.testclient import TestClient

    from skriller.api import create_app
    from skriller.auth import Identity, require_identity
    from skriller.db import JobRepository
    from skriller.jobs.worker import CheckpointWorker
    from skriller.research.bootstrap import execute_planning
    from skriller.settings import Settings

    context, scope, parent_id = setup(database)
    prompt = "Find founders at companies in London."
    actor, workspace = context.actor_id, str(context.workspace_id)
    with database.tenant(actor, workspace) as session:
        original = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, parent_id)["interpretation"]
        )
        seed_limits = original.limits.model_copy(
            update={
                "llm_calls": 1,
                "token_cap": 4096,
                "fetch_attempts": 0,
            }
        )
        ConversationRepository.add_message(session, str(scope.conversation_id), "user", prompt)
        paused_plan = original.model_copy(
            update={
                "revision": 2,
                "limits": seed_limits,
                "clarification": "Should location refer to the person or company headquarters?",
            }
        )
        parent = ConversationRepository.revise_plan(
            session,
            str(scope.conversation_id),
            paused_plan.model_dump(mode="json"),
            parent_id=parent_id,
        )
        session.execute(
            sa.update(jobs)
            .where(jobs.c.id == str(context.job_id))
            .values(
                plan_id=parent["id"],
                purpose="planning",
                state="paused",
                stage="planning",
                failure_code="clarification_required",
            )
        )
    planning_settings = Settings(
        enable_ai_planning=True,
        enable_page_extraction=True,
        public_collection_proxy_url="http://127.0.0.1:8787",
    )
    app = create_app(planning_settings)
    app.state.database = database
    app.dependency_overrides[require_identity] = lambda: Identity(actor)
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = TestClient(app)
    endpoint = f"/v1/jobs/{context.job_id}/clarifications?workspace_id={workspace}"
    submitted = client.post(
        endpoint, json={"answer": "Company headquarters"}, headers={"Idempotency-Key": "clarify-1"}
    )
    assert submitted.status_code == 202, submitted.text
    new_job_id = submitted.json()["job_id"]
    repeated = client.post(
        endpoint, json={"answer": "Company headquarters"}, headers={"Idempotency-Key": "clarify-1"}
    )
    assert repeated.status_code == 202 and repeated.json()["job_id"] == new_job_id
    with database.tenant(actor, workspace) as session:
        old = JobRepository.get(session, str(context.job_id))
        new = JobRepository.get(session, new_job_id)
        assert old["state"] == "paused" and old["plan_id"] == parent["id"]
        assert new["purpose"] == "planning" and new["state"] == "queued"
        assert ConversationRepository.get_plan(session, parent_id)["revision"] == 1
        saved_messages = (
            session.execute(
                sa.select(messages.c.content)
                .where(
                    messages.c.conversation_id == str(scope.conversation_id),
                    messages.c.role == "user",
                )
                .order_by(messages.c.sequence)
            )
            .scalars()
            .all()
        )
        assert saved_messages == [prompt, "Company headquarters"]
    payload = {"actor_id": actor, "workspace_id": workspace, "job_id": new_job_id}
    scheduled = CheckpointWorker(database, {}).schedule(payload)
    assert scheduled["status"] == "scheduled"
    payload["attempt_id"] = scheduled["attempt_id"]

    class Answer:
        calls = 0

        async def ainvoke(self, model_messages, config):
            self.calls += 1
            assert "Find founders at companies in London." in model_messages[1].content
            assert "Company headquarters" in model_messages[1].content
            return AIMessage(
                content=json.dumps(
                    {
                        "entity_type": "person",
                        "entity_quote": "founders",
                        "rules": [
                            ["must_have", "company_location", "eq", "London", "companies in London"]
                        ],
                    }
                ),
                usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )

    model = Answer()
    outcome = execute_planning(
        database,
        payload,
        planning_settings,
        LocalStructuredModel(model_instance=model),
    )
    assert outcome["status"] == "checkpointed" and outcome["planning_status"] == "ready"
    assert model.calls == 1
    with database.tenant(actor, workspace) as session:
        updated = JobRepository.get(session, new_job_id)
        latest = SearchPlan.model_validate(
            ConversationRepository.get_plan(session, updated["plan_id"])["interpretation"]
        )
        assert updated["purpose"] == "research" and latest.clarification is None
        assert latest.must_have[0].field == "company_location"
        assert latest.limits.llm_calls == 10
        assert latest.limits.token_cap == 40960
        assert latest.limits.fetch_attempts == 30


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


@pytest.mark.skipif(
    os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") != "1",
    reason="Set SKRILLER_RUN_LOCAL_MODEL_TESTS=1 to call the configured local Ollama model",
)
async def test_local_model_clarifies_ambiguous_geography(database):
    context, scope, _parent = setup(database)
    async with PromptPlanner(LocalStructuredModel()) as planner:
        plan = await planner.interpret(
            database,
            context,
            "Find founders at companies in London.",
            scope,
            operation_key="local-model-ambiguous-geography",
        )

    assert plan.clarification
    assert "person" in plan.clarification.lower()
    assert "company" in plan.clarification.lower()
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


@pytest.mark.parametrize(
    "field,operator,value,quote",
    [
        ("employee_count", "gte", "25", "250 employees"),
        ("employee_count", "gte", "25", "-25 employees"),
        ("employee_count", "gte", "25", "25.5 employees"),
        ("industry", "contains", "AI", "paid software"),
    ],
)
def test_substring_and_numeric_fragment_cannot_change_user_intent(field, operator, value, quote):
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    with pytest.raises(PlanningInvalid) as caught:
        grounded_plan(
            "Find companies with " + quote,
            Interpretation(
                entity_type="company",
                entity_quote="companies",
                rules=[("must_have", field, operator, value, quote)],
            ),
            scope,
        )
    assert caught.value.reason == "ungrounded_value"


def test_platform_name_must_be_a_whole_explicit_source_word():
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["x", "web"],
    )
    with pytest.raises(PlanningInvalid):
        grounded_plan(
            "Find founders; exclude agencies",
            Interpretation(
                entity_type="person", entity_quote="founders", sources=[("x", "exclude")]
            ),
            scope,
        )


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Find companies. Exclude agencies.", "exclusion"),
        ("Find companies. Prefer hiring engineers.", "preference"),
        ("Find companies headquartered in Paris.", "company headquarters"),
        ("Find founders based in Bengaluru.", "person location"),
        ("Find companies with at least 25 employees.", "minimum employee count"),
    ],
)
def test_omitted_material_constraint_pauses_instead_of_searching(prompt, expected):
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    target = "founders" if "founders" in prompt else "companies"
    plan = grounded_plan(
        prompt,
        Interpretation(
            entity_type="person" if target == "founders" else "company", entity_quote=target
        ),
        scope,
    )
    assert expected in plan.clarification
    assert not plan.must_have and not plan.exclusions and not plan.preferences


def test_omitted_private_field_is_still_reported_unsupported():
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    plan = grounded_plan(
        "Find founders and their Private Email.",
        Interpretation(entity_type="person", entity_quote="founders"),
        scope,
    )
    assert plan.unsupported_criteria == ["Private Email"]
    assert plan.requested_fields == ["name", "source_url"]


@pytest.mark.parametrize("source", ["LinkedIn", "Reddit", "GitHub", "YouTube", "X", "web"])
def test_omitted_explicit_source_pauses_instead_of_expanding_search(source):
    scope = PlanScope(
        workspace_id=uuid4(), conversation_id=uuid4(), revision=1,
        limits=Limits(), allowed_sources=["linkedin", "reddit", "web"],
    )
    plan = grounded_plan(
        f"Find founders on {source}.",
        Interpretation(entity_type="person", entity_quote="founders"), scope,
    )
    assert "source selection" in plan.clarification


@pytest.mark.parametrize(
    "operator,phrase,accepted",
    [
        ("gte", "at least 25 employees", True),
        ("lte", "at most 25 employees", True),
        ("gte", "at most 25 employees", False),
        ("lte", "at least 25 employees", False),
        ("gte", "25 employees", False),
    ],
)
def test_numeric_filter_preserves_explicit_comparison(operator, phrase, accepted):
    scope = PlanScope(
        workspace_id=uuid4(), conversation_id=uuid4(), revision=1,
        limits=Limits(), allowed_sources=["web"],
    )
    interpretation = Interpretation(
        entity_type="company", entity_quote="companies",
        rules=[("must_have", "employee_count", operator, "25", phrase)],
    )
    if accepted:
        plan = grounded_plan(f"Find companies with {phrase}.", interpretation, scope)
        assert plan.must_have[0].operator == operator
    else:
        with pytest.raises(PlanningInvalid, match="comparison"):
            grounded_plan(f"Find companies with {phrase}.", interpretation, scope)


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


async def test_prompt_guides_exact_quote_case_and_intent_cue_spans_without_weakening_guards(
    database,
):
    context, scope, _ = setup(database)
    prompt = "Find founders. Exclude agencies. Prefer companies hiring engineers."

    class GuidanceFixture(Fixture):
        async def ainvoke(self, messages, config):
            assert "Every quote must be a nonempty verbatim substring" in messages[1].content
            assert "Preference/exclusion quotes include their intent word" in messages[1].content
            return await super().ainvoke(messages, config)

    fixture = GuidanceFixture(
        {
            "entity_type": "person",
            "entity_quote": "founders",
            "rules": [
                ["exclude", "company_type", "contains", "agencies", "Exclude agencies"],
                [
                    "preference",
                    "hiring_role",
                    "contains",
                    "engineers",
                    "Prefer companies hiring engineers",
                ],
            ],
        }
    )
    plan = await PromptPlanner(LocalStructuredModel(model_instance=fixture)).interpret(
        database, context, prompt, scope, operation_key="cue-guidance"
    )
    assert plan.preferences[0].value == "engineers" and plan.exclusions[0].value == "agencies"
    for rule, reason in [
        (
            ["preference", "hiring_role", "contains", "engineers", "companies hiring engineers"],
            "preference_missing_cue",
        ),
        (["exclude", "company_type", "contains", "agencies", "agencies"], "exclusion_missing_cue"),
    ]:
        with pytest.raises(PlanningInvalid) as caught:
            grounded_plan(
                prompt,
                Interpretation(entity_type="person", entity_quote="founders", rules=[rule]),
                scope,
            )
        assert caught.value.reason == reason


def test_safe_grounding_diagnostics_do_not_echo_user_or_model_text():
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    with pytest.raises(PlanningInvalid) as caught:
        grounded_plan(
            "Find founders",
            Interpretation(entity_type="person", entity_quote="PRIVATE_FAKE_QUOTE"),
            scope,
        )
    assert caught.value.reason == "ungrounded_quote"
    assert "PRIVATE_FAKE_QUOTE" not in str(caught.value)


async def test_planner_configured_provider_lifecycle_and_injected_ownership(monkeypatch):
    from skriller.research import planner
    from skriller.settings import Settings

    class Provider:
        source = "groq"
        closed = False

        async def aclose(self):
            self.closed = True

    owned = Provider()
    settings = Settings(_env_file=None, model_provider="groq")

    def factory(selected):
        assert selected is settings
        return owned

    monkeypatch.setattr(planner, "structured_model", factory)
    async with planner.PromptPlanner(settings=settings) as configured:
        assert configured.model is owned and not owned.closed
    assert owned.closed
    injected = Provider()
    async with planner.PromptPlanner(injected):
        pass
    assert not injected.closed
