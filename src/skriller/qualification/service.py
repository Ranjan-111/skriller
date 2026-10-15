"""Authenticated tenant claim-to-fact adapter; no snippet qualification shortcut."""

from dataclasses import replace

import sqlalchemy as sa

from skriller.contracts import SearchPlan
from skriller.db import ResearchRepository, WorkspaceAccessDenied
from skriller.db.repositories import scope
from skriller.db.schema import claim_evidence, evidence
from skriller.qualification.contacts import role_projection
from skriller.qualification.criteria import Fact, Fit, qualify
from skriller.qualification.identity import group_claims


def load_facts(session, entity_id: str, *, now) -> tuple[Fact, ...]:
    """Read reviewed identity projection while preserving original claim ownership.

    Every linked evidence record must be visible, available and current. Oldest
    collection time controls freshness; collection never establishes event time.
    Persisted acceptance remains the upstream strict evidence validator's duty.
    """
    workspace = scope(session)
    rows = group_claims(session, entity_id)
    if len(rows) > 300:
        raise ValueError("Qualification claim collection exceeds pilot bounds")
    facts = []
    role_states = {}
    for identifier in {
        claim["entity_id"] for claim in rows if claim["field"] in {"current_role", "job_title"}
    }:
        role_states.update({row["claim_id"]: row for row in role_projection(session, identifier)})
    for claim in rows:
        temporal = role_states.get(claim["id"])
        if temporal is not None and temporal["freshness"] != "current":
            # Retain historical records in storage; they cannot satisfy current fit.
            continue
        if claim["mode"] != "observed" or type(claim["value"]) not in {str, int, float, bool}:
            continue
        linked = (
            session.execute(
                sa.select(claim_evidence.c.evidence_id)
                .where(
                    claim_evidence.c.workspace_id == workspace,
                    claim_evidence.c.claim_id == claim["id"],
                )
                .limit(11)
            )
            .scalars()
            .all()
        )
        if not linked or len(linked) > 10:
            continue
        records = (
            session.execute(
                sa.select(evidence).where(
                    evidence.c.workspace_id == workspace, evidence.c.id.in_(linked)
                )
            )
            .mappings()
            .all()
        )
        if len(records) != len(linked) or any(
            not record["excerpt"]
            or record["collected_at"] > now
            or (record["expires_at"] is not None and record["expires_at"] <= now)
            for record in records
        ):
            continue
        expirations = [
            record["expires_at"] for record in records if record["expires_at"] is not None
        ]
        try:
            fact = Fact(
                field=claim["field"],
                value=claim["value"],
                evidence_ids=tuple(sorted(linked)),
                observed_at=min(record["collected_at"] for record in records),
                event_at=temporal["event_at"] if temporal is not None else None,
                status="accepted" if claim["status"] == "accepted" else "unverified",
                expires_at=min(expirations) if expirations else None,
            )
        except ValueError:
            continue
        facts.append(fact)
    return tuple(facts)


def qualify_entity(session, plan: SearchPlan, entity_id: str) -> Fit:
    """Use database clock and verified tenant session; plan scope must agree."""
    if str(plan.workspace_id) != scope(session):
        raise WorkspaceAccessDenied("Qualification plan belongs to another workspace")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    entity = ResearchRepository.get_entity(session, entity_id)
    if entity is None or entity["attributes"].get("erased"):
        raise LookupError("Entity unavailable in workspace")
    fit = qualify(plan, load_facts(session, entity_id, now=now), now=now)
    resource = entity["attributes"].get("_source_resource_type")
    if resource in {"github_repository", "youtube_video"}:
        return replace(
            fit,
            status="excluded",
            limitations=fit.limitations
            + (
                "A video does not establish its creator's identity or lead qualification"
                if resource == "youtube_video"
                else "A repository is not a person or company lead",
            ),
        )
    expected_kinds = {
        "person": {"person"},
        "company": {"company"},
        "creator": {"person"},
        "discussion": {"post", "community"},
    }
    if entity["kind"] not in expected_kinds[plan.entity_type]:
        return replace(
            fit,
            status="near_match" if entity["kind"] == "other" else "excluded",
            limitations=fit.limitations
            + ("Requested entity type is not verified for this record",),
        )
    return fit
