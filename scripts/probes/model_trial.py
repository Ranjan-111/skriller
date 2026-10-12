"""Opt-in local model trial using the copied ScrapeGraph-AI graph, not a new engine."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from langchain_ollama import ChatOllama
from pydantic import BaseModel
from scrapegraphai.graphs import SmartScraperGraph
from scrapling import Selector

ROOT = Path(__file__).resolve().parents[2]


class CompanyFacts(BaseModel):
    company: str
    founder: str
    city: str | None = None
    employees: int | None = None
    private_email: str | None = None


def score_facts(answer: dict, expected: dict) -> dict:
    """Schema-valid hallucinations remain factual failures, including private contacts."""
    parsed = CompanyFacts.model_validate(answer).model_dump()
    checks = {key: parsed[key] == value for key, value in expected.items()}
    return {
        "answer": parsed,
        "checks": checks,
        "status": "passed" if all(checks.values()) else "quality_failed",
    }


def trial(model: str, include_structured_data: bool = False) -> dict:
    source = (ROOT / "tests/fixtures/research/company.html").read_text()
    if include_structured_data:
        # Reuse the copied selector to preserve evidence the graph's default
        # HTML-to-Markdown path otherwise omits from the document head.
        page = Selector(source)
        source = (
            page.get_all_text()
            + "\nSource JSON-LD:\n"
            + "\n".join(
                str(value) for value in page.css('script[type="application/ld+json"]::text')
            )
        )
    llm = ChatOllama(
        model=model,
        base_url="http://127.0.0.1:11434",
        temperature=0,
        format="json",
        num_predict=700,
        num_ctx=4096,
        reasoning=False,
        client_kwargs={"timeout": 90},
    )
    graph = SmartScraperGraph(
        prompt="Extract company name, founder name, city and employee count from the supplied synthetic company page. Private email is not stated: return null. Return only the requested schema; never invent facts.",
        source=source,
        schema=CompanyFacts,
        config={
            "llm": {"model_instance": llm, "model_tokens": 4096},
            "verbose": False,
            "timeout": 90,
            "reattempt": False,
            "reasoning": False,
        },
    )
    started = time.monotonic()
    record = {
        "model": model,
        "provider": "local_ollama",
        "synthetic_fixture": True,
        "structured_data_preserved": include_structured_data,
        "copied_graph": "third_party/scrapegraph-ai/scrapegraphai/graphs/smart_scraper_graph.py",
    }
    try:
        answer = CompanyFacts.model_validate(graph.run()).model_dump()
        expected = {
            "company": "Aurora Ledger",
            "founder": "Mira Rao",
            "city": "Bengaluru",
            "employees": 25,
            "private_email": None,
        }
        record.update(score_facts(answer, expected))
    except Exception as exc:  # noqa: BLE001 - trial records unexpected upstream failures
        record.update(status="failed", error_type=type(exc).__name__)
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--include-structured-data", action="store_true")
    args = parser.parse_args()
    result = trial(args.model, args.include_structured_data)
    suffix = "-structured" if args.include_structured_data else "-raw"
    destination = (
        ROOT / "docs/completions" / ("OLLAMA-" + args.model.replace(":", "-") + suffix + ".json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
