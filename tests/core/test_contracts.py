from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from skriller.contracts import Criterion, ExecutionContext, Limits, SearchPlan


def plan(**changes):
    return SearchPlan(
        workspace_id=uuid4(), conversation_id=uuid4(), revision=1, entity_type="person", **changes
    )


def test_criteria_and_json_round_trip_preserve_intent():
    initial = plan(
        must_have=[Criterion(field="location", operator="eq", value="Bengaluru")],
        exclusions=[Criterion(field="industry", operator="eq", value="agency")],
    )
    restored = SearchPlan.model_validate_json(initial.model_dump_json())
    assert restored == initial
    assert restored.exclusions[0].value == "agency"
    assert restored.limits.currency_cap == 0


@pytest.mark.parametrize(
    "limits",
    [{"result_limit": 0}, {"search_calls": 21}, {"currency_cap": "NaN"}, {"deadline_seconds": 0}],
)
def test_invalid_or_unbounded_limits_cannot_dispatch(limits):
    with pytest.raises(ValidationError):
        Limits(**limits)


def test_arbitrary_code_and_nested_schema_are_not_plans():
    with pytest.raises(ValidationError):
        plan(requested_fields=["__import__('os')"])
    with pytest.raises(ValidationError):
        Criterion(field="name", operator="eq", value={"script": "execute"})
    with pytest.raises(ValidationError):
        plan(sources=["linkedin", "linkedin"])


def test_execution_context_never_accepts_raw_secrets_or_naive_deadline():
    values = {
        "workspace_id": uuid4(),
        "job_id": uuid4(),
        "actor_id": "user",
        "plan_revision": 1,
        "deadline": datetime(2026, 10, 12),
        "attempt_budget": 2,
    }
    with pytest.raises(ValidationError):
        ExecutionContext(**values)
    values["deadline"] = "2026-10-12T12:00:00Z"
    with pytest.raises(ValidationError):
        ExecutionContext(**values, cookie="sensitive-value")


@pytest.mark.parametrize(
    "operator,value",
    [
        ("gte", True),
        ("lte", "20"),
        ("in", "fintech"),
        ("contains", 1),
        ("recent", -1),
        ("eq", ["a"]),
    ],
)
def test_operator_and_value_types_must_agree(operator, value):
    with pytest.raises(ValidationError):
        Criterion(field="employees", operator=operator, value=value)
