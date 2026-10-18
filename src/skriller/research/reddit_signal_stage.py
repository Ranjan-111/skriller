"""Saved-evidence-only discussion extraction; owns no source or account access."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa

from skriller.connectors.reddit_read import RedditThread
from skriller.contracts import ExecutionContext
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock
from skriller.extraction.reddit_signals import extract_reddit_signals
from skriller.jobs.worker import StageHandler
from skriller.storage import BlobIntegrityError, BlobUnavailable


def reddit_signal_handler(
    database, identity, entity_id, body_id, created_at, storage, settings, model
):
    def run(plan, timeout_seconds):
        try:
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                body = storage.retrieve(session, body_id)
            thread = RedditThread.model_validate_json(body)
            context = ExecutionContext(
                workspace_id=plan.workspace_id,
                job_id=identity.job_id,
                actor_id=identity.actor_id,
                plan_revision=plan.revision,
                attempt_id=identity.attempt_id,
                attempt_budget=1,
                deadline=min(
                    created_at + timedelta(seconds=plan.limits.deadline_seconds),
                    datetime.now(UTC) + timedelta(seconds=max(0, timeout_seconds - 1)),
                ),
            )
            result = asyncio.run(
                extract_reddit_signals(
                    database,
                    context,
                    thread,
                    operation_key="reddit-signals:" + identity.attempt_id.hex,
                    model=model,
                    settings=settings,
                )
            )
        except (BlobIntegrityError, BlobUnavailable, ValueError):
            result = ([], 0, False, "evidence_missing")
        return result, Decimal(0), {"llm_calls": 0}  # Copied graph owns model reservations.

    def persist(session, result):
        signals, rejected, complete, failure = result
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
        if entity is None or entity["attributes"].get("erased"):
            return []
        record = ResearchRepository.get_evidence(session, body_id)
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            record is None
            or record["object_key"] is None
            or (record["expires_at"] is not None and record["expires_at"] <= now)
        ):
            return []
        attributes = dict(entity["attributes"])
        if attributes.get("_collection_body_evidence_id") != body_id or not attributes.get(
            "reddit_thread"
        ):
            return []
        view = dict(attributes["reddit_thread"])
        view.update(
            signals=signals,
            rejected_signals=rejected,
            signal_coverage_complete=complete,
            signal_failure_code=failure,
        )
        attributes["reddit_thread"] = view
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(attributes=attributes)
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"reddit-signals:{identity.attempt_id}",
            "extraction_summary",
            {
                "entity_id": entity_id,
                "source": "reddit",
                "status": "observed" if signals else "unavailable",
                "observation_count": len(signals),
                "rejected_claims": rejected,
                "failure_code": failure,
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
        capacity_source="saved_reddit_thread",
    )
