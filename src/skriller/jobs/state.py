"""Lifecycle semantics reuse persistence's transition map and atomic mutations."""

from typing import Literal

from sqlalchemy.orm import Session

from skriller.db.repositories import JOB_TRANSITIONS, JobRepository

STAGES = {"discovering", "collecting", "extracting", "resolving", "qualifying"}
TERMINAL_STATES = {"completed", "partial", "failed", "cancelled"}
REASONS = {
    "completed": {"source_exhausted", "target_met"},
    "partial": {"budget_limit", "deadline_limit", "source_interrupted"},
    "failed": {"budget_limit", "deadline_limit", "source_interrupted", "processing_error"},
    "cancelled": {"user_cancelled"},
}
DEFAULT_REASONS = {
    "completed": "source_exhausted",
    "partial": "source_interrupted",
    "failed": "processing_error",
    "cancelled": "user_cancelled",
}


def validate_transition(current: str, target: str, stage: str | None, reason: str | None):
    if current not in JOB_TRANSITIONS or target not in JOB_TRANSITIONS:
        raise ValueError("Unknown job state")
    if stage is not None and stage not in STAGES:
        raise ValueError("Unknown execution stage")
    if target != current and target not in JOB_TRANSITIONS[current]:
        raise ValueError("Invalid job state transition")
    if target in TERMINAL_STATES:
        reason = reason or DEFAULT_REASONS[target]
        if reason not in REASONS[target]:
            raise ValueError("Terminal reason does not match outcome")
    elif reason is not None:
        raise ValueError("Nonterminal jobs cannot have a terminal reason")
    return reason


def finish(
    session: Session,
    job_id: str,
    *,
    outcome: Literal[
        "source_exhausted",
        "target_met",
        "budget_limit",
        "deadline_limit",
        "source_interrupted",
        "processing_error",
        "user_cancelled",
    ],
    retained_results: int,
    expected_version: int,
):
    """Only an interrupted run with saved results receives a partial outcome.

    Caller checkpoints the results in this same transaction before calling finish.
    No entity/evidence/qualification writes are removed by terminalization.
    """
    if retained_results < 0:
        raise ValueError("Retained result count cannot be negative")
    if outcome in {"source_exhausted", "target_met"}:
        target = "completed"
    elif outcome == "user_cancelled":
        target = "cancelled"
    elif outcome == "processing_error":
        target = "failed"
    elif outcome in {"budget_limit", "deadline_limit", "source_interrupted"}:
        target = "partial" if retained_results else "failed"
    else:
        raise ValueError("Unknown finish outcome")
    return JobRepository.transition(
        session,
        job_id,
        target,
        terminal_reason=outcome,
        expected_version=expected_version,
    )
