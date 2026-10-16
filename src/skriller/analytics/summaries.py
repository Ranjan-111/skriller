"""Private extractive summaries through the existing copied answer node and ledger."""

import json
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.reports import VerifiedReport
from skriller.db import JobRepository
from skriller.extraction.cleanup import ContextChunk, PreparedContext
from skriller.extraction.graph import extract_saved
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.control import permit_call
from skriller.research.reports import ReportObservation, ReportSelection, ResearchReport


def _unknown(reason):
    return ResearchReport("unknown", (), (reason,), False, 0, 0)


def _current(database, store, context, verified):
    if context.actor_id != verified.owner_id or str(context.workspace_id) != verified.workspace_id:
        raise AnalyticsUnavailable()
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        store.recheck(session, verified.report.grant_id, verified.grant_version)
        job = JobRepository.get(session, str(context.job_id))
        if (
            job is None
            or job["created_by"] != context.actor_id
            or not permit_call(session, str(context.job_id))
        ):
            raise AnalyticsUnavailable()


async def summarize_report(
    database, store, context, verified: VerifiedReport, *, operation_key, model=None
):
    """Select up to five exact metric lines; no private evidence is shared/persisted.

    The existing graph/parser and actual job budgets are reused. Default transport
    is explicitly local Ollama. This helper requires a trusted verified report and
    an active owner-created job; browser integration is a separate surface.
    """
    report = verified.report
    if not report.response_sha256 or not report.summary:
        return _unknown("analytics_report_data_unavailable")
    _current(database, store, context, verified)
    records = [
        {
            "evidence_id": str(uuid5(NAMESPACE_URL, report.response_sha256 + ":" + str(index))),
            "quote": quote,
        }
        for index, quote in enumerate(report.summary[:5])
    ]
    payload = json.dumps(records)
    if len(payload.encode()) > 1500:
        return _unknown("analytics_summary_budget_exhausted")
    prepared = PreparedContext(
        report.source_url,
        report.response_sha256,
        "Owner analytics metrics",
        (ContextChunk("owner-metrics", payload, 0),),
        (),
        len(payload.encode()),
        1,
        0,
        0,
        0,
        (),
        coverage_scope="explicit_owner_metric_rows",
    )
    result = await extract_saved(
        database,
        context,
        prepared,
        "Select useful supplied owner metric statements. Return only exact complete quote strings and their supplied evidence_id; do not infer trends, revenue, missing days or other owners.",
        ReportSelection,
        operation_key=operation_key,
        model=model or LocalStructuredModel(),
        max_chunks=1,
    )
    _current(database, store, context, verified)
    if result.failure or len(result.answers) != 1:
        return _unknown(result.failure.code if result.failure else "analytics_summary_unknown")
    selected = ReportSelection.model_validate(result.answers[0].data)
    if len(selected.evidence_ids) != len(selected.quotes) or len(set(selected.evidence_ids)) != len(
        selected.evidence_ids
    ):
        return _unknown("citation_invalid")
    supplied = {item["evidence_id"]: item["quote"] for item in records}
    if any(
        supplied.get(identifier) != quote
        for identifier, quote in zip(selected.evidence_ids, selected.quotes, strict=True)
    ):
        return _unknown("citation_invalid")
    observations = tuple(
        ReportObservation(
            identifier,
            quote,
            report.source_url,
            "youtube_analytics",
            report.collected_at.isoformat(),
            sha256(quote.encode()).hexdigest(),
            report.response_sha256,
            qualification="provider_reported_owner_metrics",
            content_hash_status="canonical_response_hash_not_original_transport_bytes",
        )
        for identifier, quote in zip(selected.evidence_ids, selected.quotes, strict=True)
    )
    return ResearchReport(
        "answered" if observations else "unknown",
        observations,
        (
            "provider_available_days_only",
            "citations_are_response_hash_bound_not_saved_evidence_ids",
            "unsupported_metrics_remain_unavailable",
        ),
        False,
        len(records),
        len(observations),
    )
