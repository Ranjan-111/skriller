"""Run a small labelled, synthetic HTML extraction benchmark on local Ollama."""

from __future__ import annotations

import argparse
import json
import statistics

try:
    from .model_trial import ROOT, trial_case
except ImportError:  # Direct CLI execution places this script's directory on sys.path.
    from model_trial import ROOT, trial_case


DATASET = ROOT / "tests/fixtures/research/model_eval.json"


def benchmark(model: str, *, include_structured_data: bool = True) -> dict:
    examples = json.loads(DATASET.read_text())
    if not isinstance(examples, list) or not 1 <= len(examples) <= 20:
        raise ValueError("Benchmark corpus must contain 1–20 labelled examples")
    ids = [item.get("id") for item in examples if isinstance(item, dict)]
    if len(ids) != len(examples) or len(set(ids)) != len(ids):
        raise ValueError("Each benchmark example needs a unique identifier")

    results = [
        {
            "id": item["id"],
            **trial_case(model, item["html"], item["expected"], include_structured_data),
        }
        for item in examples
    ]
    elapsed = [item["elapsed_seconds"] for item in results]
    passed = sum(item.get("status") == "passed" for item in results)
    call_counts = [item.get("model_calls") for item in results]
    calls_observed = all(isinstance(value, int) and value >= 0 for value in call_counts)
    usage_records = [item.get("token_usage") for item in results]
    usage_available = [isinstance(value, dict) for value in usage_records]
    usage_reported_calls = sum(item.get("usage_reported_calls", 0) for item in results)
    missing_usage_calls = sum(call_counts) - usage_reported_calls if calls_observed else None
    usage_status = (
        "complete"
        if calls_observed and missing_usage_calls == 0
        else "partial"
        if usage_reported_calls
        else "unavailable"
        if calls_observed
        else "unknown"
    )
    token_usage = None
    if any(usage_available):
        token_usage = {
            key: sum(value[key] for value in usage_records if isinstance(value, dict))
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    return {
        "status": "diagnostic_only",
        "model": model,
        "provider": "local_ollama",
        "synthetic_only": True,
        "corpus_size": len(results),
        "calls": sum(call_counts) if calls_observed else None,
        "calls_observed": calls_observed,
        "successful_model_calls": sum(item.get("successful_model_calls", 0) for item in results),
        "failed_model_calls": sum(item.get("failed_model_calls", 0) for item in results),
        "correct_records": passed,
        "record_accuracy": round(passed / len(results), 4),
        "mean_seconds": round(statistics.mean(elapsed), 3),
        "median_seconds": round(statistics.median(elapsed), 3),
        "token_usage": token_usage,
        "token_usage_coverage": {
            "cases_with_reported_usage": sum(usage_available),
            "cases_without_reported_usage": len(results) - sum(usage_available),
            "model_calls_with_reported_usage": usage_reported_calls,
            "model_calls_without_reported_usage": missing_usage_calls,
            "status": usage_status,
        },
        "cost_usd": None,
        "limitations": [
            "Five synthetic records are not a release-scale quality estimate.",
            "Token counts include only usage returned by local model callbacks; missing reports are not estimated.",
            "This local trial does not select or validate a hosted pilot model.",
        ],
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--raw-html", action="store_true")
    args = parser.parse_args()
    report = benchmark(args.model, include_structured_data=not args.raw_html)
    safe_name = args.model.replace(":", "-")
    target = ROOT / "docs/completions" / f"OLLAMA-{safe_name}-benchmark.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
