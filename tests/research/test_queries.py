from dataclasses import replace
from uuid import uuid4

import pytest

from skriller.contracts import Criterion, Limits, SearchPlan
from skriller.research.queries import EXA_KEYLESS, QueryCapabilities, build_queries


def plan(**overrides):
    data = {
        "workspace_id": uuid4(),
        "conversation_id": uuid4(),
        "revision": 1,
        "entity_type": "person",
        "sources": ["linkedin", "web"],
        "must_have": [
            Criterion(field="role", operator="contains", value="founder"),
            Criterion(field="industry", operator="eq", value="fintech"),
        ],
        "exclusions": [Criterion(field="company_type", operator="eq", value="consulting")],
        "limits": Limits(search_calls=4),
    }
    return SearchPlan(**{**data, **overrides})


def test_free_provider_does_not_claim_unverified_search_operators():
    objective = "Find fintech founders on LinkedIn, exclude consulting"
    request = plan()
    batch = build_queries(request, objective)
    assert 1 <= len(batch.variants) <= request.limits.search_calls
    linkedin = batch.variants[0]
    assert linkedin.source == "linkedin" and linkedin.target_domains == ("linkedin.com",)
    assert "linkedin" in linkedin.query and "founder" in linkedin.query
    assert (
        "fintech" in linkedin.query and "exclude company type equals consulting" in linkedin.query
    )
    assert "site:" not in linkedin.query and ' -"' not in linkedin.query
    assert not linkedin.exact_match_claim and not linkedin.used_operators
    assert objective in linkedin.objective
    assert "consulting" in linkedin.objective and "exclusions" in linkedin.objective
    assert batch.original_objective == objective
    assert batch.plan_snapshot == request.model_dump(mode="json")
    assert "provider_quoted_phrase_unverified" in batch.warnings


def test_verified_syntax_is_bounded_and_still_not_factual_exact_match():
    capabilities = QueryCapabilities("fixture_verified", "verified", "verified", "verified")
    batch = build_queries(
        plan(), "Find fintech founders exclude consulting", capabilities=capabilities
    )
    query = batch.variants[0]
    assert "site:linkedin.com" in query.query
    assert '"founder"' in query.query and '-"consulting"' in query.query
    assert set(query.used_operators) == {"site", "quoted_phrase", "negative"}
    assert not query.exact_match_claim
    assert len([item for item in query.criteria if item.group == "must_have"]) == 2
    assert any(item.group == "exclusion" for item in query.criteria)


def test_numeric_membership_recency_and_freshness_stay_visible_not_enforced():
    request = plan(
        must_have=[
            Criterion(field="employee_count", operator="gte", value=25),
            Criterion(field="industry", operator="in", value=["fintech", "banking"]),
            Criterion(field="hiring", operator="recent", value=30),
        ],
        freshness_days=7,
        unsupported_criteria=["private revenue"],
    )
    batch = build_queries(request, "Companies with 25 employees and recent hiring")
    assert "at least 25" in batch.variants[0].query
    assert "one of fintech or banking" in batch.variants[0].query
    assert "within requested recency 30" in batch.variants[0].query
    assert "criterion_operator_not_enforced:must_have:0:gte" in batch.warnings
    assert "criterion_operator_not_enforced:must_have:1:in" in batch.warnings
    assert "freshness_requires_evidence_validation" in batch.warnings
    assert "unsupported_criterion:private revenue" in batch.warnings
    assert "private revenue" in batch.variants[0].objective


def test_sources_before_preferences_total_cap_and_omissions_explicit():
    request = plan(
        sources=["linkedin", "reddit", "github", "web"],
        limits=Limits(search_calls=3),
        preferences=[Criterion(field="location", operator="eq", value="Bengaluru")],
    )
    batch = build_queries(request, "Founders ideally in Bengaluru")
    assert [variant.source for variant in batch.variants] == ["linkedin", "reddit", "github"]
    assert batch.omitted_variants == 5
    assert "source_not_queried_due_to_budget:web" in batch.warnings
    assert "Bengaluru" in batch.variants[0].objective  # preference retained, even unexecuted
    assert len(batch.criteria) == 4
    assert len(build_queries(request, "Founders", max_variants=1).variants) == 1


def test_provider_without_quotes_does_not_emit_phrase_operator():
    capabilities = replace(EXA_KEYLESS, quoted_phrase="unsupported")
    batch = build_queries(plan(), "Find fintech founders", capabilities=capabilities)
    assert all('"' not in variant.query for variant in batch.variants)
    assert all(not variant.exact_match_claim for variant in batch.variants)
    assert "provider_quoted_phrase_unsupported" in batch.warnings


def test_zero_budget_clarification_and_oversize_never_silently_truncate():
    assert (
        build_queries(plan(limits=Limits(search_calls=0)), "Founders").stop_reason
        == "search_budget_exhausted"
    )
    ambiguous = build_queries(
        plan(clarification="Person location or headquarters?"), "Founders in Paris"
    )
    assert not ambiguous.variants and ambiguous.stop_reason == "clarification_required"
    long = "x" * 500
    request = plan(
        must_have=[
            Criterion(field=f"field_{index}", operator="eq", value=long) for index in range(20)
        ]
    )
    batch = build_queries(request, "Full objective must not be truncated")
    assert not batch.variants and batch.stop_reason == "provider_objective_bound_exceeded"
    assert (
        len(batch.criteria) == 21
        and batch.plan_snapshot["must_have"] == request.model_dump(mode="json")["must_have"]
    )


def test_domain_alternatives_do_not_assume_or_operator_and_no_criteria_keeps_prompt():
    request = plan(sources=["x"], must_have=[], exclusions=[], limits=Limits(search_calls=20))
    batch = build_queries(
        request,
        "Find developer discussions",
        capabilities=QueryCapabilities("verified", "verified"),
    )
    assert len(batch.variants) == 2
    assert {variant.target_domains for variant in batch.variants} == {("x.com",), ("twitter.com",)}
    assert all("Find developer discussions" in variant.query for variant in batch.variants)
    assert all(" OR " not in variant.query for variant in batch.variants)


@pytest.mark.parametrize("cap", [True, 0, 21])
def test_expansion_bound(cap):
    with pytest.raises(ValueError):
        build_queries(plan(), "Founders", max_variants=cap)


def test_snapshot_and_original_plan_are_not_mutated():
    request = plan()
    before = request.model_dump(mode="json")
    batch = build_queries(request, "Fintech founders")
    batch.plan_snapshot["must_have"][0]["value"] = "changed snapshot"
    assert request.model_dump(mode="json") == before


def test_criterion_text_cannot_inject_unverified_provider_operators():
    request = plan(
        must_have=[Criterion(field="role", operator="eq", value='site:evil.org "CEO" -founder')],
        exclusions=[],
    )
    batch = build_queries(request, 'Find site:evil.org "CEO" -founder')
    assert all(
        "site:" not in item.query and '"' not in item.query and "-founder" not in item.query
        for item in batch.variants
    )
    assert batch.original_objective == 'Find site:evil.org "CEO" -founder'
    assert batch.plan_snapshot["must_have"][0]["value"] == 'site:evil.org "CEO" -founder'
