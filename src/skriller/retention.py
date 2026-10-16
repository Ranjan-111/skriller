"""Source retention ceilings and tenant-leased, repeat-safe blob cleanup."""

from datetime import timedelta

import sqlalchemy as sa

from skriller.db.repositories import scope
from skriller.db.schema import evidence
from skriller.storage import BlobUnavailable, validate_key

SOURCE_TTL_SECONDS = {
    "linkedin": 7 * 86400,
    "reddit": 7 * 86400,
    "x": 7 * 86400,
    "instagram": 7 * 86400,
    "facebook": 7 * 86400,
    "rss": 7 * 86400,
    "web": 30 * 86400,
    "github": 30 * 86400,
    "youtube": 30 * 86400,
    "skriller_export": 3600,
}


def expiry_for(source, collected_at, requested=None):
    """Callers may shorten retention, never extend its configured ceiling."""
    if collected_at.tzinfo is None or requested is not None and requested.tzinfo is None:
        raise ValueError("Retention requires timezone-aware timestamps")
    ceiling = collected_at + timedelta(seconds=SOURCE_TTL_SECONDS.get(source, 7 * 86400))
    return min(ceiling, requested) if requested is not None else ceiling


def cleanup_expired(session, storage, *, limit=100):
    """Transaction-scoped workspace lease; clear pointers only after own delete.

    Failed deletion leaves the pointer intact for the next delivery. A crash
    after deletion but before commit safely retries the absent object. Evidence
    audit rows and claim links remain; excerpts are erased and cannot satisfy
    current citation checks. The task wrapper supplies a bounded worker timeout.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Retention batch limit must be 1–100")
    workspace = scope(session)
    leased = session.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"retention:{workspace}"},
    ).scalar_one()
    if not leased:
        return {"status": "leased", "removed": 0}
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    from skriller.analytics.service import purge_expired
    from skriller.db import WorkspaceAccessDenied
    from skriller.db.repositories import require_owner

    try:
        require_owner(session)
    except WorkspaceAccessDenied:
        pass
    else:
        purge_expired(session)
        session.execute(sa.text("SELECT expire_crm_oauth_consents()"))
    rows = (
        session.execute(
            sa.select(evidence)
            .where(
                evidence.c.workspace_id == workspace,
                evidence.c.expires_at <= now,
                sa.or_(evidence.c.object_key.is_not(None), evidence.c.excerpt.is_not(None)),
            )
            .order_by(evidence.c.expires_at, evidence.c.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .mappings()
        .all()
    )
    removed = 0
    for row in rows:
        if row["object_key"] is not None:
            validate_key(workspace, row["object_key"])
            try:
                storage.backend.delete(workspace, row["object_key"])
            except BlobUnavailable:
                pass  # Already removed in a prior delivery, after validating scope.
        session.execute(
            sa.update(evidence)
            .where(evidence.c.workspace_id == workspace, evidence.c.id == row["id"])
            .values(object_key=None, excerpt=None)
        )
        removed += 1
    return {"status": "completed", "removed": removed}


def current_observations(session, entity_id, observations):
    """Persisted model excerpts are not current citations after source expiry."""
    from skriller.db.schema import claim_evidence, claims

    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    if len(observations) > 60:
        raise ValueError("Observation count exceeds retained view bounds")
    current = []
    for item in observations:
        claim = (
            session.execute(
                sa.select(claims).where(
                    claims.c.workspace_id == scope(session), claims.c.id == item["claim_id"]
                )
            )
            .mappings()
            .one_or_none()
        )
        rows = (
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
                    claim_evidence.c.claim_id == item["claim_id"],
                )
                .limit(11)
            )
            .mappings()
            .all()
        )
        if (
            claim is None
            or claim["entity_id"] != entity_id
            or claim["field"] != item["field"]
            or claim["value"] != item["value"]
            or not 1 <= len(rows) <= 10
            or any(
                not row["excerpt"]
                or item["quote"] not in row["excerpt"]
                or row["expires_at"] is not None
                and row["expires_at"] <= now
                for row in rows
            )
        ):
            continue
        current.append(
            {
                **item,
                "status": claim["status"],
                "evidence_ids": sorted(row["id"] for row in rows),
            }
        )
    return current, len(observations) - len(current)
