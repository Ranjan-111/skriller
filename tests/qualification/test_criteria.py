from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from skriller.contracts import Criterion, SearchPlan
from skriller.qualification.criteria import Fact, evaluate, qualify, rank

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def fact(field, value, **options):
    return Fact(field, value, (str(uuid4()),), NOW, status="accepted", **options)


def plan(**options):
    return SearchPlan(
        workspace_id=uuid4(), conversation_id=uuid4(), revision=1, entity_type="company", **options
    )


def test_unknown_essential_is_near_match_even_with_preferences():
    candidate = qualify(
        plan(
            must_have=[
                Criterion(field="location", operator="eq", value="London"),
                Criterion(field="size", operator="gte", value=20),
            ],
            preferences=[Criterion(field="location", operator="eq", value="London")],
        ),
        (fact("location", "London"),),
        now=NOW,
    )
    assert candidate.status == "near_match"
    assert [item.outcome for item in candidate.essential] == ["matched", "unknown"]
    assert candidate.preference_score == 1


@pytest.mark.parametrize(
    "change",
    [
        {"status": "unverified"},
        {"status": "contradicted"},
        {"evidence_ids": ()},
        {"expires_at": NOW},
        {"observed_at": NOW + timedelta(seconds=1)},
    ],
)
def test_unaccepted_unavailable_facts_cannot_confirm(change):
    criterion = Criterion(field="location", operator="eq", value="London")
    result = evaluate(criterion, (replace(fact("location", "London"), **change),), now=NOW)
    assert result.outcome == "unknown"
    assert not result.evidence_ids


def test_recent_event_does_not_use_fetch_time_and_old_event_is_not_recent():
    criterion = Criterion(field="hiring", operator="recent", value=30)
    assert evaluate(criterion, (fact("hiring", "job post"),), now=NOW).outcome == "unknown"
    result = evaluate(
        criterion, (fact("hiring", "job post", event_at=NOW - timedelta(days=90)),), now=NOW
    )
    assert result.outcome == "contradicted"
    assert (
        evaluate(
            criterion, (fact("hiring", "job post", event_at=NOW + timedelta(days=1)),), now=NOW
        ).outcome
        == "unknown"
    )


def test_conflicting_and_stale_facts_are_unknown():
    criterion = Criterion(field="location", operator="eq", value="London")
    result = evaluate(criterion, (fact("location", "London"), fact("location", "Paris")), now=NOW)
    assert result.reason == "conflicting_evidence"
    old = replace(fact("location", "London"), observed_at=NOW - timedelta(days=31))
    assert evaluate(criterion, (old,), now=NOW, freshness_days=30).outcome == "unknown"


@pytest.mark.parametrize(
    "operator,requested,actual,outcome",
    [
        ("eq", 1, True, "unknown"),
        ("gte", 20, "25", "unknown"),
        ("gte", 20, 25, "matched"),
        ("lte", 20, 25, "contradicted"),
        ("eq", " London ", "LONDON", "matched"),
        ("in", ["London", "Paris"], "Paris", "matched"),
        ("contains", "software", "Software company", "matched"),
    ],
)
def test_comparisons_are_typed(operator, requested, actual, outcome):
    result = evaluate(
        Criterion(field="field", operator=operator, value=requested),
        (fact("field", actual),),
        now=NOW,
    )
    assert result.outcome == outcome


def test_exclusion_and_unsupported_criteria_prevent_confirmation():
    essential = [Criterion(field="location", operator="eq", value="London")]
    facts = (fact("location", "London"),)
    exclusion = Criterion(field="location", operator="eq", value="London")
    assert (
        qualify(plan(must_have=essential, exclusions=[exclusion]), facts, now=NOW).status
        == "excluded"
    )
    unknown_exclusion = Criterion(field="industry", operator="eq", value="Gambling")
    assert (
        qualify(plan(must_have=essential, exclusions=[unknown_exclusion]), facts, now=NOW).status
        == "near_match"
    )
    assert (
        qualify(
            plan(must_have=essential, unsupported_criteria=["private intent"]), facts, now=NOW
        ).status
        == "near_match"
    )
    assert qualify(plan(), facts, now=NOW).status == "near_match"


def test_fit_status_ranks_before_preferences_and_ties_are_stable():
    criterion = Criterion(field="location", operator="eq", value="London")
    confirmed = qualify(plan(must_have=[criterion]), (fact("location", "London"),), now=NOW)
    near = qualify(plan(must_have=[criterion], preferences=[criterion]), (), now=NOW)
    near = replace(near, preference_score=20)
    assert [key for key, _ in rank((("z", near), ("b", confirmed), ("a", confirmed)))] == [
        "a",
        "b",
        "z",
    ]


def test_clock_and_nonfinite_values_are_rejected():
    with pytest.raises(ValueError):
        fact("size", float("nan"))
    with pytest.raises(ValueError):
        qualify(plan(), (), now=datetime(2026, 10, 13))
    criterion = Criterion(field="post", operator="recent", value=1e308)
    assert evaluate(criterion, (fact("post", "post", event_at=NOW),), now=NOW).outcome == "matched"
