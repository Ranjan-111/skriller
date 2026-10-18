"""Opt-in semantic acceptance of the production local planner, using synthetic intent."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
        {("role", "contains", "founder"), ("person_location", "eq", "Bengaluru")},
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


@pytest.fixture(scope="module")
def planning_report(tmp_path_factory):
    root = Path(__file__).parents[2]
    implementation_hashes = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ["src/skriller/research/planner.py", "src/skriller/extraction/models.py"]
    }
    corpus_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    rows = {
        key: {"id": key, "outcome": "not_executed", "calls": 0}
        for key in [*(row[0] for row in CASES), "private-output", "ambiguous-location"]
    }
    yield rows
    report = {
        "schema_version": 1,
        "dimension": "prompt_planning",
        "source_group": "synthetic_fixture",
        "model_mode": "actual_local_ollama",
        "model": os.environ.get("SKRILLER_LOCAL_BENCH_MODEL", "llama3.2:3b"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "case_denominator": len(rows),
        "case_assertions_passed": sum(row["outcome"] == "passed" for row in rows.values()),
        "actual_model_calls": sum(row["calls"] for row in rows.values()),
        "source_calls": 0,
        "release_gate_passed": False,
        "release_prompt_target": 50,
        "scope": "Five synthetic development checks using the declared per-case assertions, not a full-plan recall metric. Incomplete and failed cases remain in the denominator. No source, extraction, identity or pilot-quality claim.",
        "corpus_and_labels_sha256": corpus_hash,
        "implementation_sha256": implementation_hashes,
        "cases": list(rows.values()),
    }
    output = tmp_path_factory.mktemp("planner-quality") / "report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    if os.environ.get("SKRILLER_WRITE_QUALITY_REPORTS") == "1":
        (root / "docs/completions/PLANNER-QUALITY-LOCAL.json").write_text(output.read_text())


class DiagnosticModel(LocalStructuredModel):
    """Capture synthetic benchmark responses after the unchanged ledger boundary."""

    def __init__(self, bounds, row):
        super().__init__(bounds)
        self.row = row

    def invocation_model(self, schema):
        delegate = super().invocation_model(schema)
        row = self.row

        class Capture:
            async def ainvoke(self, messages, config):
                row["calls"] += 1
                message = await delegate.ainvoke(messages, config=config)
                text = message.content
                row["synthetic_response"] = text[:16384] if isinstance(text, str) else None
                row["response_truncated"] = isinstance(text, str) and len(text) > 16384
                row["usage_metadata"] = message.usage_metadata
                return message

        return Capture()


async def interpret(database, prompt, key, planning_report):
    context, scope, _ = setup(database)
    context = context.model_copy(update={"deadline": datetime.now(UTC) + timedelta(seconds=90)})
    bounds = ModelBounds(model=os.environ.get("SKRILLER_LOCAL_BENCH_MODEL", "llama3.2:3b"))
    row = planning_report[key]
    row["outcome"] = "failed"
    try:
        async with PromptPlanner(DiagnosticModel(bounds, row)) as planner:
            plan = await planner.interpret(database, context, prompt, scope, operation_key=key)
    except Exception as failure:
        row["failure_class"] = type(failure).__name__
        row["failure_code"] = (
            failure.reason
            if hasattr(failure, "reason")
            else failure.failure.code
            if hasattr(failure, "failure")
            else "unavailable"
        )
        raise
    row["observed_plan"] = {
        key: value
        for key, value in plan.model_dump(mode="json").items()
        if key not in {"workspace_id", "conversation_id"}
    }
    assert plan.workspace_id == context.workspace_id
    assert plan.limits == scope.limits
    return plan


@pytest.mark.parametrize("key,prompt,entity,must,excluded,preferred,sources", CASES)
async def test_local_planner_preserves_labeled_intent(
    database, key, prompt, entity, must, excluded, preferred, sources, planning_report
):
    plan = await interpret(database, prompt, key, planning_report)
    checks = {
        "entity_type": plan.entity_type == entity,
        "clarification": not plan.clarification,
        "must_have": triples(plan.must_have) == must,
        "exclusions": triples(plan.exclusions) == excluded,
        "preferences": triples(plan.preferences) == preferred,
        "sources": plan.sources == sources,
        "unsupported_criteria": not plan.unsupported_criteria,
    }
    planning_report[key]["checks"] = checks
    planning_report[key]["outcome"] = "passed" if all(checks.values()) else "failed"
    assert plan.entity_type == entity
    assert not plan.clarification
    assert triples(plan.must_have) == must
    assert triples(plan.exclusions) == excluded
    assert triples(plan.preferences) == preferred
    assert plan.sources == sources
    assert not plan.unsupported_criteria


async def test_local_planner_rejects_private_output(database, planning_report):
    plan = await interpret(
        database, "Find founders and their private email.", "private-output", planning_report
    )
    assert plan.entity_type == "person"
    assert plan.unsupported_criteria == ["private email"]
    assert "private_email" not in plan.requested_fields
    assert not plan.preferences and not plan.exclusions
    planning_report["private-output"]["outcome"] = "passed"


async def test_local_planner_pauses_ambiguous_geography(database, planning_report):
    plan = await interpret(
        database, "Find founders at companies in London.", "ambiguous-location", planning_report
    )
    assert plan.clarification
    assert "person" in plan.clarification.lower() and "company" in plan.clarification.lower()
    assert not any(rule.field.endswith("location") for rule in plan.must_have)
    planning_report["ambiguous-location"]["outcome"] = "passed"
