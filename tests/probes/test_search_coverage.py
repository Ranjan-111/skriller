from datetime import UTC, datetime

import pytest

from scripts.probes.search_coverage import measure
from skriller.connectors.search import SearchHit, SearchPage


class FixtureSearch:
    def __init__(self, page=None, error=None):
        self.page = page or SearchPage(
            hits=[
                SearchHit(title="Synthetic title", url="https://example.org/a", snippet="private snippet", rank=1),
                SearchHit(title="Second synthetic", url="https://outside.test/b", snippet="other text", rank=2),
            ],
            rejected=3,
            truncated=True,
            pagination_supported=False,
            query="fixture query",
            observed_at=datetime.now(UTC),
        )
        self.error = error
        self.calls = []

    async def search(self, query, *, objective, limit):
        self.calls.append((query, objective, limit))
        if self.error:
            raise self.error
        return self.page


@pytest.mark.asyncio
async def test_measure_records_one_logical_call_and_only_scalar_coverage():
    searcher = FixtureSearch()
    corpus = (
        {
            "id": "synthetic",
            "query": "secret search prompt",
            "objective": "synthetic objective",
            "target_domain": "example.org",
            "expected_urls": ("https://example.org/a", "https://example.org/missing"),
        },
    )

    report = await measure(searcher, corpus=corpus, limit=2)

    assert searcher.calls == [("secret search prompt", "synthetic objective", 2)]
    assert report["provider_invocations"] == report["query_count"] == 1
    row = report["query_results"][0]
    assert row["accepted_hits"] == 2
    assert row["rejected_hits"] == 3
    assert row["truncated"] is True
    assert row["target_domain_matches"] == 1
    assert row["expected_url_matches"] == 1
    assert row["expected_url_label_count"] == 2
    assert report["operator_semantics"] == "unknown"
    assert report["pagination_supported"] is False
    assert report["duplicate_rate"] == "unavailable_after_adapter_deduplication"
    assert report["raw_queries_or_results_persisted"] is False
    serialized = str(report)
    assert "secret search prompt" not in serialized
    assert "private snippet" not in serialized
    assert "https://example.org/a" not in serialized


@pytest.mark.asyncio
async def test_measure_marks_ground_truth_absent_and_redacts_provider_failures():
    searcher = FixtureSearch(error=RuntimeError("secret provider response"))
    valid_corpus = (
        {"id": "one", "query": "public query", "objective": "objective", "expected_urls": ()},
    )

    report = await measure(searcher, corpus=valid_corpus)

    row = report["query_results"][0]
    assert report["status"] == "partial"
    assert row["status"] == "failed"
    assert row["failure_type"] == "RuntimeError"
    assert row["expected_url_matches"] is None
    assert "secret provider response" not in str(report)


@pytest.mark.asyncio
async def test_measure_enforces_fixed_small_query_and_hit_bounds():
    searcher = FixtureSearch()
    corpus = tuple(
        {"id": str(index), "query": "q", "objective": "o"} for index in range(5)
    )
    with pytest.raises(ValueError, match="1–4"):
        await measure(searcher, corpus=corpus)
    with pytest.raises(ValueError, match="1–5"):
        await measure(searcher, limit=6)
    assert searcher.calls == []
