"""Reviewed reversible identity groups; original claims are never reassigned."""

from dataclasses import dataclass
from typing import get_args
from urllib.parse import urlsplit

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from sqlalchemy.dialects.postgresql import UUID

from skriller.contracts import Source
from skriller.db.repositories import ResearchRepository, insert_row, require_owner, scope
from skriller.db.schema import claim_evidence, claims, evidence, scoped

identity_reviews = scoped(
    "identity_reviews",
    sa.Column("source_id", UUID(as_uuid=False), nullable=False),
    sa.Column("target_id", UUID(as_uuid=False), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("reason", sa.String(64), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("reviewed_by", sa.String(128)),
    constraints=(
        sa.CheckConstraint("state IN ('suggestion','linked','reversed')"),
        sa.CheckConstraint("source_id<>target_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"], ["entities.workspace_id", "entities.id"]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "target_id"], ["entities.workspace_id", "entities.id"]
        ),
    ),
)
identity_events = scoped(
    "identity_events",
    sa.Column("review_id", UUID(as_uuid=False), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("reason", sa.String(64), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "review_id"], ["identity_reviews.workspace_id", "identity_reviews.id"]
        ),
    ),
)


@dataclass(frozen=True)
class IdentityDecision:
    eligible: bool
    reason: str


def _facts(session, entity_id):
    rows = session.execute(
        sa.select(claims.c.field, claims.c.value)
        .join(
            claim_evidence,
            sa.and_(
                claims.c.workspace_id == claim_evidence.c.workspace_id,
                claims.c.id == claim_evidence.c.claim_id,
            ),
        )
        .join(
            evidence,
            sa.and_(
                evidence.c.workspace_id == claim_evidence.c.workspace_id,
                evidence.c.id == claim_evidence.c.evidence_id,
            ),
        )
        .where(
            claims.c.workspace_id == scope(session),
            claims.c.entity_id == entity_id,
            claims.c.status == "accepted",
            claims.c.mode == "observed",
            sa.or_(evidence.c.expires_at.is_(None), evidence.c.expires_at > sa.func.now()),
        )
        .limit(65)
    ).all()
    if len(rows) > 64:
        raise ValueError("Identity fact budget exceeded")
    facts: dict[str, set[str]] = {}
    for field, value in rows:
        if isinstance(value, str) and 0 < len(value) <= 255:
            if field not in {"domain", "legal_name", "country"} and field not in {
                f"native_id.{source}" for source in get_args(Source)
            }:
                continue
            normalized = (
                value.strip()
                if field.startswith("native_id.")
                else " ".join(value.split()).casefold()
            )
            if field == "domain":
                try:
                    parsed = urlsplit(
                        normalize_public_http_url(value if "://" in value else "https://" + value)
                    )
                except ValueError:
                    continue
                if parsed.username or parsed.password or not parsed.hostname or parsed.port:
                    continue
                normalized = parsed.hostname.casefold().removeprefix("www.")
            facts.setdefault(field, set()).add(normalized)
    return facts


def compare(session, source_id: str, target_id: str) -> IdentityDecision:
    if source_id == target_id:
        return IdentityDecision(False, "same_record")
    a = ResearchRepository.get_entity(session, source_id)
    b = ResearchRepository.get_entity(session, target_id)
    if a is None or b is None:
        raise LookupError("Entity unavailable in workspace")
    if a["kind"] != b["kind"]:
        return IdentityDecision(False, "kind_conflict")
    left, right = _facts(session, source_id), _facts(session, target_id)
    native = {key for key in left.keys() | right.keys() if key.startswith("native_id.")}
    for key in native:
        if key in left and key in right and (len(left[key]) != 1 or left[key] != right[key]):
            return IdentityDecision(False, "native_id_conflict")
    if any(
        key in left and key in right and len(left[key]) == 1 and left[key] == right[key]
        for key in native
    ):
        return IdentityDecision(True, "same_native_id")
    if a["kind"] == "company":
        fields = ("domain", "legal_name", "country")
        if all(
            key in left and key in right and len(left[key]) == 1 and left[key] == right[key]
            for key in fields
        ):
            return IdentityDecision(True, "domain_corroborated")
        if "domain" in left and "domain" in right and left["domain"].isdisjoint(right["domain"]):
            return IdentityDecision(False, "domain_conflict")
    return IdentityDecision(False, "insufficient_identity")


