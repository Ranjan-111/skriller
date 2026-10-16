from __future__ import annotations

import pytest

from scripts.probes.local_job_benchmark import benchmark


def test_local_benchmark_reports_stage_samples_and_separates_fixture_access_failures():
    report = benchmark(repetitions=2)

    assert report["status"] == "diagnostic_only"
    assert report["network_calls"] == report["model_calls"] == report["browser_calls"] == 0
    assert report["sample_count"] == 10
    assert report["stage_timings"]["classification"]["count"] == 10
    assert report["stage_timings"]["job"]["p50_ms"] is not None
    assert report["classification_outcomes"].get("challenge", 0) == 2
    assert all(
        item["static_processing_skipped"]
        for item in report["cases"]
        if item["status"] == "challenge"
    )
    assert report["resource_observations"]["python_traced_peak_bytes"] > 0
    assert report["resource_observations"]["rss_delta_not_attributable"] is True
    assert "not product targets" in " ".join(report["limitations"])


@pytest.mark.parametrize("repetitions", [0, 21, True])
def test_local_benchmark_rejects_unbounded_repetition_counts(repetitions):
    with pytest.raises(ValueError):
        benchmark(repetitions=repetitions)


def test_local_benchmark_rejects_empty_corpus():
    with pytest.raises(ValueError):
        benchmark(fixtures=())
