"""Comparison words must qualify the selected number, not another number in the quote."""

from uuid import uuid4

import pytest

from skriller.contracts import Limits
from skriller.research.planner import Interpretation, PlanningInvalid, PlanScope, grounded_plan


@pytest.mark.parametrize(
    "operator,value,quote,accepted",
    [
        ("gte", "25", "at least 25 and at most 100 employees", True),
        ("lte", "100", "at least 25 and at most 100 employees", True),
        ("gte", "100", "at least 25 and at most 100 employees", False),
        ("lte", "25", "at least 25 and at most 100 employees", False),
        ("gte", "25", "at least 250 employees, with 25 offices", False),
        ("recent", "30", "hiring within 30 days, 90 employees", True),
        ("recent", "90", "hiring within 30 days, 90 employees", False),
    ],
)
def test_number_is_bound_to_its_comparison(operator, value, quote, accepted):
    scope = PlanScope(
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        revision=1,
        limits=Limits(),
        allowed_sources=["web"],
    )
    interpretation = Interpretation(
        entity_type="company",
        entity_quote="companies",
        rules=[
            (
                "must_have",
                "hiring_role" if operator == "recent" else "employee_count",
                operator,
                value,
                quote,
            )
        ],
    )
    prompt = "Find companies with " + quote
    if accepted:
        plan = grounded_plan(prompt, interpretation, scope)
        assert plan.must_have[0].value == float(value)
    else:
        with pytest.raises(PlanningInvalid, match="comparison"):
            grounded_plan(prompt, interpretation, scope)
