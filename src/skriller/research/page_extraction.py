"""Checkpoint saved-page directory observations through the copied model graph."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, evidence
from skriller.extraction.cleanup import CleanupLimits, prepare_context
from skriller.extraction.presets import extract_directory_page
from skriller.jobs.budget import locked_job
from skriller.jobs.state import TERMINAL_STATES
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.research.collection import finish_collection_pipeline
from skriller.settings import Settings
from skriller.storage import BlobIntegrityError, BlobUnavailable, EvidenceStorage, LocalBlobBackend


def schedule_extraction(session, job):
    collected = (
        session.execute(
            sa.select(attempts.c.result_entity_ids).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job["id"],
                attempts.c.stage == "collecting",
                attempts.c.state == "succeeded",
            )
        )
        .scalars()
        .all()
    )
    ids = list(dict.fromkeys(value for batch in collected for value in batch))
    scheduled = 0
    for identifier in ids:
        entity = ResearchRepository.get_entity(session, identifier)
        if entity is None or entity["attributes"].get("collection", {}).get("status") != "read":
            continue
        attempt = JobRepository.attempt(
            session, job["id"], f"extracting:{identifier}", "extracting"
        )
        JobRepository.enqueue(
            session,
            job["id"],
            f"attempt:{attempt['id']}",
            topic="execute_attempt",
            attempt_id=attempt["id"],
        )
        scheduled += 1
    if scheduled:
        JobRepository.transition(session, job["id"], "running", stage="extracting")
    return bool(scheduled)


def extraction_handler(database, identity, storage, settings, model):
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.job_id == job["id"],
                    attempts.c.id == str(identity.attempt_id),
                    attempts.c.stage == "extracting",
                )
            )
            .mappings()
            .one()
        )
        entity_id = str(UUID(attempt["logical_key"].removeprefix("extracting:")))
        parents = (
            session.execute(
                sa.select(attempts.c.result_entity_ids).where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.job_id == job["id"],
                    attempts.c.stage == "collecting",
                    attempts.c.state == "succeeded",
                )
            )
            .scalars()
            .all()
        )
        if not any(entity_id in batch for batch in parents):
            raise LookupError("Extraction candidate is outside collected checkpoints")
        entity = ResearchRepository.get_entity(session, entity_id)
        if entity is None or entity["attributes"].get("collection", {}).get("status") != "read":
            raise LookupError("Collected candidate unavailable")
        body_id = entity["attributes"]["_collection_body_evidence_id"]
        created_at = job["created_at"]

    def run(plan, timeout_seconds):
        result = None
        failure_code = None
        try:
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                body = storage.retrieve(session, body_id)
                record = dict(ResearchRepository.get_evidence(session, body_id))
            # The local transport conservatively bounds input by UTF-8 bytes.
            # Small copied-tokenizer chunks leave room for schema/prompt/ID framing.
            prepared = prepare_context(
                body.decode("utf-8", errors="strict"),
                record["source_url"],
                limits=CleanupLimits(chunk_tokens=128),
            )
            if isinstance(prepared, Failure):
                failure_code = prepared.code
            elif prepared.source_sha256 != record["content_hash"]:
                failure_code = "schema_invalid"
            else:
                context = ExecutionContext(
                    workspace_id=plan.workspace_id,
                    job_id=identity.job_id,
                    actor_id=identity.actor_id,
                    plan_revision=plan.revision,
                    deadline=min(
                        created_at + timedelta(seconds=plan.limits.deadline_seconds),
                        datetime.now(UTC) + timedelta(seconds=max(0, timeout_seconds - 1)),
                    ),
                    attempt_budget=2,
                )
                result = asyncio.run(
                    extract_directory_page(
                        database,
                        context,
                        prepared,
                        "directory",
                        operation_key=f"page:{identity.attempt_id}",
                        settings=settings,
                        model=model,
                        max_chunks=2,
                    )
                )
                failure_code = result.failure_code
        except (BlobUnavailable, BlobIntegrityError, UnicodeError):
            failure_code = "evidence_missing"
        return (result, failure_code), Decimal(0), {"llm_calls": 0}

    def persist(session, data):
        from skriller.erasure import privacy_lock, suppressed

        privacy_lock(session)

        entity = (
            session.execute(
                sa.select(entities)
                .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            entity is None
            or entity["attributes"].get("erased")
            or suppressed(session, entity_id=entity_id)
        ):
            return []
        result, failure_code = data
        record = (
            session.execute(
                sa.select(evidence)
                .where(
                    evidence.c.workspace_id == scope(session),
                    evidence.c.id == body_id,
                )
                .with_for_update(read=True, key_share=True)
            )
            .mappings()
            .one_or_none()
        )
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        observations, seen = [], set()
        rejected = result.rejected_claims if result else 0
        for draft in result.claims if result else ():
            key = (draft.field, json.dumps(draft.value), draft.quote)
            if key in seen:
                continue
            seen.add(key)
            if (
                len(observations) >= 60
                or record is None
                or not record["excerpt"]
                or draft.quote not in record["excerpt"]
                or draft.source_sha256 != record["content_hash"]
                or record["expires_at"] is not None
                and record["expires_at"] <= now
            ):
                rejected += 1
                continue
            # Exact source occurrence cannot establish subject identity or fit.
            claim = ResearchRepository.claim(
                session,
                entity_id,
                draft.field,
                draft.value,
                mode="observed",
                status="unverified",
                evidence_ids=[body_id],
            )
            observations.append(
                {
                    "claim_id": claim["id"],
                    "field": draft.field,
                    "value": draft.value,
                    "quote": draft.quote,
                    "status": claim["status"],
                }
            )
        statuses = {
            row["id"]: row["status"] for row in ResearchRepository.claims_for(session, entity_id)
        }
        for observation in observations:
            observation["status"] = statuses[observation["claim_id"]]
        summary = {
            "status": "unavailable" if failure_code else "observed",
            "failure_code": failure_code,
            "observations": observations,
            "rejected_claims": rejected,
            "coverage_complete": result.coverage_complete if result else False,
            "omitted_chunks": result.omitted_chunks if result else 0,
        }
        entity = ResearchRepository.get_entity(session, entity_id)
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(attributes={**entity["attributes"], "extraction": summary})
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"extraction:{identity.attempt_id}",
            "extraction_summary",
            {
                "entity_id": entity_id,
                "status": summary["status"],
                "failure_code": failure_code,
                "observation_count": len(observations),
                "rejected_claims": rejected,
            },
        )
        return [entity_id]

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {"llm_calls": 0},
        lease_seconds=105,
        run_with_deadline=run,
        capacity_source="saved_page",
    )


def execute_page_extraction(database, payload, *, settings=None, storage=None, model=None):
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Extraction attempt required")
    settings = settings or Settings()
    storage = storage or EvidenceStorage(LocalBlobBackend(settings.object_directory))
    handler = extraction_handler(database, identity, storage, settings, model)
    outcome = CheckpointWorker(database, {"extracting": handler}).execute(payload)
    if outcome["status"] in {"checkpointed", "source_unavailable"}:
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            if job["state"] not in TERMINAL_STATES:
                finish_collection_pipeline(session, job)
    return outcome
