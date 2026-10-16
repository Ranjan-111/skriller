"""Owner-authorized erasure, replay fences and opaque rediscovery suppression."""

import hashlib
import json
import re
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, insert

from skriller.connectors.candidates import canonical_url
from skriller.db import ResearchRepository
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import (
    claim_evidence,
    claims,
    entities,
    evidence,
    followup_reports,
    jobs,
    metadata,
)
from skriller.db.schema import (
    entity_links as relationships,
)
from skriller.db.schema import (
    qualifications as criteria_evaluations,
)
from skriller.jobs.control import cancel
from skriller.qualification.identity import group_members, identity_events, identity_reviews
from skriller.storage import BlobUnavailable, validate_key

journal = sa.Table(
    "erasure_journal",
    metadata,
    sa.Column(
        "workspace_id", UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
    ),
    sa.Column("entity_id", UUID(as_uuid=False), primary_key=True),
    sa.Column("request_key", sa.String(100), nullable=False),
    sa.Column("url_hashes", sa.JSON, nullable=False),
    sa.Column("native_hashes", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("created_by", sa.String(128), nullable=False),
)


def url_hash(workspace, url):
    return hashlib.sha256((workspace + "\0" + canonical_url(url)).encode()).hexdigest()


def native_hash(workspace, reference):
    if (
        not isinstance(reference, dict)
        or set(reference) != {"namespace", "id"}
        or not isinstance(reference["namespace"], str)
        or not re.fullmatch(r"[a-z0-9_]{1,64}", reference["namespace"])
        or not isinstance(reference["id"], str)
        or not 1 <= len(reference["id"]) <= 4096
    ):
        raise ValueError("Bounded native source identifier required")
    return hashlib.sha256(
        json.dumps([workspace, "native_source_v1", reference], sort_keys=True).encode()
    ).hexdigest()


def privacy_lock(session):
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"privacy:{scope(session)}"},
    )


def suppressed(session, *, entity_id=None, url=None, native_id=None):
    rows = (
        session.execute(
            sa.select(journal).where(journal.c.workspace_id == scope(session)).limit(1001)
        )
        .mappings()
        .all()
    )
    if len(rows) > 1000:
        raise ValueError("Suppression lookup exceeds pilot bound")
    digest = url_hash(scope(session), url) if url else None
    native_digest = native_hash(scope(session), native_id) if native_id is not None else None
    return any(
        row["entity_id"] == entity_id
        or (digest is not None and digest in row["url_hashes"])
        or (native_digest is not None and native_digest in row["native_hashes"])
        for row in rows
    )


