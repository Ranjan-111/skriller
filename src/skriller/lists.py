"""Immutable saved-list revisions from scoped persisted plans and reviewed facts."""

from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from skriller.connectors.candidates import canonical_url
from skriller.contracts import SearchPlan
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import (
    ConversationRepository,
    ResearchRepository,
    insert_row,
    require_owner,
    scope,
)
from skriller.db.schema import claim_evidence, claims, evidence, scoped, suppressions
from skriller.extraction.validation import CONTACT_FIELDS
from skriller.qualification.contacts import check_contact
from skriller.qualification.identity import compare, group_claims, group_members
from skriller.qualification.service import load_facts, qualify_entity

saved_lists = scoped(
    "saved_lists",
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("plan_id", PGUUID(as_uuid=False), nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]),
    ),
)
list_snapshots = scoped(
    "list_snapshots",
    sa.Column("list_id", PGUUID(as_uuid=False), nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("plan_id", PGUUID(as_uuid=False), nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(128), nullable=False),
    constraints=(
        sa.ForeignKeyConstraint(
            ["workspace_id", "list_id"], ["saved_lists.workspace_id", "saved_lists.id"]
        ),
        sa.ForeignKeyConstraint(["workspace_id", "plan_id"], ["plans.workspace_id", "plans.id"]),
        sa.UniqueConstraint("workspace_id", "list_id", "revision"),
        sa.CheckConstraint("revision>0"),
    ),
)


def _plan(session, plan_id):
    row = ConversationRepository.get_plan(session, plan_id)
    if row is None:
        raise LookupError("Plan unavailable")
    plan = SearchPlan.model_validate(row["interpretation"])
    if (
        str(plan.workspace_id) != scope(session)
        or str(plan.conversation_id) != row["conversation_id"]
        or plan.revision != row["revision"]
    ):
        raise WorkspaceAccessDenied("Saved plan scope or revision mismatch")
    return plan


def _suppressed(session, entity_id, entries):
    from skriller.erasure import suppressed

    if suppressed(session, entity_id=entity_id):
        return True
    members = group_members(session, entity_id, current_only=False)
    for entry in entries:
        if entry["kind"] == "entity":
            if entry["key"] in members:
                return True
            try:
                UUID(entry["key"])
            except ValueError:
                continue
            if (
                ResearchRepository.get_entity(session, entry["key"]) is not None
                and compare(session, entity_id, entry["key"]).reason == "same_native_id"
            ):
                return True
    profile_keys = set()
    for entry in entries:
        if entry["kind"] == "profile":
            try:
                profile_keys.add(canonical_url(entry["key"]))
            except ValueError:
                continue
    if profile_keys:
        candidates = session.execute(
            sa.select(claims.c.entity_id, evidence.c.source_url)
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
                claims.c.status == "accepted",
                claims.c.mode == "observed",
            )
            .limit(301)
        ).all()
        if len(candidates) > 300:
            raise ValueError("Suppression identity lookup exceeds snapshot bounds")
        for target, source_url in candidates:
            try:
                matches = canonical_url(source_url) in profile_keys
            except ValueError:
                continue
            if matches and (
                target in members or compare(session, entity_id, target).reason == "same_native_id"
            ):
                return True
    # Only accepted observations belonging to this original/reviewed group may
    # associate a suppression profile/email/domain. A person's workplace domain
    # cannot suppress another person's identity or establish their email.
    rows = session.execute(
        sa.select(claims.c.field, claims.c.value, evidence.c.source_url)
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
            claims.c.entity_id.in_(members),
            claims.c.status == "accepted",
            claims.c.mode == "observed",
        )
        .limit(301)
    ).all()
    if len(rows) > 300:
        raise ValueError("Suppression evidence exceeds snapshot bounds")
    for entry in entries:
        for field, value, url in rows:
            if (
                entry["kind"] == "email"
                and field in {"work_email", "professional_email"}
                and isinstance(value, str)
                and value.casefold() == entry["key"].casefold()
            ):
                return True
            if (
                entry["kind"] == "domain"
                and field == "domain"
                and ResearchRepository.get_entity(session, entity_id)["kind"] == "company"
                and value == entry["key"]
            ):
                return True
            if entry["kind"] == "profile":
                try:
                    if canonical_url(url) == canonical_url(entry["key"]):
                        return True
                except ValueError:
                    continue
    return False


