"""Fixed public outcomes for rejected planning; never expose provider text."""

from typing import Literal

from skriller.contracts import Contract


class PlanningFailureView(Contract):
    reason: Literal[
        "invalid_interpretation", "model_unavailable", "budget_exhausted", "execution_interrupted"
    ]
    recovery: Literal["revise_prompt", "check_service", "check_limits", "review_run"]
    automatic_retry_allowed: Literal[False] = False
    source_search_started: Literal[False] = False


def planning_failure(code: str | None) -> PlanningFailureView:
    if code in {
        "schema_invalid",
        "interpretation_rejected",
        "ungrounded_quote",
        "unsupported_criterion",
        "ungrounded_value",
        "preference_missing_cue",
        "exclusion_missing_cue",
    }:
        return PlanningFailureView(reason="invalid_interpretation", recovery="revise_prompt")
    if code in {"source_unavailable", "rate_limited"}:
        return PlanningFailureView(reason="model_unavailable", recovery="check_service")
    if code == "budget_exhausted":
        return PlanningFailureView(reason="budget_exhausted", recovery="check_limits")
    return PlanningFailureView(reason="execution_interrupted", recovery="review_run")
