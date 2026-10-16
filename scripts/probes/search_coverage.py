"""Measure bounded keyless Exa search coverage without retaining result content."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Protocol

from agent_reach.utils.url import host_matches

from skriller.connectors.search import ExaKeylessSearch, SearchPage

ROOT = Path(__file__).resolve().parents[2]
MAX_QUERIES = 4
MAX_HITS_PER_QUERY = 5
CORPUS = (
    {
        "id": "linkedin",
        "query": 'site:linkedin.com "fintech" founder Bengaluru -jobs',
        "objective": "Find public search references to fintech founders in Bengaluru.",
        "target_domain": "linkedin.com",
        "expected_urls": (),
    },
    {
        "id": "reddit",
        "query": 'site:reddit.com "CRM" migration -hiring',
        "objective": "Find public Reddit discussions about CRM migrations.",
        "target_domain": "reddit.com",
        "expected_urls": (),
    },
    {
        "id": "company",
        "query": '"fintech" Bengaluru careers -agency',
        "objective": "Find public company career references related to fintech in Bengaluru.",
        "target_domain": None,
        "expected_urls": (),
    },
)


class Searcher(Protocol):
    async def search(self, query: str, *, objective: str, limit: int = 5) -> SearchPage: ...


def _safe_corpus(corpus: tuple[dict[str, Any], ...]) -> None:
    if not 1 <= len(corpus) <= MAX_QUERIES:
        raise ValueError("Search coverage trial requires 1–4 queries")
    ids = [item.get("id") for item in corpus]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Search query identifiers must be unique nonempty strings")
    for item in corpus:
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise ValueError("Search query must be nonempty")
        if not isinstance(item.get("objective"), str) or not item["objective"].strip():
            raise ValueError("Search objective must be nonempty")
        if len(item.get("expected_urls", ())) > 100:
            raise ValueError("Expected URL labels exceed the bounded corpus limit")


async def measure(
    searcher: Searcher,
    *,
    corpus: tuple[dict[str, Any], ...] = CORPUS,
    limit: int = MAX_HITS_PER_QUERY,
) -> dict[str, Any]:
    """Call the existing adapter once per fixed query and retain scalar metrics only."""
    _safe_corpus(corpus)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HITS_PER_QUERY:
        raise ValueError("Search coverage trial allows 1–5 hits per query")

    rows: list[dict[str, Any]] = []
    invocations = 0
    started_all = time.monotonic()
    for item in corpus:
        started = time.monotonic()
        invocations += 1
        try:
            page = await searcher.search(
                item["query"], objective=item["objective"], limit=limit
            )
        except Exception as error:  # noqa: BLE001 - report only a type, never remote text
            rows.append(
                {
                    "id": item["id"],
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "provider_invocations": 1,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "accepted_hits": 0,
                    "rejected_hits": 0,
                    "truncated": None,
                    "target_domain_matches": None,
                    "expected_url_matches": None,
                    "pagination_supported": False,
                }
            )
            continue

        hits = page.hits
        target_domain = item.get("target_domain")
        expected = set(item.get("expected_urls", ()))
        rows.append(
            {
                "id": item["id"],
                "status": "measured",
                "provider_invocations": 1,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "accepted_hits": len(hits),
                "rejected_hits": page.rejected,
                "truncated": page.truncated,
                "target_domain_matches": (
                    sum(host_matches(hit.url, target_domain) for hit in hits)
                    if target_domain
                    else None
                ),
                "expected_url_matches": (
                    len(expected.intersection(hit.url for hit in hits)) if expected else None
                ),
                "expected_url_label_count": len(expected),
                "pagination_supported": page.pagination_supported,
            }
        )

    complete = all(row["status"] == "measured" for row in rows)
    return {
        "schema_version": 1,
        "provider": "exa_keyless",
        "status": "measured" if complete else "partial",
        "synthetic_or_public_queries_only": True,
        "query_count": len(corpus),
        "provider_invocations": invocations,
        "elapsed_ms": round((time.monotonic() - started_all) * 1000),
        "accepted_hits": sum(row["accepted_hits"] for row in rows),
        "rejected_hits": sum(row["rejected_hits"] for row in rows),
        "truncated_queries": sum(row["truncated"] is True for row in rows),
        "pagination_supported": False,
        "pagination_observation": "adapter exposes one bounded result page; no pagination call made",
        "operator_semantics": "unknown",
        "domain_filter_semantics": "target-domain matches measured from returned URLs; not provider enforcement",
        "duplicate_rate": "unavailable_after_adapter_deduplication",
        "billed_cost": "unknown_no_authenticated_billing_account",
        "commercial_use_and_storage_rights": "unverified",
        "raw_queries_or_results_persisted": False,
        "query_results": rows,
        "limitations": [
            "Exact expected-URL matching is unavailable when a query has no ground-truth URL labels.",
            "A single bounded public corpus does not establish source completeness or lead quality.",
            "One logical adapter invocation may use multiple transport requests for MCP setup; network request count is not inferred.",
        ],
    }


async def main_async(*, output: Path, limit: int = MAX_HITS_PER_QUERY) -> dict[str, Any]:
    report = await measure(ExaKeylessSearch(), limit=limit)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run the fixed public-query corpus")
    parser.add_argument("--limit", type=int, default=MAX_HITS_PER_QUERY)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/completions/EXA-COVERAGE.json"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("live public search requires explicit --live opt-in")
    report = asyncio.run(main_async(output=args.output, limit=args.limit))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
