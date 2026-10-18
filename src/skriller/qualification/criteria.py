"""Deterministic evidence outcomes, with preference scores kept separate from fit.

This product logic has no equivalent in the supplied scraping engines. Callers
must supply tenant-scoped, identity-resolved facts from strict claim validation;
this module neither promotes search snippets nor makes model/network calls.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from skriller.contracts import Criterion, SearchPlan

Outcome = Literal["matched", "contradicted", "unknown"]
Scalar = str | int | float | bool


@dataclass(frozen=True)
class Fact:
    field: str
    value: Scalar
    evidence_ids: tuple[str, ...]
    observed_at: datetime
    event_at: datetime | None = None
    status: Literal["accepted", "unverified", "contradicted"] = "unverified"
    expires_at: datetime | None = None

    def __post_init__(self):
        if not self.field or len(self.field) > 80 or len(self.evidence_ids) > 10:
            raise ValueError("Bounded field and evidence required")
        if any(not value or len(value) > 128 for value in self.evidence_ids):
            raise ValueError("Bounded evidence identifiers required")
        if type(self.value) not in {str, int, float, bool}:
            raise ValueError("Only scalar facts are supported")
        if isinstance(self.value, str) and len(self.value) > 4096:
            raise ValueError("Fact value exceeds bounds")
        if isinstance(self.value, float):
            from math import isfinite

            if not isfinite(self.value):
                raise ValueError("Finite fact required")
        if self.status not in {"accepted", "unverified", "contradicted"}:
            raise ValueError("Typed fact status required")
        for date in (self.observed_at, self.event_at, self.expires_at):
            if date is not None and (date.tzinfo is None or date.utcoffset() is None):
                raise ValueError("Timezone-aware fact dates required")


@dataclass(frozen=True)
class CriterionResult:
    criterion: Criterion
    outcome: Outcome
    reason: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fit:
    status: Literal["confirmed", "near_match", "excluded"]
    essential: tuple[CriterionResult, ...]
    exclusions: tuple[CriterionResult, ...]
    preferences: tuple[CriterionResult, ...]
    preference_score: int
    limitations: tuple[str, ...]


def _equal(actual: Scalar, requested: object) -> bool | None:
    if isinstance(actual, bool) or isinstance(requested, bool):
        return actual == requested if type(actual) is type(requested) else None
    if isinstance(actual, (int, float)) and isinstance(requested, (int, float)):
        return actual == requested
    if isinstance(actual, str) and isinstance(requested, str):
        return actual.strip().casefold() == requested.strip().casefold()
    return None


def _compare(criterion: Criterion, fact: Fact, now: datetime) -> bool | None:
    value = fact.value
    if criterion.operator == "recent":
        # A fetch time is not the date of hiring, a post, or a role change.
        if fact.event_at is None or fact.event_at > now:
            return None
        return (now - fact.event_at).total_seconds() / 86400 <= cast(int | float, criterion.value)
    if criterion.operator == "eq":
        return _equal(value, criterion.value)
    if criterion.operator == "contains":
        return (
            str(criterion.value).casefold() in value.casefold() if isinstance(value, str) else None
        )
    if criterion.operator == "in":
        outcomes = [_equal(value, item) for item in cast(list[str], criterion.value)]
        return True if True in outcomes else False if all(v is False for v in outcomes) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    bound = cast(int | float, criterion.value)
    return value >= bound if criterion.operator == "gte" else value <= bound


def evaluate(
    criterion: Criterion,
    facts: tuple[Fact, ...],
    *,
    now: datetime,
    freshness_days: int | None = None,
) -> CriterionResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware evaluation clock required")
    eligible = [
        fact
        for fact in facts
        if (
            fact.field == criterion.field
            or criterion.field == "role"
            and fact.field in {"job_title", "current_role"}
        )
        and fact.status == "accepted"
        and fact.evidence_ids
        and fact.observed_at <= now
        and (fact.expires_at is None or fact.expires_at > now)
        and (freshness_days is None or now - fact.observed_at <= timedelta(days=freshness_days))
    ]
    if not eligible:
        return CriterionResult(criterion, "unknown", "accepted_current_evidence_missing")
    values = [_compare(criterion, fact, now) for fact in eligible]
    if None in values:
        return CriterionResult(criterion, "unknown", "type_or_event_date_unverified")
    if len(set(values)) > 1:
        return CriterionResult(criterion, "unknown", "conflicting_evidence")
    evidence = tuple(
        dict.fromkeys(identifier for fact in eligible for identifier in fact.evidence_ids)
    )
    if len(evidence) > 10:
        return CriterionResult(criterion, "unknown", "evidence_reference_budget_exhausted")
    return CriterionResult(
        criterion,
        "matched" if values[0] else "contradicted",
        "accepted_evidence_comparison",
        evidence,
    )


def qualify(plan: SearchPlan, facts: tuple[Fact, ...], *, now: datetime) -> Fit:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware evaluation clock required")
    if len(facts) > 300:
        raise ValueError("Fact collection exceeds pilot bounds")

    def group(criteria):
        return tuple(
            evaluate(item, facts, now=now, freshness_days=plan.freshness_days) for item in criteria
        )

    essential, exclusions, preferences = (
        group(plan.must_have),
        group(plan.exclusions),
        group(plan.preferences),
    )
    limitations = tuple(plan.unsupported_criteria) + (
        ("clarification_required",) if plan.clarification else ()
    )
    status: Literal["confirmed", "near_match", "excluded"] = (
        "excluded"
        if any(item.outcome == "matched" for item in exclusions)
        else "near_match"
        if limitations
        or not essential
        or any(item.outcome != "matched" for item in essential)
        or any(item.outcome != "contradicted" for item in exclusions)
        else "confirmed"
    )
    return Fit(
        status,
        essential,
        exclusions,
        preferences,
        sum(item.outcome == "matched" for item in preferences),
        limitations,
    )


def rank(fits: tuple[tuple[str, Fit], ...]) -> tuple[tuple[str, Fit], ...]:
    order = {"confirmed": 0, "near_match": 1, "excluded": 2}
    # Stable identifier tie-break; preference counts are not confidence scores.
    return tuple(
        sorted(fits, key=lambda item: (order[item[1].status], -item[1].preference_score, item[0]))
    )
