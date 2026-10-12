"""Opt-in bounded Brave search coverage trial; never scrape Google or persist result bodies.

No Brave client exists in the supplied three engines. Reuse Agent-Reach's copied
public-URL and exact-domain helpers; provider requests/metrics are new probe glue.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from decimal import Decimal
from urllib.parse import urldefrag

import httpx
from agent_reach.utils.url import host_matches, normalize_public_http_url

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
CORPUS = (
    {
        "id": "linkedin",
        "query": 'site:linkedin.com "fintech" founder Bengaluru -jobs',
        "domain": "linkedin.com",
    },
    {"id": "reddit", "query": 'site:reddit.com "CRM" migration -hiring', "domain": "reddit.com"},
    {"id": "company", "query": '"fintech" Bengaluru careers -agency', "domain": None},
)
DOCUMENTED_OPERATORS = ["site", "quoted_phrase", "exclusion"]


def validate_request(query: str, count: int, offset: int) -> None:
    if not query.strip() or len(query) > 600 or len(query.split()) > 75:
        raise ValueError("Query exceeds provider bounds")
    if not 1 <= count <= 20 or not 0 <= offset <= 9:
        raise ValueError("Count/offset exceed provider bounds")


def fetch_page(*, query: str, count: int, offset: int, country: str, api_key: str) -> dict:
    validate_request(query, count, offset)
    with (
        httpx.Client(timeout=15, follow_redirects=False) as client,
        client.stream(
            "GET",
            ENDPOINT,
            params={
                "q": query,
                "count": count,
                "offset": offset,
                "country": country,
                "search_lang": "en",
                "operators": "true",
                "spellcheck": "false",
            },
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        ) as response,
    ):
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Search response exceeds probe limit")
        return json.loads(raw)


def measure_page(payload: dict, domain: str | None) -> tuple[dict, set[str]]:
    if not isinstance(payload, dict):
        raise TypeError("Unexpected search response")
    query_metadata = payload.get("query")
    if not isinstance(query_metadata, dict):
        raise TypeError("Unexpected search query metadata")
    web = payload.get("web", {})
    rows = web.get("results", []) if isinstance(web, dict) else None
    if not isinstance(rows, list):
        raise TypeError("Unexpected search result schema")
    valid: set[str] = set()
    invalid = outside = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            raise TypeError("Unexpected search result schema")
        try:
            url = normalize_public_http_url(row["url"])
        except ValueError:
            invalid += 1
            continue
        valid.add(urldefrag(url).url)
        if domain and not host_matches(url, domain):
            outside += 1
    metadata = query_metadata.get("search_operators", {})
    applied = isinstance(metadata, dict) and metadata.get("applied") is True
    sites = metadata.get("sites", []) if isinstance(metadata, dict) else []
    reported_domain = domain is not None and isinstance(sites, list) and domain in sites
    domain_supported = bool(
        domain and rows and invalid == 0 and outside == 0 and applied and reported_domain
    )
    fields = sorted({key for row in rows for key in row})
    return {
        "returned": len(rows),
        "valid_public_urls": len(rows) - invalid,
        "invalid_urls": invalid,
        "off_domain_results": outside,
        "domain_constraint_observed": domain_supported if domain else None,
        "operator_metadata_applied": applied,
        "fields": fields,
        "more_results_available": query_metadata.get("more_results_available"),
        "quote_and_exclusion_semantics": "documented_not_measured",
    }, valid


def probe(
    *,
    live: bool = False,
    api_key: str | None = None,
    pages: int = 2,
    count: int = 10,
    country: str = "IN",
    caller=fetch_page,
) -> dict:
    if not 1 <= pages <= 2 or not 1 <= count <= 20 or country not in {"IN", "US", "GB"}:
        raise ValueError("Probe requires <=2 pages, <=20 results and a supported trial country")
    report = {
        "provider": "brave",
        "google_backend": False,
        "query_syntax": "google_style_subset",
        "documented_operators": DOCUMENTED_OPERATORS,
        "operators_experimental": True,
        "status": "skipped",
        "validated": False,
        "country": country,
        "coverage_complete": False,
        "domain_constrained_search_advertisable": False,
        "requests_attempted": 0,
        "queries": [],
        "raw_results_persisted": False,
        "observed_billed_cost_usd": None,
        "nominal_list_price_estimate_usd": "0.000",
        "reason": "Explicit live opt-in and Brave API key required",
    }
    if not live or not api_key:
        return report
    started = time.monotonic()
    domain_outcomes = []
    try:
        for item in CORPUS:
            query_report = {"id": item["id"], "query": item["query"], "pages": []}
            seen: set[str] = set()
            returned = duplicates = 0
            for offset in range(pages):
                validate_request(item["query"], count, offset)
                report["requests_attempted"] += 1
                page, urls = measure_page(
                    caller(
                        query=item["query"],
                        count=count,
                        offset=offset,
                        country=country,
                        api_key=api_key,
                    ),
                    item["domain"],
                )
                duplicates += len(urls & seen) + page["valid_public_urls"] - len(urls)
                seen.update(urls)
                returned += page["returned"]
                query_report["pages"].append({"offset": offset, **page})
                if item["domain"]:
                    domain_outcomes.append(page["domain_constraint_observed"])
            query_report.update(
                unique_urls=len(seen),
                duplicates=duplicates,
                duplicate_rate=duplicates / returned if returned else None,
            )
            report["queries"].append(query_report)
        report.update(
            status="measured",
            validated=True,
            domain_constrained_search_advertisable=bool(domain_outcomes and all(domain_outcomes)),
            reason="Bounded corpus responses measured; no completeness or provider selection claim",
        )
    except Exception as exc:  # noqa: BLE001 - redact provider/key/response text
        report.update(status="failed", reason=f"{type(exc).__name__}: search trial failed")
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    report["nominal_list_price_estimate_usd"] = str(Decimal("0.005") * report["requests_attempted"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--country", choices=["IN", "US", "GB"], default="IN")
    print(
        json.dumps(
            probe(**vars(parser.parse_args()), api_key=os.environ.get("SKRILLER_BRAVE_API_KEY")),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
