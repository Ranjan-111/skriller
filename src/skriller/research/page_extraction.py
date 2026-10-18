"""Checkpoint saved-page directory observations through the copied model graph."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, create_model

from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, evidence
from skriller.extraction.cleanup import CleanupLimits, prepare_context
from skriller.extraction.presets import PresetId, extract_directory_page
from skriller.extraction.validation import Citation, validate_extraction
from skriller.jobs.budget import locked_job
from skriller.jobs.state import TERMINAL_STATES
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.research.adaptive_templates import template_observations
from skriller.research.collection import finish_collection_pipeline
from skriller.settings import Settings
from skriller.storage import BlobIntegrityError, BlobUnavailable
from skriller.storage.configuration import configured_storage


@lru_cache(maxsize=40)
def observation_schema(field: str) -> type[BaseModel]:
    fields: dict[str, Any] = {field: (str | int | float | bool, ...)}
    return create_model("SavedPageObservation", **fields)


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
        if (
            entity is None
            or entity["attributes"].get("source") not in {"web", "reddit", "linkedin"}
            or entity["attributes"].get("collection", {}).get("status") != "read"
            or entity["attributes"].get("source") == "reddit"
            and not entity["attributes"].get("reddit_thread")
        ):
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


def preset_for_source_url(source_url: str) -> PresetId:
    """Choose a bounded preset from the public page's path, never model output.

    A generic/company page remains the conservative fallback. Path matching is
    intentionally explicit so query strings and unrelated words in a hostname
    cannot silently select a more specialized extraction schema.
    """
    parsed = urlsplit(source_url)
    path = parsed.path.lower().rstrip("/")
    if parsed.hostname == "www.linkedin.com":
        return (
            "linkedin_profile"
            if path.startswith("/in/")
            else "linkedin_company"
            if path.startswith("/company/")
            else "linkedin_post"
        )
    segments = {segment for segment in path.split("/") if segment}
    if segments & {"team", "people", "leadership", "founders", "founder"}:
        return "team"
    if segments & {"careers", "career", "jobs", "job", "openings", "positions"}:
        return "careers"
    if segments & {"services", "solutions", "products"}:
        return "services"
    if segments & {"contact", "contacts"}:
        return "contact"
    if segments & {"directory", "companies", "vendors", "suppliers"}:
        return "directory"
    if segments & {"about", "company", "organization", "organisation"}:
        return "company"
    return "directory"


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

    if entity["attributes"].get("source") == "reddit":
        from skriller.research.reddit_signal_stage import reddit_signal_handler

        return reddit_signal_handler(
            database, identity, entity_id, body_id, created_at, storage, settings, model
        )

    def run(plan, timeout_seconds):
        result = None
        adaptive_claims = ()
        adaptive_diagnostics = []
        failure_code: str | None = None
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
                    attempt_id=identity.attempt_id,
                )
                adaptive_claims, adaptive_diagnostics = template_observations(
                    database,
                    context,
                    body.decode("utf-8"),
                    record["source_url"],
                    settings.reviewed_page_templates_file,
                )
                result = asyncio.run(
                    extract_directory_page(
                        database,
                        context,
                        prepared,
                        preset_for_source_url(record["source_url"]),
                        operation_key=f"page:{identity.attempt_id}",
                        settings=settings,
                        model=model,
                        max_chunks=2,
                    )
                )
                failure_code = result.failure_code
        except (BlobUnavailable, BlobIntegrityError, UnicodeError):
            failure_code = "evidence_missing"
        return (
            (result, failure_code, adaptive_claims, adaptive_diagnostics),
            Decimal(0),
            {"llm_calls": 0},
        )

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
        result, failure_code, adaptive_claims, adaptive_diagnostics = data
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
        observations: list[dict] = []
        seen = set()
        rejected = result.rejected_claims if result else 0
        for draft in (*(result.claims if result else ()), *adaptive_claims):
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
            checked = validate_extraction(
                session,
                UUID(entity_id),
                {draft.field: draft.value},
                observation_schema(draft.field),
                citations={draft.field: Citation((UUID(body_id),), draft.quote)},
                persist=True,
            )
            claim = checked.fields[draft.field]
            if claim.value is None:
                rejected += 1
                continue
            observations.append(
                {
                    "claim_id": claim.claim_id,
                    "field": draft.field,
                    "value": draft.value,
                    "quote": draft.quote,
                    "status": claim.status,
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
            "coverage_complete": result.coverage_complete
            and entity["attributes"].get("source") != "linkedin"
            if result
            else False,
            "omitted_chunks": result.omitted_chunks if result else 0,
        }
        entity = ResearchRepository.get_entity(session, entity_id)
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(
                attributes={
                    **entity["attributes"],
                    "extraction": summary,
                    "_adaptive_validation": adaptive_diagnostics,
                }
            )
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
    if storage is None:
        with configured_storage(settings) as owned_storage:
            return execute_page_extraction(
                database, payload, settings=settings, storage=owned_storage, model=model
            )
    handler = extraction_handler(database, identity, storage, settings, model)
    outcome = CheckpointWorker(database, {"extracting": handler}).execute(payload)
    if outcome["status"] in {"checkpointed", "source_unavailable"}:
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            if job["state"] not in TERMINAL_STATES:
                finish_collection_pipeline(session, job)
    return outcome
