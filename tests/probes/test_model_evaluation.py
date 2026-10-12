import pytest
from pydantic import ValidationError

from scripts.probes.model_trial import score_facts


def test_schema_valid_invented_contact_is_factual_failure():
    expected = {"company": "Aurora Ledger", "founder": "Mira Rao", "private_email": None}
    result = score_facts({**expected, "private_email": "invented@aurora.example"}, expected)
    assert result["status"] == "quality_failed"
    assert result["checks"]["company"] is True
    assert result["checks"]["private_email"] is False
    assert score_facts(expected, expected)["status"] == "passed"


def test_schema_failure_and_unknown_employee_are_not_successful_facts():
    with pytest.raises(ValidationError):
        score_facts({"company": "Aurora"}, {"company": "Aurora"})
    expected = {"company": "Cedar", "founder": "Dev", "employees": None}
    assert score_facts({**expected, "employees": 0}, expected)["status"] == "quality_failed"
