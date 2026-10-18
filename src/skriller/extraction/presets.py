"""Fixture-backed directory presets over the copied saved-content graph.

Every result remains a source-specific, unverified observation until the trusted
identity and qualification pipeline independently reviews it.
"""

import math
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from skriller.contracts import ExecutionContext
from skriller.extraction.cleanup import PreparedContext
from skriller.extraction.graph import SavedExtraction, extract_saved
from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.validation import literal_value
from skriller.settings import Settings

PresetId = Literal[
    "company",
    "team",
    "careers",
    "jobs",
    "pricing",
    "services",
    "contact",
    "directory",
    "industry_directory",
    "linkedin_profile",
    "linkedin_company",
    "linkedin_post",
]


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=40)
    value: str | int | float | bool
    # Large schema repetition bounds crash the installed Ollama grammar runner.
    # The response token cap is 512; retained source evidence remains full length.
    quote: str = Field(min_length=1, max_length=512)

    @field_validator("value")
    @classmethod
    def bounded_value(cls, value):
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("Claim value exceeds its bound")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Claim value must be finite")
        return value


class DirectoryAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The compact transport prompt can retain the full nested schema. Giving the
    # model field/value/quote keys avoids ambiguous untyped dictionary outputs.
    claims: list[ClaimDraft] = Field(max_length=60)


class DirectoryClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str
    value: str | int | float | bool
    quote: str
    evidence_ids: tuple[str, ...]
    source_url: str
    source_sha256: str
    observed_at: datetime
    status: Literal["source_specific_unverified"] = "source_specific_unverified"


class DirectoryPresetResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preset: PresetId
    source_url: str
    claims: tuple[DirectoryClaim, ...]
    rejected_claims: int
    coverage_complete: bool
    omitted_chunks: int
    failure_code: str | None


_FIELDS: dict[PresetId, tuple[str, ...]] = {
    # Dates are literal drafts for explicit owner review, never automatic acceptance.
    "linkedin_profile": ("person_name", "job_title", "location", "role_effective_date"),
    "linkedin_company": ("company_name", "description", "headquarters", "industry"),
    "linkedin_post": ("post_text", "post_published_date"),
    "company": ("company_name", "description", "headquarters", "employee_count", "industry"),
    "team": ("person_name", "job_title", "team_page_url"),
    # A page may state when a role was posted. This is retained as a literal
    # source observation; it does not assert that the role is still open.
    "careers": (
        "job_title",
        "location",
        "employment_type",
        "careers_url",
        "job_posted_date",
        "job_listing_status",
    ),
    "jobs": (
        "job_title",
        "location",
        "employment_type",
        "careers_url",
        "job_posted_date",
        "job_listing_status",
    ),
    # Keep the site's literal amount, currency, period, effective date and
    # availability as separate observations. In particular, do not parse
    # localized punctuation or convert currencies in this extraction layer.
    "pricing": (
        "product_name",
        "price",
        "currency",
        "billing_period",
        "price_effective_date",
        "price_availability",
    ),
    "services": ("service_name", "service_description", "customer_type", "service_area"),
    "contact": ("contact_page_url", "public_work_email", "business_phone"),
    "directory": (
        "company_name",
        "description",
        "headquarters",
        "employee_count",
        "industry",
        "service_name",
    ),
    "industry_directory": (
        "company_name",
        "description",
        "headquarters",
        "employee_count",
        "industry",
        "service_name",
    ),
}

_CLOSED_JOB_RE = re.compile(
    r"\b(expired|closed|position\s+filled|no\s+longer\s+accepting\s+applications)\b",
    re.IGNORECASE,
)
_CURRENT_JOB_STATUSES = {"open", "active", "current", "hiring", "accepting applications"}


def preset_fields(preset: PresetId) -> tuple[str, ...]:
    try:
        return _FIELDS[preset]
    except KeyError as exc:
        raise ValueError("Unsupported directory preset") from exc


def _verified_claims(
    prepared: PreparedContext, preset: PresetId, extraction: SavedExtraction
) -> tuple[tuple[DirectoryClaim, ...], int]:
    allowed = set(preset_fields(preset))
    evidence_by_id = {node.evidence_id: node for node in prepared.evidence}
    claims = []
    rejected = 0
    observed_at = datetime.now(UTC)
    source_indicates_closed_job = preset in {"careers", "jobs"} and any(
        _CLOSED_JOB_RE.search(node.quote) for node in prepared.evidence
    )
    for answer in extraction.answers:
        nodes = [evidence_by_id[key] for key in answer.evidence_ids if key in evidence_by_id]
        for raw in answer.data.get("claims", []):
            try:
                draft = ClaimDraft.model_validate(raw, strict=True)
            except Exception:  # noqa: BLE001 - model output is untrusted
                rejected += 1
                continue
            supports = [node for node in nodes if draft.quote in node.quote]
            if (
                draft.field not in allowed
                or not supports
                or not literal_value(draft.value, draft.quote)
                or (
                    source_indicates_closed_job
                    and draft.field == "job_listing_status"
                    and isinstance(draft.value, str)
                    and draft.value.strip().casefold() in _CURRENT_JOB_STATUSES
                )
            ):
                rejected += 1
                continue
            # Exact evidence quote is required, but matching the source does not
            # validate entity identity, freshness, or cross-source truth.
            claims.append(
                DirectoryClaim(
                    field=draft.field,
                    value=draft.value,
                    quote=draft.quote,
                    evidence_ids=tuple(node.evidence_id for node in supports),
                    source_url=prepared.source_url,
                    source_sha256=prepared.source_sha256,
                    observed_at=observed_at,
                )
            )
    return tuple(claims), rejected


async def extract_directory_page(
    database,
    context: ExecutionContext,
    prepared: PreparedContext,
    preset: PresetId,
    *,
    operation_key: str,
    model: LocalStructuredModel | None = None,
    settings: Settings | None = None,
    max_chunks: int = 8,
) -> DirectoryPresetResult:
    """Use the copied graph and shared model ledger for one already-fetched page."""
    fields = preset_fields(preset)
    instruction = (
        f"Extract explicitly stated fields: {', '.join(fields)}. "
        "Return claims [{field,value,quote}] with exact values and verbatim supporting quotes. "
        "Preserve spelling, punctuation, currency, billing period, dates and availability; "
        "do not convert currencies or normalize amounts/dates. "
        "Expired, closed, filled or no-longer-accepting jobs cannot be current/open/active/hiring. "
        "Omit unknowns and null values. Never infer contacts or merge other pages."
    )
    extraction = await extract_saved(
        database,
        context,
        prepared,
        instruction,
        DirectoryAnswer,
        operation_key=operation_key,
        model=model,
        settings=settings,
        max_chunks=max_chunks,
    )
    claims, rejected = _verified_claims(prepared, preset, extraction)
    return DirectoryPresetResult(
        preset=preset,
        source_url=prepared.source_url,
        claims=claims,
        rejected_claims=rejected,
        coverage_complete=extraction.coverage_complete,
        omitted_chunks=extraction.omitted_chunks,
        failure_code=extraction.failure.code if extraction.failure else None,
    )