def _unresolved_suppressed_identity(session, entity_id, entries):
    targets = set()
    for entry in entries:
        if entry["kind"] == "entity":
            try:
                targets.add(str(UUID(entry["key"])))
            except ValueError:
                continue
    if not targets:
        return False
    rows = session.execute(
        sa.select(claims.c.entity_id, claims.c.field, claims.c.value)
        .where(
            claims.c.workspace_id == scope(session),
            claims.c.entity_id.in_(targets | {entity_id}),
            claims.c.mode == "observed",
            claims.c.field.like("native_id.%"),
        )
        .limit(301)
    ).all()
    if len(rows) > 300:
        raise ValueError("Suppression identity uncertainty exceeds snapshot bounds")
    candidate = {
        (field, value)
        for owner, field, value in rows
        if owner == entity_id and isinstance(value, str)
    }
    suppressed = {
        (field, value)
        for owner, field, value in rows
        if owner in targets and isinstance(value, str)
    }
    return bool(candidate & suppressed)


def create_list(session, name: str, plan_id: str, entity_ids: tuple[str, ...]):
    require_owner(session)
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("Bounded list name required")
    _plan(session, plan_id)
    row = insert_row(
        session,
        saved_lists,
        name=name.strip(),
        plan_id=plan_id,
        created_by=session.info["actor_id"],
    )
    refresh_list(session, row["id"], entity_ids, expected_revision=0)
    return row


