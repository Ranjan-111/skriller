"""Strict copied-parser output validation against tenant-owned saved evidence.

Literal occurrence is necessary, never sufficient for subject attribution.
Accepted observations additionally require a trusted same-container semantic
mapping from the copied adaptive selector validation. Model citations alone do
not establish an identity or relationship.
"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from scrapegraphai.utils.output_parser import get_pydantic_output_parser

from skriller.db import ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import evidence
from skriller.extraction.adaptive import ValidatedField


@dataclass(frozen=True)
class Citation:
    evidence_ids: tuple[UUID, ...]
    quote: str
    mode: Literal["observed", "inferred"] = "observed"

    def __post_init__(self):
        if not 1 <= len(self.evidence_ids) <= 10 or not all(
            isinstance(v, UUID) for v in self.evidence_ids
        ):
            raise ValueError("Citation requires 1–10 evidence UUIDs")
        if not self.quote or len(self.quote) > 4096 or self.mode not in {"observed", "inferred"}:
            raise ValueError("Citation requires bounded source quote and typed mode")


@dataclass(frozen=True)
class FieldBinding:
    """Trusted connector output; never accepted from model JSON or API input."""

    entity_id: UUID
    field: str
    semantic: ValidatedField


@dataclass(frozen=True)
class CheckedField:
    value: Any
    mode: str
    status: str
    reason: str
    evidence_ids: tuple[str, ...] = ()
    claim_id: str | None = None


@dataclass(frozen=True)
class CheckedExtraction:
    fields: dict[str, CheckedField]
    schema_valid: bool


CONTACT_FIELDS = frozenset(
    {"email", "private_email", "work_email", "personal_email", "phone", "phone_number"}
)


def literal_value(value: Any, quote: str) -> bool:
    """Whole literal token matching; 25 is not 250/-25/25.5, nor a name prefix."""
    if isinstance(value, bool):
        token = "true" if value else "false"
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return False
        token = str(value)
        return re.search(r"(?<![\w.,+\-])" + re.escape(token) + r"(?![\w.,])", quote) is not None
    elif isinstance(value, str) and value:
        token = value
    else:
        return False
    boundary = r"[\w@.!#$%&'*+/=?^`{|}~\-]" if "@" in token else r"\w"
    return (
        re.search(r"(?<!" + boundary + ")" + re.escape(token) + r"(?!" + boundary + ")", quote)
        is not None
    )


def _unavailable(reason):
    return CheckedField(None, "unavailable", "unverified", reason)


def validate_extraction(
    session,
    entity_id: UUID,
    answer: dict | str,
    schema: type[BaseModel],
    *,
    citations: dict[str, Citation],
    bindings: dict[str, FieldBinding] | None = None,
    persist: bool = False,
) -> CheckedExtraction:
    """Require strict types, saved quote/value, and trusted identity before acceptance.

    Inference is retained only as unverified and never accepted for contacts.
    Unknown/rejected values become null with reasons; persisted unavailable claims
    carry no invalid/cross-tenant evidence references. Reasons stay in this typed
    result for the product's audit/report writer.
    """
    if (
        not isinstance(entity_id, UUID)
        or not isinstance(schema, type)
        or not issubclass(schema, BaseModel)
    ):
        raise TypeError("Typed entity identity and Pydantic v2 schema required")
    if ResearchRepository.get_entity(session, str(entity_id)) is None:
        raise LookupError("Entity unavailable")
    if len(schema.model_fields) > 30 or len(citations) > 30:
        raise ValueError("Extraction field count exceeds supported bounds")
    bindings = bindings or {}
    try:
        if isinstance(answer, str):
            if len(answer.encode()) > 65536:
                raise ValueError("Answer exceeds supported bounds")
            answer = get_pydantic_output_parser(schema).parse(answer)
        parsed = schema.model_validate(answer, strict=True).model_dump(mode="json")
        # A caller's permissive schema must not allow undeclared model fields.
        if set(parsed) - schema.model_fields.keys() or set(answer) - schema.model_fields.keys():
            raise ValueError("Unexpected extraction fields")
    except (ValidationError, ValueError, TypeError):
        return CheckedExtraction(
            {name: _unavailable("schema_invalid") for name in schema.model_fields}, False
        )
    fields = {}
    now = datetime.now(UTC)
    for name, value in parsed.items():
        citation = citations.get(name)
        if value is None:
            checked = _unavailable("not_stated")
        elif citation is None:
            checked = _unavailable("evidence_missing")
        else:
            rows: list[Any] = []
            for identifier in citation.evidence_ids:
                row = (
                    session.execute(
                        sa.select(evidence)
                        .where(
                            evidence.c.workspace_id == scope(session),
                            evidence.c.id == str(identifier),
                        )
                        .with_for_update(read=True, key_share=True)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or row["expires_at"] is not None and row["expires_at"] <= now:
                    rows = []
                    break
                rows.append(row)
            if not rows:
                checked = _unavailable("evidence_unavailable")
            elif any(not row["excerpt"] or citation.quote not in row["excerpt"] for row in rows):
                checked = _unavailable("quote_missing")
            elif citation.mode == "inferred":
                checked = (
                    _unavailable("contact_inference_rejected")
                    if name in CONTACT_FIELDS
                    else CheckedField(
                        value,
                        "inferred",
                        "unverified",
                        "inference_unverified",
                        tuple(str(v) for v in citation.evidence_ids),
                    )
                )
            elif not literal_value(value, citation.quote):
                checked = _unavailable("value_missing")
            else:
                binding = bindings.get(name)
                if binding is None:
                    checked = CheckedField(
                        value,
                        "observed",
                        "unverified",
                        "subject_relationship_unverified",
                        tuple(str(v) for v in citation.evidence_ids),
                    )
                elif (
                    binding.entity_id != entity_id
                    or binding.field != name
                    or binding.semantic.status != "accepted"
                    or not binding.semantic.locator
                    or not binding.semantic.quote
                    or binding.semantic.quote not in citation.quote
                    or not literal_value(value, binding.semantic.quote)
                    or any(row["content_hash"] != binding.semantic.source_sha256 for row in rows)
                ):
                    checked = _unavailable("subject_relationship_mismatch")
                else:
                    checked = CheckedField(
                        value,
                        "observed",
                        "accepted",
                        "literal_and_semantic_evidence",
                        tuple(str(v) for v in citation.evidence_ids),
                    )
        if persist:
            claim = ResearchRepository.claim(
                session,
                str(entity_id),
                name,
                checked.value,
                mode=checked.mode,
                status=checked.status,
                evidence_ids=list(checked.evidence_ids),
            )
            checked = CheckedField(
                checked.value,
                checked.mode,
                claim["status"],
                checked.reason,
                checked.evidence_ids,
                claim["id"],
            )
        fields[name] = checked
    return CheckedExtraction(fields, True)
