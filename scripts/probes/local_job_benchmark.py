"""Measure bounded local fixture processing through Skriller's existing page pipeline.

This diagnostic includes no network, browser, model, or account calls. Fixture
classification outcomes are reported separately from local classification,
cleanup, and total processing time.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import time
import tracemalloc
from pathlib import Path
from typing import Any

from scrapling.engines.toolbelt.custom import Response

from skriller.connectors.classification import classify_page
from skriller.extraction.cleanup import CleanupLimits, prepare_context

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = (
    ("company", "tests/fixtures/research/company.html", "web"),
    ("changed", "tests/fixtures/research/changed.html", "web"),
    ("discussion", "tests/fixtures/research/discussion.html", "reddit"),
    ("challenge", "tests/fixtures/research/challenge.html", "web"),
    ("dynamic", "tests/fixtures/research/dynamic.html", "web"),
)
MAX_REPETITIONS = 20


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.5)))
    return round(ordered[index], 3)


def _rss_observation() -> dict[str, Any]:
    # getrusage is process-wide and reports a platform-specific unit.
    usage = resource.getrusage(resource.RUSAGE_SELF)
    unit = "bytes" if platform.system() == "Darwin" else "kilobytes"
    return {"peak_rss_value": usage.ru_maxrss, "peak_rss_unit": unit}


def benchmark(*, repetitions: int = 3, fixtures=DEFAULT_FIXTURES) -> dict[str, Any]:
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or not 1 <= repetitions <= MAX_REPETITIONS
    ):
        raise ValueError("repetitions must be between 1 and 20")
    if not 1 <= len(fixtures) <= 10:
        raise ValueError("benchmark corpus must contain 1–10 fixtures")

    cases: list[dict[str, Any]] = []
    timings: dict[str, list[float]] = {"classification": [], "cleanup": [], "job": []}
    classification_outcomes: dict[str, int] = {}
    bytes_read = 0
    failures: list[dict[str, str]] = []
    warmup_path = ROOT / DEFAULT_FIXTURES[0][1]
    warmup_body = warmup_path.read_bytes()
    warmup_url = "https://fixture.invalid/warmup"
    warmup_response = Response(
        warmup_url, warmup_body, 200, "OK", {}, {"Content-Type": "text/html"}, {}, adaptive=False
    )
    warmup_result = classify_page(
        warmup_body,
        source="web",
        final_url=warmup_url,
        status=200,
        content_type="text/html",
        document=warmup_response,
    )
    if warmup_result.accepts_content:
        prepare_context(
            warmup_body.decode("utf-8", errors="strict"), warmup_url, limits=CleanupLimits()
        )
    tracemalloc.start()
    tracemalloc.reset_peak()
    process_rss_before = _rss_observation()
    job_started = time.perf_counter()

    for repetition in range(repetitions):
        for case_id, relative_path, source in fixtures:
            path = ROOT / relative_path
            case_started = time.perf_counter()
            try:
                body = path.read_bytes()
                bytes_read += len(body)
                response = Response(
                    f"https://fixture.invalid/{case_id}",
                    body,
                    200,
                    "OK",
                    {},
                    {"Content-Type": "text/html"},
                    {},
                    adaptive=False,
                )
                classify_started = time.perf_counter()
                classification = classify_page(
                    body,
                    source=source,
                    final_url=f"https://fixture.invalid/{case_id}",
                    status=response.status,
                    content_type="text/html",
                    document=response,
                )
                classification_ms = (time.perf_counter() - classify_started) * 1000
                timings["classification"].append(classification_ms)
                classification_outcomes[classification.status] = (
                    classification_outcomes.get(classification.status, 0) + 1
                )

                cleanup_ms = None
                prepared_chunks = None
                if classification.accepts_content:
                    cleanup_started = time.perf_counter()
                    prepared = prepare_context(
                        body.decode("utf-8", errors="strict"),
                        f"https://fixture.invalid/{case_id}",
                        limits=CleanupLimits(),
                    )
                    cleanup_ms = (time.perf_counter() - cleanup_started) * 1000
                    timings["cleanup"].append(cleanup_ms)
                    if hasattr(prepared, "chunks"):
                        prepared_chunks = len(prepared.chunks)
                    elif hasattr(prepared, "code"):
                        failures.append(
                            {"fixture": case_id, "stage": "cleanup", "failure_type": prepared.code}
                        )
                else:
                    failures.append(
                        {
                            "fixture": case_id,
                            "stage": "classification",
                            "outcome": classification.status,
                        }
                    )

                elapsed_ms = (time.perf_counter() - case_started) * 1000
                timings["job"].append(elapsed_ms)
                cases.append(
                    {
                        "id": case_id,
                        "repetition": repetition + 1,
                        "status": classification.status,
                        "static_processing_skipped": not classification.accepts_content,
                        "classification_ms": round(classification_ms, 3),
                        "cleanup_ms": round(cleanup_ms, 3) if cleanup_ms is not None else None,
                        "fixture_bytes": len(body),
                        "prepared_chunks": prepared_chunks,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "cache_state": "filesystem_read_each_iteration; OS cache uncontrolled",
                    }
                )
            except (OSError, UnicodeError, ValueError) as error:
                failures.append(
                    {
                        "fixture": case_id,
                        "stage": "fixture_or_processing",
                        "failure_type": type(error).__name__,
                    }
                )
                cases.append(
                    {
                        "id": case_id,
                        "repetition": repetition + 1,
                        "status": "benchmark_error",
                        "failure_type": type(error).__name__,
                    }
                )

    elapsed_ms = (time.perf_counter() - job_started) * 1000
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    process_rss_after = _rss_observation()
    samples = {
        name: {
            "count": len(values),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
        }
        for name, values in timings.items()
    }
    return {
        "schema_version": 1,
        "status": "diagnostic_only"
        if not failures or all(item["stage"] == "classification" for item in failures)
        else "partial",
        "synthetic_fixture_only": True,
        "network_calls": 0,
        "model_calls": 0,
        "browser_calls": 0,
        "hardware": {"platform": platform.platform(), "python": platform.python_version()},
        "repetitions": repetitions,
        "warmup_samples_excluded": 1,
        "fixture_count": len(fixtures),
        "sample_count": len(cases),
        "stage_timings": samples,
        "job_elapsed_ms": round(elapsed_ms, 3),
        "fixture_bytes_read": bytes_read,
        "classification_outcomes": classification_outcomes,
        "resource_observations": {
            "python_traced_peak_bytes": traced_peak,
            "process_peak_rss_before": process_rss_before,
            "process_peak_rss_after": process_rss_after,
            "rss_delta_not_attributable": True,
        },
        "cache_state": "fixture files read for each sample; OS page cache is uncontrolled; no application cache used",
        "failures": failures,
        "cases": cases,
        "limitations": [
            "Fixture classification outcomes do not measure real source availability or network latency.",
            "Job timing is local file read, copied classification, and cleanup only; it is not end-to-end product latency.",
            "Process peak RSS is cumulative for this process and cannot be attributed to this run; Python allocation peak is reported separately.",
            "Small fixture percentiles are diagnostic and are not product targets or an SLA.",
            "No concurrency, browser capacity, host responsiveness, or multi-workspace behavior is measured.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/completions/SKR-075-LOCAL.json")
    args = parser.parse_args()
    report = benchmark(repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
