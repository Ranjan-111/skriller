"""Bounded current identity proof for one tenant-scoped owner review."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from pydantic import Field

from skriller.contracts import Contract
from skriller.db import ResearchRepository, WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import claim_evidence, claims, evidence
from skriller.qualification.identity import compare


class IdentityEvidenceView(Contract):
    id: UUID
    source_url: str
    source_platform: str
    collected_at: datetime
    expires_at: datetime | None
    excerpt: str = Field(max_length=4096)
    excerpt_truncated: bool


class IdentityFactView(Contract):
    claim_id: UUID
    field: str
    value: str
    evidence: list[IdentityEvidenceView] = Field(max_length=10)


class IdentitySubjectView(Contract):
    id: UUID
    display_name: str = Field(max_length=200)
    kind: str
    available: bool
    identity_facts: list[IdentityFactView] = Field(max_length=20)
    context_complete: bool


def subject_context(session, identifier):
    entity = ResearchRepository.get_entity(session, identifier)
    result: dict[str, Any] = {
        "id": identifier,
        "display_name": "Removed record",
        "kind": "other",
        "available": False,
        "identity_facts": [],
        "context_complete": False,
    }
    if entity is None or entity["attributes"].get("erased"):
        return result
    result.update(
        display_name=(entity["display_name"] or "Unnamed record")[:200],
        kind=entity["kind"],
        available=True,
        context_complete=True,
    )
    current = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    facts = (
        session.execute(
            sa.select(claims)
            .where(
                claims.c.workspace_id == scope(session),
                claims.c.entity_id == identifier,
                claims.c.status == "accepted",
                claims.c.mode == "observed",
                sa.or_(
                    claims.c.field.in_(["domain", "legal_name", "country"]),
                    claims.c.field.startswith("native_id."),
                ),
            )
            .order_by(claims.c.id)
            .limit(21)
        )
        .mappings()
        .all()
    )
    if len(facts) > 20:
        result["context_complete"] = False
    for claim in facts[:20]:
        if not isinstance(claim["value"], str) or len(claim["value"]) > 255:
            continue
        records = (
            session.execute(
                sa.select(evidence)
                .join(
                    claim_evidence,
                    sa.and_(
                        claim_evidence.c.workspace_id == evidence.c.workspace_id,
                        claim_evidence.c.evidence_id == evidence.c.id,
                    ),
                )
                .where(
                    claim_evidence.c.workspace_id == scope(session),
                    claim_evidence.c.claim_id == claim["id"],
                )
                .order_by(evidence.c.id)
                .limit(11)
            )
            .mappings()
            .all()
        )
        if not 1 <= len(records) <= 10 or any(
            not row["excerpt"]
            or not row["excerpt"].strip()
            or row["expires_at"] is not None
            and row["expires_at"] <= current
            for row in records
        ):
            continue
        citations: list[dict[str, Any]] = []
        for row in records:
            try:
                source_url = normalize_public_http_url(row["source_url"])
                if row["source_platform"] not in {"web", "github", "rss", "youtube"}:
                    raise ValueError("Account-backed context requires source access integration")
            except ValueError:
                result["context_complete"] = False
                citations = []
                break
            citations.append(
                {
                    "id": row["id"],
                    "source_url": source_url,
                    "source_platform": row["source_platform"],
                    "collected_at": row["collected_at"],
                    "expires_at": row["expires_at"],
                    "excerpt": row["excerpt"][:4096],
                    "excerpt_truncated": len(row["excerpt"]) > 4096,
                }
            )
        if citations:
            result["identity_facts"].append(
                {
                    "claim_id": claim["id"],
                    "field": claim["field"],
                    "value": claim["value"],
                    "evidence": citations,
                }
            )
    return result


def review_context(session, row):
    source = subject_context(session, row["source_id"])
    target = subject_context(session, row["target_id"])
    eligible, reason = False, "identity_unavailable"
    try:
        decision = compare(session, row["source_id"], row["target_id"])
        eligible, reason = decision.eligible, decision.reason
    except (LookupError, ValueError):
        pass
    try:
        require_owner(session)
        owner = True
    except WorkspaceAccessDenied:
        owner = False
    return {
        "source": source,
        "target": target,
        "eligible": eligible,
        "current_reason": reason,
        "can_review": owner,
    }
