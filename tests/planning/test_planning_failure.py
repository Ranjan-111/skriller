"""Public planning failures contain fixed recovery choices, never model content."""

import pytest

from skriller.research.planning_failure import planning_failure


@pytest.mark.parametrize(
    "code,reason,recovery",
    [
        ("schema_invalid", "invalid_interpretation", "revise_prompt"),
        ("ungrounded_quote", "invalid_interpretation", "revise_prompt"),
        ("ungrounded_value", "invalid_interpretation", "revise_prompt"),
        ("source_unavailable", "model_unavailable", "check_service"),
        ("rate_limited", "model_unavailable", "check_service"),
        ("budget_exhausted", "budget_exhausted", "check_limits"),
        ("deadline_exceeded", "execution_interrupted", "review_run"),
        ("provider exception containing a secret", "execution_interrupted", "review_run"),
        (None, "execution_interrupted", "review_run"),
    ],
)
def test_planning_recovery_is_fixed_and_never_auto_retries(code, reason, recovery):
    result = planning_failure(code).model_dump()
    assert result == {
        "reason": reason,
        "recovery": recovery,
        "automatic_retry_allowed": False,
        "source_search_started": False,
    }