def refresh_list(session, list_id: str, entity_ids: tuple[str, ...], *, expected_revision: int):
    require_owner(session)
    from skriller.erasure import privacy_lock

    privacy_lock(session)
    if (
        not isinstance(entity_ids, tuple)
        or len(entity_ids) > 100
        or len(set(entity_ids)) != len(entity_ids)
    ):
        raise ValueError("Refresh needs at most100 unique entity IDs")
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "saved-list:" + scope(session) + ":" + list_id},
    )
    header = (
        session.execute(
            sa.select(saved_lists).where(
                saved_lists.c.workspace_id == scope(session), saved_lists.c.id == list_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if header is None:
        raise LookupError("Saved list unavailable")
    plan = _plan(session, header["plan_id"])
    latest = session.execute(
        sa.select(sa.func.coalesce(sa.func.max(list_snapshots.c.revision), 0)).where(
            list_snapshots.c.workspace_id == scope(session), list_snapshots.c.list_id == list_id
        )
    ).scalar_one()
    if type(expected_revision) is not int or latest != expected_revision:
        raise ValueError("Refresh must reference latest immutable snapshot")
    entries = (
        session.execute(
            sa.select(suppressions).where(suppressions.c.workspace_id == scope(session)).limit(101)
        )
        .mappings()
        .all()
    )
    if len(entries) > 100:
        raise ValueError("Suppression collection exceeds snapshot bounds")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    members, omitted = [], []
    for identifier in entity_ids:
        entity = ResearchRepository.get_entity(session, identifier)
        if entity is None:
            raise LookupError("Snapshot entity unavailable")
        if entity["attributes"].get("erased") or _suppressed(session, identifier, entries):
            omitted.append({"entity_id": identifier, "reason": "suppressed"})
            continue
        unresolved = _unresolved_suppressed_identity(session, identifier, entries)
        fit = qualify_entity(session, plan, identifier)
        facts = load_facts(session, identifier, now=now)
        originals = group_claims(session, identifier)
        original_support: dict[str, set[str]] = {}
        if originals:
            for original_id, support_id in session.execute(
                sa.select(claim_evidence.c.claim_id, claim_evidence.c.evidence_id).where(
                    claim_evidence.c.workspace_id == scope(session),
                    claim_evidence.c.claim_id.in_([claim["id"] for claim in originals]),
                )
            ):
                original_support.setdefault(original_id, set()).add(support_id)
        if len(facts) > 30:
            raise ValueError("Snapshot entity exceeds30 fact bounds")
        values = []
        for fact in facts:
            if fact.status != "accepted":
                continue
            if fact.field in CONTACT_FIELDS or fact.field == "professional_email":
                # Preserve original ownership: a reviewed group does not make
                # another person's professional address this person's address.
                ids = session.execute(
                    sa.select(claims.c.id, claims.c.value).where(
                        claims.c.workspace_id == scope(session),
                        claims.c.entity_id == identifier,
                        claims.c.field == fact.field,
                    )
                ).all()
                ids = [row.id for row in ids if row.value == fact.value]
                if not isinstance(fact.value, str):
                    continue
                if not any(
                    check_contact(
                        session, identifier, fact.value, claim_id=claim_id, evidence_id=ev
                    ).email
                    is not None
                    for claim_id in ids
                    for ev in fact.evidence_ids
                ):
                    continue
            records = (
                session.execute(
                    sa.select(
                        evidence.c.id,
                        evidence.c.source_url,
                        evidence.c.source_platform,
                        evidence.c.collected_at,
                        sa.func.left(evidence.c.excerpt, 4096).label("excerpt"),
                        (sa.func.length(evidence.c.excerpt) > 4096).label("excerpt_truncated"),
                    ).where(
                        evidence.c.workspace_id == scope(session),
                        evidence.c.id.in_(fact.evidence_ids),
                    )
                )
                .mappings()
                .all()
            )
            values.append(
                {
                    "field": fact.field,
                    "value": fact.value,
                    "claim_ids": sorted(
                        claim["id"]
                        for claim in originals
                        if claim["field"] == fact.field
                        and claim["value"] == fact.value
                        and claim["status"] == "accepted"
                        and claim["mode"] == "observed"
                        and original_support.get(claim["id"]) == set(fact.evidence_ids)
                    ),
                    "source_entity_ids": sorted(
                        {
                            claim["entity_id"]
                            for claim in originals
                            if claim["field"] == fact.field
                            and claim["value"] == fact.value
                            and claim["status"] == "accepted"
                            and claim["mode"] == "observed"
                            and original_support.get(claim["id"]) == set(fact.evidence_ids)
                        }
                    ),
                    "evidence": [
                        {**dict(row), "collected_at": row["collected_at"].isoformat()}
                        for row in records
                    ],
                }
            )
        fit_payload = TypeAdapter(type(fit)).dump_python(fit, mode="json")
        if unresolved:
            values = []
            fit_payload["status"] = "near_match"
            fit_payload["limitations"] = [
                *fit_payload["limitations"],
                "Suppressed identity match remains unverified; review required.",
            ]
        members.append(
            {
                "entity_id": identifier,
                "display_name": entity["display_name"],
                "fit": fit_payload,
                "identity_status": "suppression_unresolved" if unresolved else "reviewed_facts",
                "values": values,
            }
        )
    payload = {
        "snapshot_at": now.isoformat(),
        "members": members,
        "omitted": omitted,
        "refresh_scope": "persisted_reviewed_facts_only",
    }
    if len(TypeAdapter(dict).dump_json(payload)) > 1_048_576:
        raise ValueError("Snapshot payload exceeds1MiB bounds")
    result = insert_row(
        session,
        list_snapshots,
        list_id=list_id,
        revision=latest + 1,
        plan_id=header["plan_id"],
        payload=payload,
        created_by=session.info["actor_id"],
    )
    from skriller.webhooks.service import enqueue_snapshot

    enqueue_snapshot(session, result)
    return result


def snapshot(session, list_id: str, revision: int):
    row = (
        session.execute(
            sa.select(list_snapshots).where(
                list_snapshots.c.workspace_id == scope(session),
                list_snapshots.c.list_id == list_id,
                list_snapshots.c.revision == revision,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Saved snapshot unavailable")
    return dict(row)
