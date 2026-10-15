"""Guarded RSS/Atom bytes become bounded attributed source material, never leads."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic

import sqlalchemy as sa

from skriller.connectors.fetch import FetchUnavailable
from skriller.connectors.rss import parse_feed, public_rss_binding
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.worker import StageHandler


def rss_collection_handler(
    database, identity, attributes, entity_id, proxy_url, storage, created_at
):
    binding = public_rss_binding(database, proxy_url, operation_key=identity.attempt_id.hex)

    def run(plan, timeout_seconds):
        artifact, feed, failure = None, None, None
        if "rss" not in plan.sources:
            failure = Failure(code="unsupported_operation", message="RSS was not selected")
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
                attempt_budget=min(3, plan.limits.fetch_attempts),
            )
            try:
                artifact = binding.execute(context, attributes["url"])
                parsed_at = monotonic()
                feed = parse_feed(
                    artifact.response.body,
                    artifact.final_url,
                    max_entries=min(20, plan.limits.result_limit),
                )
                artifact = replace(
                    artifact, parser_seconds=artifact.parser_seconds + monotonic() - parsed_at
                )
                if feed.malformed:
                    feed = None
                    failure = Failure(
                        code="schema_invalid", message="Source is not a valid RSS or Atom feed"
                    )
            except FetchUnavailable as error:
                failure = error.failure
        return (artifact, feed, failure), Decimal(0), {"fetch_attempts": 0}

    def persist(session, result):
        artifact, feed, failure = result
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
            or suppressed(session, entity_id=entity_id, url=attributes["url"])
        ):
            return []
        updated = dict(entity["attributes"])
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if artifact is not None and feed is not None:
            saved = artifact.persist(session, storage)
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["_collection_metadata_evidence_id"] = saved["metadata_evidence_id"]
            updated["feed"] = {
                "feed_url": feed.feed_url,
                "entries": [
                    {
                        "entry_id": entry.entry_id,
                        "title": entry.title,
                        "url": entry.url,
                        "published_at": entry.published_at,
                        "updated_at": entry.updated_at,
                        "summary": entry.summary[:4096],
                        "summary_truncated": entry.summary_truncated or len(entry.summary) > 4096,
                    }
                    for entry in feed.entries
                ],
                "duplicate_count": feed.duplicate_count,
                "invalid_link_count": feed.invalid_link_count,
                "omitted_entry_count": feed.omitted_entry_count,
                "evidence_expired": False,
            }
            summary.update(
                status="read",
                observed_at=artifact.collected_at.isoformat(),
                final_url=artifact.final_url,
                content_hash=artifact.content_hash,
                network_seconds=artifact.network_seconds,
                parser_seconds=artifact.parser_seconds,
                coverage_complete=not (
                    feed.omitted_entry_count
                    or feed.invalid_link_count
                    or feed.truncated_entry_count
                    or any(len(entry.summary) > 4096 for entry in feed.entries)
                ),
                prepared_chunks=0,
            )
        updated["collection"] = summary
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(attributes=updated)
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"collection:{identity.attempt_id}",
            "collection_summary",
            {
                "entity_id": entity_id,
                "source": "rss",
                "status": summary["status"],
                "failure_code": summary["failure_code"],
                "feed_entries": len(feed.entries) if feed else 0,
                "network_seconds": artifact.network_seconds if artifact else None,
                "parser_seconds": artifact.parser_seconds if artifact else None,
                "browser_seconds": artifact.browser_seconds if artifact else None,
            },
        )
        return [entity_id]

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {"fetch_attempts": 0},
        lease_seconds=105,
        run_with_deadline=run,
        capacity_source="rss",
    )
