"""Private exports built from trusted qualification and tenant evidence."""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from skriller.contracts import SearchPlan
from skriller.db.repositories import ConversationRepository, ResearchRepository, scope
from skriller.db.schema import evidence
from skriller.exports.formats import Format, serialize
from skriller.qualification.contacts import check_contact
from skriller.qualification.identity import group_claims
from skriller.qualification.service import load_facts, qualify_entity
from skriller.storage import BlobTooLarge, BlobUnavailable, EvidenceStorage

SCHEMA_VERSION = "skriller-qualified-v1"
BASE = (
    "entity_id",
    "fit",
    "schema_version",
    "evidence_ids",
    "null_fields",
    "field_evidence",
    "export_metadata",
)


def create_export(
    session,
    storage: EvidenceStorage,
    plan_id: str,
    entity_ids: tuple[str, ...],
    *,
    format: Format,
    selected_near_ids: tuple[str, ...] = (),
    expiry_seconds: int = 3600,
):
    if len(entity_ids) > 100 or len(set(entity_ids)) != len(entity_ids):
        raise ValueError("Select at most 100 distinct entities")
    if not set(selected_near_ids) <= set(entity_ids):
        raise ValueError("Near-match selection must belong to requested entities")
    if not 60 <= expiry_seconds <= 86400:
        raise ValueError("Export expiry must be 60–86400 seconds")
    plan_row = ConversationRepository.get_plan(session, plan_id)
    if plan_row is None:
        raise BlobUnavailable("Export plan unavailable")
    plan = SearchPlan.model_validate(plan_row["interpretation"])
    if str(plan.workspace_id) != scope(session):
        raise BlobUnavailable("Export plan unavailable")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    rows = []
    fields = set(plan.requested_fields)
    for entity_id in entity_ids:
        UUID(entity_id)
        fit = qualify_entity(session, plan, entity_id)
        if fit.status == "excluded" or (
            fit.status != "confirmed" and entity_id not in selected_near_ids
        ):
            raise ValueError("Only confirmed or explicitly selected near matches may be exported")
        facts = [
            fact
            for fact in load_facts(session, entity_id, now=now)
            if fact.status == "accepted" and fact.field in fields
        ]
        allowed_facts = []
        source_claims = None
        for fact in facts:
            if "phone" in fact.field or (
                "email" in fact.field and fact.field not in {"work_email", "professional_email"}
            ):
                continue
            if fact.field in {"work_email", "professional_email"}:
                if not isinstance(fact.value, str):
                    continue
                source_claims = (
                    source_claims if source_claims is not None else group_claims(session, entity_id)
                )
                if not any(
                    claim["field"] == fact.field
                    and claim["value"] == fact.value
                    and any(
                        check_contact(
                            session,
                            claim["entity_id"],
                            fact.value,
                            claim_id=claim["id"],
                            evidence_id=identifier,
                        ).email
                        is not None
                        for identifier in fact.evidence_ids
                    )
                    for claim in source_claims
                ):
                    continue
            allowed_facts.append(fact)
        facts = allowed_facts
        row: dict[str, Any] = {
            "entity_id": entity_id,
            "fit": fit.status,
            "schema_version": SCHEMA_VERSION,
            "evidence_ids": sorted(
                {ev for fact in facts for ev in fact.evidence_ids}
                | {
                    ev
                    for comparison in (*fit.essential, *fit.exclusions, *fit.preferences)
                    for ev in comparison.evidence_ids
                }
            ),
        }
        row["field_evidence"] = {}
        for fact in facts:
            row["field_evidence"].setdefault(fact.field, []).append(
                {
                    "evidence_ids": list(fact.evidence_ids),
                    "observed_at": fact.observed_at.isoformat(),
                    "event_at": fact.event_at.isoformat() if fact.event_at is not None else None,
                }
            )
        values: dict[str, list[Any]] = {}
        for fact in facts:
            values.setdefault(fact.field, []).append(fact.value)
        for field, candidates in values.items():
            # Contradictory values never silently pick a first value.
            if all(
                type(value) is type(candidates[0]) and value == candidates[0]
                for value in candidates
            ):
                row["field." + field] = candidates[0]
        rows.append(row)
    columns = [*BASE, *("field." + field for field in sorted(fields))]
    for row in rows:
        row["null_fields"] = [key for key in columns if key.startswith("field.") and key not in row]
        for key in columns:
            row.setdefault(key, None)
    metadata = {
        "kind": "qualified_export",
        "schema_version": SCHEMA_VERSION,
        "columns": columns,
        "plan_id": plan_id,
        "plan_revision": plan.revision,
        "created_at": now.isoformat(),
        "format": format,
        "csv_null_encoding": "empty cell listed in null_fields",
        "csv_formula_guard": "apostrophe prefix",
        "row_count": len(rows),
    }
    evidence_ids = {item for row in rows for item in row["evidence_ids"]}
    evidence_rows = (
        session.execute(
            sa.select(evidence).where(
                evidence.c.workspace_id == scope(session), evidence.c.id.in_(evidence_ids)
            )
        )
        .mappings()
        .all()
    )
    metadata["evidence"] = [
        {
            "id": row["id"],
            "source_url": row["source_url"],
            "source_platform": row["source_platform"],
            "collected_at": row["collected_at"].isoformat(),
        }
        for row in sorted(evidence_rows, key=lambda row: row["id"])
    ]
    expiration = min(
        [
            now + timedelta(seconds=expiry_seconds),
            *(row["expires_at"] for row in evidence_rows if row["expires_at"] is not None),
        ]
    )
    for row in rows:
        row["export_metadata"] = metadata
    content = serialize(rows, metadata, format)
    if len(content) > min(storage.max_bytes, 2 * 1024 * 1024):
        raise BlobTooLarge("Export exceeds pilot size")
    artifact = storage.store(
        session,
        content,
        source_url="https://skriller.invalid/exports",
        source_platform="skriller_export",
        collected_at=now,
        expires_at=expiration,
        excerpt=json.dumps(metadata, ensure_ascii=False),
    )
    return {
        "id": artifact["id"],
        "format": format,
        "row_count": len(rows),
        "expires_at": artifact["expires_at"],
        "schema_version": SCHEMA_VERSION,
    }


def download_export(session, storage: EvidenceStorage, export_id: str):
    record = ResearchRepository.get_evidence(session, export_id)
    if record is None or record["source_platform"] != "skriller_export":
        raise BlobUnavailable("Export unavailable")
    try:
        metadata = json.loads(record["excerpt"] or "")
        if metadata["kind"] != "qualified_export" or metadata["format"] not in {
            "csv",
            "json",
            "jsonl",
        }:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise BlobUnavailable("Export unavailable") from None
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    for item in metadata.get("evidence", []):
        source = ResearchRepository.get_evidence(session, item["id"])
        if source is None or (source["expires_at"] is not None and source["expires_at"] <= now):
            raise BlobUnavailable("Export unavailable")
    return storage.retrieve(session, export_id), metadata["format"]
