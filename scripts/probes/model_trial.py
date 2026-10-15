"""Opt-in local model trial using the copied ScrapeGraph-AI graph, not a new engine."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_ollama import ChatOllama
from pydantic import BaseModel
from scrapegraphai.graphs import SmartScraperGraph
from scrapling import Selector

ROOT = Path(__file__).resolve().parents[2]


class TrialUsageCallback(BaseCallbackHandler):
    """Record only call and usage facts the local model actually reports."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started: set[UUID] = set()
        self._ended: set[UUID] = set()
        self._usage: list[dict[str, int]] = []
        self._failed: set[UUID] = set()

    def on_chat_model_start(
        self, serialized: dict, messages: list, *, run_id: UUID, **kwargs: Any
    ) -> None:
        with self._lock:
            self._started.add(run_id)

    def on_llm_start(
        self, serialized: dict, prompts: list[str], *, run_id: UUID, **kwargs: Any
    ) -> None:
        with self._lock:
            self._started.add(run_id)

    @staticmethod
    def _valid_usage(value: Any) -> dict[str, int] | None:
        if not isinstance(value, dict):
            return None
        aliases = {
            "input_tokens": value.get("input_tokens", value.get("prompt_tokens")),
            "output_tokens": value.get("output_tokens", value.get("completion_tokens")),
            "total_tokens": value.get("total_tokens"),
        }
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in aliases.values()
        ):
            return None
        if aliases["input_tokens"] + aliases["output_tokens"] != aliases["total_tokens"]:
            return None
        return aliases

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        usage = None
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = self._valid_usage(getattr(message, "usage_metadata", None))
                if usage:
                    break
            if usage:
                break
        if usage is None and response.llm_output:
            usage = self._valid_usage(response.llm_output.get("token_usage"))
        with self._lock:
            self._ended.add(run_id)
            if usage:
                self._usage.append(usage)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            self._failed.add(run_id)

    @property
    def report(self) -> dict[str, Any]:
        with self._lock:
            calls = len(self._started | self._ended | self._failed)
            usage_calls = len(self._usage)
            totals = {
                key: sum(item[key] for item in self._usage)
                for key in ("input_tokens", "output_tokens", "total_tokens")
            }
            return {
                "model_calls": calls,
                "successful_model_calls": len(self._ended),
                "failed_model_calls": len(self._failed),
                "usage_reported_calls": usage_calls,
                "token_usage": totals if usage_calls else None,
            }


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


def trial_case(
    model: str, source: str, expected: dict, include_structured_data: bool = False
) -> dict:
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
    usage_callback = TrialUsageCallback()
    llm = ChatOllama(
        model=model,
        base_url="http://127.0.0.1:11434",
        temperature=0,
        format="json",
        num_predict=700,
        num_ctx=4096,
        reasoning=False,
        client_kwargs={"timeout": 90},
        callbacks=[usage_callback],
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
        record.update(score_facts(answer, expected))
    except Exception as exc:  # noqa: BLE001 - trial records unexpected upstream failures
        record.update(status="failed", error_type=type(exc).__name__)
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record.update(usage_callback.report)
    return record


def trial(model: str, include_structured_data: bool = False) -> dict:
    source = (ROOT / "tests/fixtures/research/company.html").read_text()
    expected = {
        "company": "Aurora Ledger",
        "founder": "Mira Rao",
        "city": "Bengaluru",
        "employees": 25,
        "private_email": None,
    }
    return trial_case(model, source, expected, include_structured_data)


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
