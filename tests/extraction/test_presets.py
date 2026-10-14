from datetime import UTC, datetime
from uuid import uuid4

import pytest

from skriller.contracts import ExecutionContext
from skriller.extraction.cleanup import ContextChunk, EvidenceNode, PreparedContext
from skriller.extraction.graph import ChunkAnswer, SavedExtraction
from skriller.extraction.presets import (
    DirectoryAnswer,
    _verified_claims,
    extract_directory_page,
    preset_fields,
)


def fixture_context():
    return ExecutionContext(
        workspace_id=uuid4(),
        job_id=uuid4(),
        actor_id="fixture",
        plan_revision=1,
        deadline=datetime.now(UTC),
        attempt_budget=1,
    )


def prepared_page():
    return PreparedContext(
        source_url="https://example.org/about",
        source_sha256="a" * 64,
        title="About",
        chunks=(ContextChunk("chunk-1", "Aurora Ledger is based in Bengaluru.", 7),),
        evidence=(
            EvidenceNode("fact-1", "/html/body/p", "Aurora Ledger is based in Bengaluru.", "text"),
        ),
        input_bytes=64,
        total_chunks=1,
        omitted_chunks=0,
        omitted_evidence_nodes=0,
        omitted_scripts=0,
        issues=(),
    )


def extraction(drafts):
    return SavedExtraction(
        source_url="https://example.org/about",
        source_sha256="a" * 64,
        answers=(
            ChunkAnswer(
                "chunk-1",
                {"claims": drafts},
                ("fact-1",),
                "local-model",
                "confirmed",
                30,
            ),
        ),
        coverage_complete=True,
        omitted_chunks=0,
        failure=None,
    )


def test_preset_registry_is_bounded_and_page_specific():
    assert "employee_count" in preset_fields("company")
    assert "job_title" in preset_fields("careers")
    assert "business_phone" in preset_fields("contact")
    with pytest.raises(ValueError, match="Unsupported"):
        preset_fields("unknown")


def test_results_keep_source_specific_status_and_reject_unsupported_or_ungrounded_claims():
    prepared = prepared_page()
    claims, rejected = _verified_claims(
        prepared,
        "company",
        extraction(
            [
                {
                    "field": "company_name",
                    "value": "Aurora Ledger",
                    "quote": "Aurora Ledger is based in Bengaluru.",
                },
                {
                    "field": "business_phone",
                    "value": "555-0100",
                    "quote": "Aurora Ledger is based in Bengaluru.",
                },
                {"field": "industry", "value": "Fintech", "quote": "Not in the source."},
                {"field": "headquarters", "value": "Bengaluru", "quote": "Bengaluru"},
            ]
        ),
    )
    assert len(claims) == 2 and rejected == 2
    assert all(claim.status == "source_specific_unverified" for claim in claims)
    assert claims[0].status == "source_specific_unverified"
    assert claims[0].source_url == prepared.source_url
    assert claims[0].evidence_ids == ("fact-1",)


@pytest.mark.asyncio
async def test_preset_calls_shared_saved_content_graph_and_returns_unverified_results(monkeypatch):
    from skriller.extraction import presets

    called = {}

    async def fake_extract(database, context, prepared, prompt, schema, **kwargs):
        called.update(schema=schema, prompt=prompt, kwargs=kwargs)
        return extraction(
            [
                {
                    "field": "careers_url",
                    "value": "https://example.org/jobs",
                    "quote": "Aurora Ledger is based in Bengaluru.",
                }
            ]
        )

    monkeypatch.setattr(presets, "extract_saved", fake_extract)
    result = await extract_directory_page(
        object(), fixture_context(), prepared_page(), "careers", operation_key="preset-test"
    )
    assert called["schema"] is DirectoryAnswer
    assert "careers_url" in called["prompt"] and called["kwargs"]["operation_key"] == "preset-test"
    assert result.claims == () and result.rejected_claims == 1
    assert result.coverage_complete and result.failure_code is None