def erase(session, storage, entity_id, *, request_key):
    require_owner(session)
    if not request_key or len(request_key) > 100:
        raise ValueError("Bounded erasure idempotency key required")
    existing = (
        session.execute(
            sa.select(journal).where(
                journal.c.workspace_id == scope(session), journal.c.entity_id == entity_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        return {"status": "erased", "entity_ids": [entity_id]}
    entity = ResearchRepository.get_entity(session, entity_id)
    if entity is None:
        raise LookupError("Entity unavailable")
    members = set(group_members(session, entity_id, current_only=False))
    if len(members) > 100:
        raise ValueError("Erasure identity group exceeds pilot bound")
    # Fence jobs first, preserving the worker's job-before-entity lock order.
    # Discovery does not know its URLs until IO returns. Owner erasure therefore
    # cancels active workspace research before fencing writes and derivative copies.
    active = (
        session.execute(
            sa.select(jobs.c.id).where(
                jobs.c.workspace_id == scope(session),
                jobs.c.state.in_(["queued", "running", "paused", "waiting_for_connection"]),
            )
        )
        .scalars()
        .all()
    )
    for job_id in sorted(active):
        cancel(session, job_id)
    privacy_lock(session)
    # Identity writers share the privacy fence. Reload the group after IO/job
    # fencing so a link committed while cancellation ran cannot escape erasure.
    members = set(group_members(session, entity_id, current_only=False))
    if len(members) > 100:
        raise ValueError("Erasure identity group exceeds pilot bound")
    rows = (
        session.execute(
            sa.select(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id.in_(members))
            .order_by(entities.c.id)
            .with_for_update()
        )
        .mappings()
        .all()
    )
    linked = (
        session.execute(
            sa.select(claim_evidence.c.evidence_id)
            .join(
                claims,
                sa.and_(
                    claims.c.workspace_id == claim_evidence.c.workspace_id,
                    claims.c.id == claim_evidence.c.claim_id,
                ),
            )
            .where(claims.c.workspace_id == scope(session), claims.c.entity_id.in_(members))
        )
        .scalars()
        .all()
    )
    bodies = set(linked)
    hashes = set()
    native_hashes = set()
    for row in rows:
        attrs = row["attributes"]
        if attrs.get("_source_native_id"):
            native_hashes.add(native_hash(scope(session), attrs["_source_native_id"]))
        if attrs.get("url"):
            try:
                hashes.add(url_hash(scope(session), attrs["url"]))
            except ValueError:
                pass
        for key in ("_collection_body_evidence_id", "_collection_metadata_evidence_id"):
            if attrs.get(key):
                bodies.add(attrs[key])
    records = (
        session.execute(
            sa.select(evidence).where(
                evidence.c.workspace_id == scope(session), evidence.c.id.in_(bodies)
            )
        )
        .mappings()
        .all()
    )
    for record in records:
        try:
            hashes.add(url_hash(scope(session), record["source_url"]))
        except ValueError:
            pass
    # Remove exact-URL rediscoveries that committed before this privacy fence.
    duplicates = (
        session.execute(
            sa.select(entities).where(
                entities.c.workspace_id == scope(session),
                entities.c.attributes["url"].as_string().is_not(None),
            )
        )
        .mappings()
        .all()
    )
    for duplicate in duplicates:
        try:
            reference = duplicate["attributes"].get("_source_native_id")
            if (
                url_hash(scope(session), duplicate["attributes"]["url"]) in hashes
                or reference is not None
                and native_hash(scope(session), reference) in native_hashes
            ):
                members.add(duplicate["id"])
                for key in ("_collection_body_evidence_id", "_collection_metadata_evidence_id"):
                    if duplicate["attributes"].get(key):
                        bodies.add(duplicate["attributes"][key])
        except ValueError:
            continue
    linked = (
        session.execute(
            sa.select(claim_evidence.c.evidence_id)
            .join(
                claims,
                sa.and_(
                    claims.c.workspace_id == claim_evidence.c.workspace_id,
                    claims.c.id == claim_evidence.c.claim_id,
                ),
            )
            .where(claims.c.workspace_id == scope(session), claims.c.entity_id.in_(members))
        )
        .scalars()
        .all()
    )
    bodies.update(linked)
    for member in members:
        session.execute(
            insert(journal)
            .values(
                workspace_id=scope(session),
                entity_id=member,
                request_key=request_key,
                url_hashes=sorted(hashes),
                native_hashes=sorted(native_hashes),
                created_by=session.info["actor_id"],
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "entity_id"])
        )
    purge(session, storage, members, bodies)
    return {"status": "erased", "entity_ids": sorted(members)}


def purge(session, storage, members, bodies):
    """Invalidate broad workspace derivatives so erased bytes cannot survive copies."""
    from skriller.lists import list_snapshots
    from skriller.qualification.contacts import role_history

    workspace = scope(session)
    request_key = session.execute(
        sa.select(journal.c.request_key)
        .where(journal.c.workspace_id == workspace, journal.c.entity_id.in_(members))
        .limit(1)
    ).scalar_one()
    session.execute(
        sa.text("SELECT set_config('app.erasure_request_key',:key,true)"), {"key": request_key}
    )
    cache_rows = (
        session.execute(
            sa.select(entities.c.attributes).where(
                entities.c.workspace_id == workspace,
                entities.c.canonical_key.startswith("response-cache:"),
            )
        )
        .scalars()
        .all()
    )
    bodies = set(bodies) | {row["evidence_id"] for row in cache_rows if row.get("evidence_id")}
    # Exports can copy target values; cached responses can contain alternate URLs.
    derivatives = (
        session.execute(
            sa.select(evidence).where(
                evidence.c.workspace_id == workspace,
                sa.or_(evidence.c.id.in_(bodies), evidence.c.source_platform == "skriller_export"),
            )
        )
        .mappings()
        .all()
    )
    for row in derivatives:
        if row["object_key"]:
            validate_key(workspace, row["object_key"])
            try:
                storage.backend.delete(workspace, row["object_key"])
            except BlobUnavailable:
                pass
        session.execute(
            sa.update(evidence)
            .where(evidence.c.workspace_id == workspace, evidence.c.id == row["id"])
            .values(
                object_key=None,
                excerpt=None,
                content_hash=None,
                source_url="https://skriller.invalid/erased",
                expires_at=datetime.now(UTC),
            )
        )
    from skriller.automation_lifecycle import quarantine
    from skriller.webhooks.tables import deliveries as webhook_deliveries

    quarantine(session, "data_erasure")
    session.execute(
        sa.delete(webhook_deliveries).where(webhook_deliveries.c.workspace_id == workspace)
    )
    session.execute(sa.delete(list_snapshots).where(list_snapshots.c.workspace_id == workspace))
    session.execute(
        sa.update(followup_reports)
        .where(
            followup_reports.c.workspace_id == workspace,
            followup_reports.c.entity_id.in_(members),
        )
        .values(
            question="[erased]",
            evidence_ids=[],
            citation_hashes={},
            unknowns=["entity_erased"],
            status="unknown",
        )
    )
    session.execute(
        sa.update(entities)
        .where(
            entities.c.workspace_id == workspace,
            entities.c.canonical_key.startswith("response-cache:"),
        )
        .values(attributes={"erased": True}, canonical_key=None, display_name=None)
    )
    session.execute(
        sa.delete(criteria_evaluations).where(
            criteria_evaluations.c.workspace_id == workspace,
            criteria_evaluations.c.entity_id.in_(members),
        )
    )
    claim_ids = (
        session.execute(
            sa.select(claims.c.id).where(
                claims.c.workspace_id == workspace, claims.c.entity_id.in_(members)
            )
        )
        .scalars()
        .all()
    )
    session.execute(
        sa.delete(criteria_evaluations).where(
            criteria_evaluations.c.workspace_id == workspace,
            criteria_evaluations.c.claim_id.in_(claim_ids),
        )
    )
    session.execute(
        sa.delete(role_history).where(
            role_history.c.workspace_id == workspace,
            sa.or_(
                role_history.c.previous_id.in_(claim_ids),
                role_history.c.replacement_id.in_(claim_ids),
                role_history.c.previous_date_id.in_(claim_ids),
                role_history.c.replacement_date_id.in_(claim_ids),
            ),
        )
    )
    session.execute(
        sa.delete(claim_evidence).where(
            claim_evidence.c.workspace_id == workspace, claim_evidence.c.claim_id.in_(claim_ids)
        )
    )
    session.execute(
        sa.delete(claims).where(claims.c.workspace_id == workspace, claims.c.id.in_(claim_ids))
    )
    review_ids = (
        session.execute(
            sa.select(identity_reviews.c.id).where(
                identity_reviews.c.workspace_id == workspace,
                sa.or_(
                    identity_reviews.c.source_id.in_(members),
                    identity_reviews.c.target_id.in_(members),
                ),
            )
        )
        .scalars()
        .all()
    )
    session.execute(
        sa.delete(identity_events).where(
            identity_events.c.workspace_id == workspace, identity_events.c.review_id.in_(review_ids)
        )
    )
    session.execute(
        sa.delete(identity_reviews).where(
            identity_reviews.c.workspace_id == workspace, identity_reviews.c.id.in_(review_ids)
        )
    )
    session.execute(
        sa.delete(relationships).where(
            relationships.c.workspace_id == workspace,
            sa.or_(relationships.c.source_id.in_(members), relationships.c.target_id.in_(members)),
        )
    )
    session.execute(
        sa.update(entities)
        .where(entities.c.workspace_id == workspace, entities.c.id.in_(members))
        .values(attributes={"erased": True}, display_name=None, canonical_key=None, kind="other")
    )
    session.execute(sa.text("SELECT set_config('app.erasure_request_key','',true)"))


def replay_erasures(session, storage):
    """Restore must import the newest journal before exposing restored data."""
    require_owner(session)
    privacy_lock(session)
    rows = (
        session.execute(sa.select(journal).where(journal.c.workspace_id == scope(session)))
        .mappings()
        .all()
    )
    markers = {row["entity_id"] for row in rows}
    hashes = {value for row in rows for value in row["url_hashes"]}
    native_hashes = {value for row in rows for value in row["native_hashes"]}
    if not rows:
        return 0
    candidates = (
        session.execute(sa.select(entities).where(entities.c.workspace_id == scope(session)))
        .mappings()
        .all()
    )
    targets = set(markers)
    bodies = set()
    for candidate in candidates:
        attrs = candidate["attributes"]
        match = candidate["id"] in markers
        if attrs.get("_source_native_id"):
            match = (
                match or native_hash(scope(session), attrs["_source_native_id"]) in native_hashes
            )
        if attrs.get("url"):
            try:
                match = match or url_hash(scope(session), attrs["url"]) in hashes
            except ValueError:
                pass
        if match:
            targets.add(candidate["id"])
            for key in ("_collection_body_evidence_id", "_collection_metadata_evidence_id"):
                if attrs.get(key):
                    bodies.add(attrs[key])
    linked = (
        session.execute(
            sa.select(claim_evidence.c.evidence_id)
            .join(
                claims,
                sa.and_(
                    claims.c.workspace_id == claim_evidence.c.workspace_id,
                    claims.c.id == claim_evidence.c.claim_id,
                ),
            )
            .where(claims.c.workspace_id == scope(session), claims.c.entity_id.in_(targets))
        )
        .scalars()
        .all()
    )
    bodies.update(linked)
    purge(session, storage, targets, bodies)
    return len(targets)
