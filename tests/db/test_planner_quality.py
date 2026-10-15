"""Opt-in semantic acceptance of the production local planner, using synthetic intent."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from test_planner import setup

from skriller.extraction.models import LocalStructuredModel, ModelBounds
from skriller.research.planner import PromptPlanner

pytestmark = [
    pytest.mark.integration_db,
    pytest.mark.skipif(
        os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") != "1",
        reason="Explicit opt-in required for bounded local Ollama semantic benchmark",
    ),
]

CASES = [
    (
        "location-exclusion-preference",
        "Find founders based in Bengaluru on LinkedIn. Exclude agencies. Prefer companies hiring engineers.",
        "person",
        {("role", "contains", "founders"), ("person_location", "eq", "Bengaluru")},
        {("company_type", "contains", "agencies")},
        {("hiring_role", "contains", "engineers")},
        ["linkedin"],
    ),
    (
        "company-geography-industry",
        "Find companies in the fintech industry headquartered in Paris.",
        "company",
        {("industry", "contains", "fintech"), ("company_location", "eq", "Paris")},
        set(),
        set(),
        ["linkedin", "reddit", "web"],
    ),
    (
        "numeric-minimum",
        "Find companies with at least 25 employees. Exclude agencies.",
        "company",
        {("employee_count", "gte", 25.0)},
        {("company_type", "contains", "agencies")},
        set(),
        ["linkedin", "reddit", "web"],
    ),
]


def triples(rules):
    return {(rule.field, rule.operator, rule.value) for rule in rules}


async def interpret(database, prompt, key):
    context, scope, _ = setup(database)
    context = context.model_copy(update={"deadline": datetime.now(UTC) + timedelta(seconds=90)})
    bounds = ModelBounds(model=os.environ.get("SKRILLER_LOCAL_BENCH_MODEL", "llama3.2:3b"))
    async with PromptPlanner(LocalStructuredModel(bounds)) as planner:
        plan = await planner.interpret(database, context, prompt, scope, operation_key=key)
    assert plan.workspace_id == context.workspace_id
    assert plan.limits == scope.limits
    return plan


@pytest.mark.parametrize("key,prompt,entity,must,excluded,preferred,sources", CASES)
async def test_local_planner_preserves_labeled_intent(
    database, key, prompt, entity, must, excluded, preferred, sources
):
    plan = await interpret(database, prompt, key)
    assert plan.entity_type == entity
    assert not plan.clarification
    assert triples(plan.must_have) == must
    assert triples(plan.exclusions) == excluded
    assert triples(plan.preferences) == preferred
    assert plan.sources == sources
    assert not plan.unsupported_criteria


async def test_local_planner_rejects_private_output(database):
    plan = await interpret(database, "Find founders and their private email.", "private-output")
    assert plan.entity_type == "person"
    assert plan.unsupported_criteria == ["private email"]
    assert "private_email" not in plan.requested_fields
    assert not plan.preferences and not plan.exclusions


async def test_local_planner_pauses_ambiguous_geography(database):
    plan = await interpret(database, "Find founders at companies in London.", "ambiguous-location")
    assert plan.clarification
    assert "person" in plan.clarification.lower() and "company" in plan.clarification.lower()
    assert not any(rule.field.endswith("location") for rule in plan.must_have)
