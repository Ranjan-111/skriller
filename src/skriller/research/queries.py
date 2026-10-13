"""Bounded query variants from trusted plans; search syntax is not qualification.

This is product glue: the supplied engines do not implement the product's plan
translation. Provider syntax capabilities are explicit server choices, never
inferred from a provider accepting a request.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal

from skriller.contracts import Criterion, SearchPlan, Source

Support = Literal["verified", "unsupported", "unverified"]
SOURCE_DOMAINS: dict[Source, tuple[str, ...]] = {
    "linkedin": ("linkedin.com",),
    "reddit": ("reddit.com",),
    "github": ("github.com",),
    "youtube": ("youtube.com",),
    "x": ("x.com", "twitter.com"),
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com",),
    "web": (),
    "rss": (),
}


@dataclass(frozen=True)
class QueryCapabilities:
    provider: str
    domain_operator: Support = "unsupported"
    quoted_phrase: Support = "unsupported"
    negative_operator: Support = "unsupported"

    def __post_init__(self):
        if not self.provider or len(self.provider) > 100:
            raise ValueError("Bounded provider identity required")
        if any(
            value not in {"verified", "unsupported", "unverified"}
            for value in (self.domain_operator, self.quoted_phrase, self.negative_operator)
        ):
            raise ValueError("Invalid provider syntax support")


EXA_KEYLESS = QueryCapabilities("exa_keyless", "unverified", "unverified", "unverified")


@dataclass(frozen=True)
class CriterionRoute:
    group: str
    index: int
    field: str
    operator: str
    value: object
    route: str


@dataclass(frozen=True)
class QueryVariant:
    source: Source
    query: str
    objective: str
    target_domains: tuple[str, ...]
    criteria: tuple[CriterionRoute, ...]
    used_operators: tuple[str, ...]
    exact_match_claim: bool = False
    candidate_filter: str = "public_url_then_domain_postfilter"


@dataclass(frozen=True)
class QueryBatch:
    original_objective: str
    plan_snapshot: dict
    variants: tuple[QueryVariant, ...]
    criteria: tuple[CriterionRoute, ...]
    warnings: tuple[str, ...]
    omitted_variants: int
    stop_reason: str | None = None


def _plain(value: object) -> str:
    if isinstance(value, list):
        text = " or ".join(str(item) for item in value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    # Preserve the full literal in objective/snapshot, but prevent criterion
    # text from injecting provider syntax that was not explicitly enabled.
    text = re.sub(r'["\\:]', " ", text)
    text = re.sub(r"(?<!\w)-(?=\w)", " ", text)
    return " ".join(text.split())


def _criterion_text(criterion: Criterion) -> str:
    labels = {
        "eq": "equals",
        "contains": "includes",
        "gte": "at least",
        "lte": "at most",
        "in": "one of",
        "recent": "within requested recency",
    }
    return f"{criterion.field.replace('_', ' ')} {labels[criterion.operator]} {_plain(criterion.value)}"


def _quoted(value: str) -> str:
    # Model/criteria strings can contain user syntax; quoted operator values
    # never interpolate raw quote delimiters or backslash escapes.
    return '"' + value.replace("\\", " ").replace('"', " ") + '"'


def build_queries(
    plan: SearchPlan,
    original_objective: str,
    *,
    capabilities: QueryCapabilities = EXA_KEYLESS,
    max_variants: int = 20,
) -> QueryBatch:
    if not isinstance(plan, SearchPlan):
        raise TypeError("Query generation requires a validated SearchPlan")
    if (
        not isinstance(original_objective, str)
        or not original_objective.strip()
        or len(original_objective) > 1500
    ):
        raise ValueError("Original objective must contain 1–1500 characters")
    if (
        isinstance(max_variants, bool)
        or not isinstance(max_variants, int)
        or not 1 <= max_variants <= 20
    ):
        raise ValueError("Query expansion cap must be 1–20")
    warnings = [
        f"provider_{operator}_{support}"
        for operator, support in (
            ("domain_operator", capabilities.domain_operator),
            ("quoted_phrase", capabilities.quoted_phrase),
            ("negative_operator", capabilities.negative_operator),
        )
        if support != "verified"
    ]
    routes = tuple(
        CriterionRoute(
            group,
            index,
            item.field,
            item.operator,
            item.value,
            "search_hint_then_evidence_validation",
        )
        for group, items in (
            ("must_have", plan.must_have),
            ("preference", plan.preferences),
            ("exclusion", plan.exclusions),
        )
        for index, item in enumerate(items)
    )
    for item in routes:
        if item.operator not in {"eq", "contains"}:
            warnings.append(
                f"criterion_operator_not_enforced:{item.group}:{item.index}:{item.operator}"
            )
    warnings.extend(f"unsupported_criterion:{value}" for value in plan.unsupported_criteria)
    snapshot = plan.model_dump(mode="json")
    payload = {
        "objective": original_objective,
        "must_have": snapshot["must_have"],
        "preferences": snapshot["preferences"],
        "exclusions": snapshot["exclusions"],
        "freshness_days": plan.freshness_days,
        "requested_fields": plan.requested_fields,
        "unsupported_criteria": plan.unsupported_criteria,
        "instruction": "Search candidates only; every criterion requires later evidence validation.",
    }
    objective = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    stop = (
        "clarification_required"
        if plan.clarification
        else "search_budget_exhausted"
        if not plan.limits.search_calls
        else "provider_objective_bound_exceeded"
        if len(objective) > 4096
        else "no_sources_selected"
        if not plan.sources
        else None
    )
    if stop:
        return QueryBatch(
            original_objective, snapshot, (), routes, tuple(dict.fromkeys(warnings)), 0, stop
        )

    required = [route for route in routes if route.group != "preference"]
    base: str = plan.entity_type if routes else _plain(original_objective)
    for criterion in plan.must_have:
        base += " " + _criterion_text(criterion)
        if (
            criterion.operator in {"eq", "contains"}
            and isinstance(criterion.value, str)
            and capabilities.quoted_phrase == "verified"
        ):
            base += " " + _quoted(criterion.value)
    for criterion in plan.exclusions:
        if (
            capabilities.negative_operator == "verified"
            and criterion.operator in {"eq", "contains"}
            and isinstance(criterion.value, str)
        ):
            base += " -" + _quoted(criterion.value)
        else:
            base += " exclude " + _criterion_text(criterion)
    variants = []
    seen = set()

    def append(source, text, selected_routes):
        domains = SOURCE_DOMAINS[source]
        operators = []
        if domains and capabilities.domain_operator == "verified":
            # Separate domain alternatives avoid assuming unverified OR syntax.
            domain_options = domains
        else:
            domain_options = (None,)
            if domains:
                text = f"{source} {text}"
        for domain in domain_options:
            query = text + (f" site:{domain}" if domain else "")
            if len(query) > 2000:
                warnings.append(f"query_bound_exceeded:{source}")
                continue
            if domain:
                operators.append("site")
            if capabilities.quoted_phrase == "verified" and '"' in query:
                operators.append("quoted_phrase")
            if capabilities.negative_operator == "verified" and ' -"' in query:
                operators.append("negative")
            identity = (source, query)
            if identity in seen:
                continue
            seen.add(identity)
            variants.append(
                QueryVariant(
                    source,
                    query,
                    objective,
                    (domain,) if domain else domains,
                    tuple(selected_routes),
                    tuple(dict.fromkeys(operators)),
                )
            )

    # Cover sources before spending additional calls on preference variants.
    for source in plan.sources:
        append(source, base, required)
    for index, criterion in enumerate(plan.preferences):
        extra = _criterion_text(criterion)
        for source in plan.sources:
            append(
                source,
                f"{base} prefer {extra}",
                [
                    *required,
                    next(
                        item
                        for item in routes
                        if item.group == "preference" and item.index == index
                    ),
                ],
            )
    cap = min(max_variants, plan.limits.search_calls, 20)
    omitted = max(0, len(variants) - cap)
    if omitted:
        warnings.append(f"query_variants_omitted:{omitted}")
        omitted_sources = set(plan.sources) - {variant.source for variant in variants[:cap]}
        warnings.extend(
            f"source_not_queried_due_to_budget:{source}" for source in sorted(omitted_sources)
        )
    if plan.freshness_days is not None:
        warnings.append("freshness_requires_evidence_validation")
    if "rss" in plan.sources:
        warnings.append("rss_index_search_is_not_feed_subscription")
    return QueryBatch(
        original_objective,
        snapshot,
        tuple(variants[:cap]),
        routes,
        tuple(dict.fromkeys(warnings)),
        omitted,
        "provider_query_bound_exceeded" if not variants else None,
    )
