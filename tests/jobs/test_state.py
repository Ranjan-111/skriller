import pytest

from skriller.db.repositories import JOB_TRANSITIONS
from skriller.jobs import validate_transition


def test_terminal_states_have_no_restart_transition():
    for state in ("completed", "partial", "failed", "cancelled"):
        assert JOB_TRANSITIONS[state] == set()
        with pytest.raises(ValueError, match="Invalid"):
            validate_transition(state, "running", "discovering", None)


def test_states_stages_and_reasons_remain_separate():
    with pytest.raises(ValueError, match="state"):
        validate_transition("running", "collecting", None, None)
    with pytest.raises(ValueError, match="stage"):
        validate_transition("running", "running", "completed", None)
    with pytest.raises(ValueError, match="reason"):
        validate_transition("running", "completed", "qualifying", "budget_limit")
    with pytest.raises(ValueError, match="Nonterminal"):
        validate_transition("queued", "running", "discovering", "target_met")
    assert validate_transition("running", "completed", "qualifying", "source_exhausted") == (
        "source_exhausted"
    )
    assert validate_transition("running", "partial", "qualifying", "budget_limit") == "budget_limit"