def _lock(session):
    require_owner(session)
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "identity:" + scope(session)},
    )


def _event(session, review, action, reason):
    insert_row(
        session,
        identity_events,
        review_id=review["id"],
        action=action,
        actor_id=session.info["actor_id"],
        reason=reason,
    )


def suggest(session, source_id, target_id):
    _lock(session)
    decision = compare(session, source_id, target_id)
    review = insert_row(
        session,
        identity_reviews,
        source_id=source_id,
        target_id=target_id,
        state="suggestion",
        reason=decision.reason,
        created_by=session.info["actor_id"],
    )
    _event(session, review, "suggested", decision.reason)
    return review


def review_link(session, review_id):
    _lock(session)
    review = (
        session.execute(
            sa.select(identity_reviews)
            .where(
                identity_reviews.c.workspace_id == scope(session),
                identity_reviews.c.id == review_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if review is None:
        raise LookupError("Identity review unavailable")
    if review["state"] != "suggestion":
        raise ValueError("Only a pending suggestion can be linked")
    decision = compare(session, review["source_id"], review["target_id"])
    if not decision.eligible:
        return {**review, "review_outcome": decision.reason}
    left = group_members(session, review["source_id"])
    right = group_members(session, review["target_id"])
    if set(left) & set(right):
        return {**review, "review_outcome": "already_linked"}
    if len(left) * len(right) > 100:
        return {**review, "review_outcome": "group_review_budget_exceeded"}
    for source in left:
        for target in right:
            related = compare(session, source, target)
            if related.reason in {"native_id_conflict", "kind_conflict", "domain_conflict"}:
                return {**review, "review_outcome": "group_identity_conflict"}
    session.execute(
        sa.update(identity_reviews)
        .where(
            identity_reviews.c.workspace_id == scope(session), identity_reviews.c.id == review_id
        )
        .values(state="linked", reason=decision.reason, reviewed_by=session.info["actor_id"])
    )
    _event(session, review, "linked", decision.reason)
    return {**review, "state": "linked", "reason": decision.reason}


def reverse_link(session, review_id):
    _lock(session)
    review = (
        session.execute(
            sa.select(identity_reviews)
            .where(
                identity_reviews.c.workspace_id == scope(session),
                identity_reviews.c.id == review_id,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if review is None:
        raise LookupError("Identity review unavailable")
    if review["state"] == "reversed":
        return dict(review)
    if review["state"] != "linked":
        raise ValueError("Only a linked identity can be reversed")
    session.execute(
        sa.update(identity_reviews)
        .where(
            identity_reviews.c.workspace_id == scope(session), identity_reviews.c.id == review_id
        )
        .values(state="reversed", reviewed_by=session.info["actor_id"])
    )
    _event(session, review, "reversed", "owner_reversed")
    return {**review, "state": "reversed"}


def group_members(session, entity_id):
    if ResearchRepository.get_entity(session, entity_id) is None:
        raise LookupError("Entity unavailable")
    links = session.execute(
        sa.select(identity_reviews.c.source_id, identity_reviews.c.target_id)
        .where(
            identity_reviews.c.workspace_id == scope(session), identity_reviews.c.state == "linked"
        )
        .limit(1001)
    ).all()
    if len(links) > 1000:
        raise ValueError("Identity traversal budget exceeded")
    members = {entity_id}
    changed = True
    while changed:
        changed = False
        for source, target in links:
            if (source in members or target in members) and not {source, target} <= members:
                members.update((source, target))
                changed = True
    return tuple(sorted(members))


def group_claims(session, entity_id):
    """Read projection retains each claim's original entity_id for reversal/trace."""
    members = group_members(session, entity_id)
    rows = (
        session.execute(
            sa.select(claims)
            .where(claims.c.workspace_id == scope(session), claims.c.entity_id.in_(members))
            .limit(1001)
        )
        .mappings()
        .all()
    )
    if len(rows) > 1000:
        raise ValueError("Identity claim projection budget exceeded")
    return [dict(row) for row in rows]
