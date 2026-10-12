"""Explicitly opt-in free search trial; persist metrics, never raw result content."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from skriller.connectors.search import ExaKeylessSearch, SearchUnavailable

CORPUS = [
    (
        "company",
        "category:company fintech companies Bengaluru India official websites",
        (),
        "Return official company pages relevant to fintech businesses in Bengaluru.",
    ),
    (
        "linkedin",
        "category:company fintech companies in Bengaluru listed on LinkedIn",
        ("linkedin.com",),
        "Return publicly indexed LinkedIn company-page references only. Do not enrich private contacts.",
    ),
    (
        "reddit",
        "Reddit discussions startup founders manual payment reconciliation",
        ("reddit.com",),
        "Return publicly indexed Reddit discussions relevant to manual payment reconciliation problems.",
    ),
]


async def trial():
    report = {
        "provider": "exa_keyless",
        "authenticated": False,
        "paid_fallback": False,
        "queries": [],
        "qualified_lead_accuracy": "not_measured",
        "pagination": "not_supported",
        "formal_dork_semantics": "not_verified",
        "domains": "validated_post_filter",
        "billed_cost": "no_authenticated_billing_account",
    }
    client = ExaKeylessSearch()
    for name, query, domains, objective in CORPUS:
        start = time.monotonic()
        try:
            result = await client.search(query, objective=objective, limit=2, domains=domains)
            outcome = {
                "id": name,
                "status": "passed" if result.hits else "zero_yield",
                "returned_references": len(result.hits),
                "rejected_references": result.rejected,
                "truncated": result.truncated,
            }
        except SearchUnavailable as error:
            outcome = {"id": name, "status": "unavailable", "code": error.failure.code}
        outcome["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["queries"].append(outcome)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.exit(2, "Use --live to make three bounded, keyless public search calls.\n")
    report = asyncio.run(trial())
    destination = Path(__file__).resolve().parents[2] / "docs/completions/EXA-KEYLESS.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
