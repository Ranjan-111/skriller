"""Explicit owner review of original subject/date evidence; never automatic acceptance."""

import json
from datetime import UTC, datetime
from hashlib import sha256

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url

from skriller.db import ResearchRepository
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import claims, entities
from skriller.erasure import privacy_lock
from skriller.qualification.contacts import DatedRole, _dated, record_role_refresh, role_projection


def review_context(session, entity_id: str, previous: DatedRole, replacement: DatedRole):
    entity = ResearchRepository.get_entity(session, entity_id)
    if entity is None or entity["attributes"].get("erased"):
        raise LookupError("Role review unavailable")
    if entity["kind"] != "person":
        raise ValueError("Employment chronology requires the original person record")
    now = datetime.now(UTC)
    old = _dated(session, previous, now, reviewed=False)
    new = _dated(session, replacement, now, reviewed=False)
    if old is None or new is None:
        raise ValueError("Role review requires current literal role/date evidence")
    if (
        old[0]["entity_id"] != entity_id
        or new[0]["entity_id"] != entity_id
        or old[0]["field"] != new[0]["field"]
        or old[0]["value"] == new[0]["value"]
        or new[1] <= old[1]
    ):
        raise ValueError("Role review does not describe a chronological same-subject change")
    for row in (old[0], new[0]):
        normalize_public_http_url(row["source_url"])
        if row["collected_at"] > now or len(row["excerpt"]) > 4096 or len(row["value"]) > 512:
            raise ValueError("Role review requires bounded current source observations")
    result = {
        "entity_id": entity_id,
        "subject_name": entity["display_name"],
        "previous": {
            **vars(previous),
            "role": old[0]["value"],
            "effective_date": old[1],
            "excerpt": old[0]["excerpt"][:4096],
            "source_url": old[0]["source_url"],
        },
        "replacement": {
            **vars(replacement),
            "role": new[0]["value"],
            "effective_date": new[1],
            "excerpt": new[0]["excerpt"][:4096],
            "source_url": new[0]["source_url"],
        },
        "review_origin": "workspace_owner",
        "requires_same_subject_confirmation": True,
    }
    result["review_hash"] = sha256(
        json.dumps(result, sort_keys=True, default=str).encode()
    ).hexdigest()
    return result


def approve_role_refresh(
    session,
    entity_id: str,
    previous: DatedRole,
    replacement: DatedRole,
    *,
    same_subject_confirmed: bool,
    expected_review_hash: str,
):
    """Atomic audited supersession; retain source values, dates and every original claim."""
    require_owner(session)
    if same_subject_confirmed is not True:
        raise ValueError("Owner must review both sources and confirm the same original subject")
    with session.begin_nested():
        privacy_lock(session)
        # Same entity lock as ordinary claim insertion; review cannot race a new conflict.
        session.execute(
            sa.select(entities.c.id)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .with_for_update()
        ).scalar_one_or_none()
        preview = review_context(session, entity_id, previous, replacement)
        if expected_review_hash != preview["review_hash"]:
            raise ValueError("Role review evidence changed; refresh the preview")
        identifiers = {
            previous.role_claim_id,
            previous.date_claim_id,
            replacement.role_claim_id,
            replacement.date_claim_id,
        }
        session.execute(
            sa.update(claims)
            .where(
                claims.c.workspace_id == scope(session),
                claims.c.entity_id == entity_id,
                claims.c.id.in_(identifiers),
            )
            .values(status="accepted")
        )
        outcome = record_role_refresh(
            session, previous, replacement, review_hash=expected_review_hash
        )
        if outcome != "superseded":
            raise ValueError("Role refresh could not be recorded")
        return {
            "entity_id": entity_id,
            "outcome": outcome,
            "review_origin": "workspace_owner",
            "roles": [
                {
                    **{name: row[name] for name in ("claim_id", "freshness", "event_at")},
                    "value": row["value"] if isinstance(row["value"], str) else None,
                }
                for row in role_projection(session, entity_id)
            ],
        }
