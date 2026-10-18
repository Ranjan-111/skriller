"""Durable candidate reads using the copied guarded fetch and cleanup adapters."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from time import monotonic
from uuid import UUID

import sqlalchemy as sa
from agent_reach.channels import get_all_channels
from scrapling.engines.toolbelt.custom import Response

from skriller.connectors.fetch import FetchArtifact, FetchUnavailable, HTTPFetcher
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, evidence, job_events
from skriller.extraction.cleanup import CleanupLimits, prepare_context
from skriller.jobs.budget import locked_job
from skriller.jobs.state import TERMINAL_STATES, finish
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.storage import BlobIntegrityError, BlobUnavailable


def schedule_collection(session, job, entity_ids):
    """Job lock and idempotent outbox make discovery replay safe."""
    if not entity_ids:
        return False
    if job["stage"] not in {"discovering", "collecting"}:
        return True  # A replay cannot move a later checkpoint back to collection.
    if len(entity_ids) > 100:
        raise ValueError("Collection candidate count exceeds pilot bound")
    for entity_id in dict.fromkeys(entity_ids):
        if ResearchRepository.get_entity(session, entity_id) is None:
            raise LookupError("Collection candidate unavailable")
        attempt = JobRepository.attempt(session, job["id"], f"collecting:{entity_id}", "collecting")
        JobRepository.enqueue(
            session,
            job["id"],
            f"attempt:{attempt['id']}",
            topic="execute_attempt",
            attempt_id=attempt["id"],
        )
    JobRepository.transition(session, job["id"], "running", stage="collecting")
    return True


def public_web_url(url):
    # Reuse the copied ordered platform routing without executing channel reads.
    return (
        next((channel.name for channel in get_all_channels() if channel.can_handle(url)), None)
        == "web"
    )


def collection_handler(
    database,
    identity,
    proxy_url,
    storage,
    browser=None,
    github_reader=None,
    cache_ttl_seconds=0,
    youtube_reader=None,
    reddit_reader=None,
    linkedin_reader=None,
    instagram_reader=None,
    facebook_reader=None,
    connection_store=None,
):
    """Each leased attempt reads one persisted, discovery-owned candidate."""
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.job_id == job["id"],
                    attempts.c.id == str(identity.attempt_id),
                    attempts.c.stage == "collecting",
                )
            )
            .mappings()
            .one()
        )
        entity_id = str(UUID(attempt["logical_key"].removeprefix("collecting:")))
        discovery_ids = (
            session.execute(
                sa.select(attempts.c.result_entity_ids).where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.job_id == job["id"],
                    attempts.c.stage == "discovering",
                    attempts.c.state == "succeeded",
                )
            )
            .scalars()
            .all()
        )
        if not any(entity_id in batch for batch in discovery_ids):
            raise LookupError("Candidate is outside this discovery checkpoint")
        candidate = ResearchRepository.get_entity(session, entity_id)
        if candidate is None:
            raise LookupError("Collection candidate unavailable")
        attributes = dict(candidate["attributes"])
        created_at = job["created_at"]

    if attributes["source"] in {"instagram", "facebook"}:
        from skriller.research.social_collection import social_collection_handler

        return social_collection_handler(
            database,
            identity,
            attributes,
            entity_id,
            storage,
            created_at,
            instagram_reader if attributes["source"] == "instagram" else facebook_reader,
            connection_store,
        )
    if attributes["source"] == "linkedin":
        from skriller.research.linkedin_collection import linkedin_collection_handler

        return linkedin_collection_handler(
            database,
            identity,
            attributes,
            entity_id,
            storage,
            created_at,
            linkedin_reader,
            connection_store,
        )
    if attributes["source"] == "reddit":
        from skriller.research.reddit_collection import reddit_collection_handler

        return reddit_collection_handler(
            database,
            identity,
            attributes,
            entity_id,
            storage,
            created_at,
            reddit_reader,
            connection_store,
        )
    if attributes["source"] == "youtube":
        from skriller.research.youtube_collection import youtube_collection_handler

        return youtube_collection_handler(
            database, identity, attributes, entity_id, storage, youtube_reader
        )
    if attributes["source"] == "github":
        from skriller.research.github_collection import github_collection_handler

        return github_collection_handler(
            database, identity, attributes, entity_id, proxy_url, storage, github_reader
        )
    if attributes["source"] == "rss":
        from skriller.research.rss_collection import rss_collection_handler

        return rss_collection_handler(
            database, identity, attributes, entity_id, proxy_url, storage, created_at
        )

    fetcher = HTTPFetcher(database, trusted_proxy_url=proxy_url, max_body_bytes=2 * 1024 * 1024)

    def run(plan, timeout_seconds):
        artifact, prepared, failure = None, None, None
        url = attributes["url"]
        if attributes["source"] != "web" or not public_web_url(url):
            failure = Failure(
                code="unsupported_operation", message="Platform-specific read adapter required"
            )
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
                replay_key = None
                revalidation = None
                if cache_ttl_seconds:
                    from skriller.research.collection_cache import (
                        cache_key,
                        needs_revalidation,
                        read_cached,
                    )

                    try:
                        replay_key = cache_key(url, plan.entity_type)
                    except ValueError:
                        pass  # Credential-like query URLs cannot enter the cache.
                    if replay_key is not None:
                        artifact = read_cached(database, storage, context, replay_key)
                        if artifact is not None and needs_revalidation(artifact):
                            revalidation, artifact = artifact, None
                try:
                    if artifact is None:
                        artifact = fetcher.fetch(
                            context,
                            url,
                            source="web",
                            operation_key=identity.attempt_id.hex,
                            revalidation=revalidation,
                        )
                except FetchUnavailable as exc:
                    if (
                        browser is None
                        or exc.classification is None
                        or (
                            exc.classification.next_method != "dynamic"
                            and not (browser.stealth and exc.classification.status == "challenge")
                        )
                    ):
                        raise
                    result = browser.fetch(
                        context,
                        url,
                        source="web",
                        readiness_selector="body h1, body article, body [data-result]",
                        operation_key=identity.attempt_id.hex + ".dynamic",
                        max_requests=3,
                    )
                    parsed_at = monotonic()
                    response = Response(
                        result.final_url,
                        result.content,
                        result.status,
                        "",
                        {},
                        {"Content-Type": "text/html"},
                        {},
                        adaptive=False,
                    )
                    artifact = FetchArtifact(
                        response,
                        "web",
                        url,
                        result.final_url,
                        datetime.now(UTC),
                        "text/html",
                        sha256(result.content).hexdigest(),
                        len(result.content),
                        None,
                        monotonic() - parsed_at,
                        result.request_count,
                        str(context.workspace_id),
                        str(context.job_id),
                        result.classification,
                        access_route="isolated_dynamic_browser",
                        evidence_kind=result.classification.evidence_kind,
                        browser_seconds=result.elapsed_seconds,
                    )
                if not public_web_url(artifact.final_url):
                    artifact = None
                    failure = Failure(
                        code="unsupported_operation", message="Redirect requires a platform adapter"
                    )
                else:
                    prepared = prepare_context(
                        artifact.response.body.decode("utf-8", errors="strict"),
                        artifact.final_url,
                        limits=CleanupLimits(),
                    )
                    if isinstance(prepared, Failure):
                        failure, prepared = prepared, None
                    elif prepared.source_sha256 != artifact.content_hash:
                        failure, prepared = (
                            Failure(
                                code="schema_invalid",
                                message="Source encoding changed content identity",
                            ),
                            None,
                        )
                    elif replay_key is not None:
                        from skriller.research.collection_cache import write_cached

                        write_cached(
                            database, storage, context, replay_key, artifact, cache_ttl_seconds
                        )
            except FetchUnavailable as exc:
                failure = exc.failure
            except (BlobUnavailable, BlobIntegrityError):
                artifact, prepared = None, None
                failure = Failure(code="evidence_missing", message="Cached evidence unavailable")
            except UnicodeError:
                failure = Failure(code="schema_invalid", message="Source is not UTF-8 text")
        return (artifact, prepared, failure), Decimal(0), {"fetch_attempts": 0}

    def persist(session, data):
        artifact, prepared, failure = data
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
            or suppressed(session, entity_id=entity_id, url=attributes["url"])
        ):
            return []
        updated = dict(entity["attributes"])
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if artifact is not None:
            saved = artifact.persist(session, storage)
            if prepared is not None:
                session.execute(
                    sa.update(evidence)
                    .where(
                        evidence.c.workspace_id == scope(session),
                        evidence.c.id == saved["id"],
                    )
                    .values(excerpt="\n".join(node.quote for node in prepared.evidence))
                )
            # Private body/metadata identifiers stay out of the results API.
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["_collection_metadata_evidence_id"] = saved["metadata_evidence_id"]
            summary.update(
                status="read" if prepared is not None else "preparation_failed",
                observed_at=artifact.collected_at.isoformat(),
                final_url=artifact.final_url,
                content_hash=artifact.content_hash,
                network_seconds=artifact.network_seconds,
                parser_seconds=artifact.parser_seconds,
                browser_seconds=artifact.browser_seconds,
                coverage_complete=prepared.coverage_complete if prepared else False,
                prepared_chunks=len(prepared.chunks) if prepared else 0,
            )
        updated["collection"] = summary
        session.execute(
            sa.update(entities)
            .where(
                entities.c.workspace_id == scope(session),
                entities.c.id == entity_id,
            )
            .values(attributes=updated)
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"collection:{identity.attempt_id}",
            "collection_summary",
            {
                "entity_id": entity_id,
                "source": attributes["source"],
                "status": summary["status"],
                "failure_code": summary["failure_code"],
                "network_seconds": summary.get("network_seconds"),
                "parser_seconds": summary.get("parser_seconds"),
                "browser_seconds": summary.get("browser_seconds"),
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
        capacity_source="web",
        feedback_failure=lambda data: data[2],
    )


def execute_collection(
    database,
    payload,
    proxy_url,
    *,
    storage=None,
    enable_extraction=False,
    browser=None,
    github_reader=None,
    cache_ttl_seconds=0,
    youtube_reader=None,
    reddit_reader=None,
    linkedin_reader=None,
    instagram_reader=None,
    facebook_reader=None,
    connection_store=None,
):
    if (
        isinstance(cache_ttl_seconds, bool)
        or not isinstance(cache_ttl_seconds, int)
        or not 0 <= cache_ttl_seconds <= 300
    ):
        raise ValueError("Public collector cache TTL must be 0–300 seconds")
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Collection attempt required")
    from skriller.research.rebind import pause_for_read_connection

    paused = pause_for_read_connection(
        database,
        identity,
        connection_store,
        {"linkedin": linkedin_reader is not None, "reddit": reddit_reader is not None},
    )
    if paused is not None:
        return paused
    if storage is None:
        from skriller.settings import Settings
        from skriller.storage.configuration import configured_storage

        with configured_storage(Settings()) as owned_storage:
            return execute_collection(
                database,
                payload,
                proxy_url,
                storage=owned_storage,
                enable_extraction=enable_extraction,
                browser=browser,
                github_reader=github_reader,
                cache_ttl_seconds=cache_ttl_seconds,
                youtube_reader=youtube_reader,
                reddit_reader=reddit_reader,
                linkedin_reader=linkedin_reader,
                instagram_reader=instagram_reader,
                facebook_reader=facebook_reader,
                connection_store=connection_store,
            )
    handler = collection_handler(
        database,
        identity,
        proxy_url,
        storage,
        browser,
        github_reader,
        cache_ttl_seconds,
        youtube_reader=youtube_reader,
        reddit_reader=reddit_reader,
        linkedin_reader=linkedin_reader,
        instagram_reader=instagram_reader,
        facebook_reader=facebook_reader,
        connection_store=connection_store,
    )
    outcome = CheckpointWorker(database, {"collecting": handler}).execute(payload)
    if outcome["status"] not in {"checkpointed", "source_unavailable"}:
        return outcome
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        if job["state"] in TERMINAL_STATES:
            return outcome
        rows = (
            session.execute(
                sa.select(attempts.c.state).where(
                    attempts.c.workspace_id == scope(session),
                    attempts.c.job_id == job["id"],
                    attempts.c.stage == "collecting",
                )
            )
            .scalars()
            .all()
        )
        if any(state in {"pending", "running"} for state in rows):
            return outcome
        if enable_extraction:
            from skriller.research.page_extraction import schedule_extraction

            if schedule_extraction(session, job):
                return outcome
        finish_collection_pipeline(session, job)
    return outcome


def finish_collection_pipeline(session, job):
    rows = (
        session.execute(
            sa.select(attempts.c.state).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job["id"],
                attempts.c.stage.in_(["collecting", "extracting"]),
            )
        )
        .scalars()
        .all()
    )
    if any(state in {"pending", "running"} for state in rows):
        return
    failed_reads = session.execute(
        sa.select(sa.func.count())
        .select_from(job_events)
        .where(
            job_events.c.workspace_id == scope(session),
            job_events.c.job_id == job["id"],
            sa.or_(
                sa.and_(
                    job_events.c.kind == "collection_summary",
                    job_events.c.details["status"].as_string() != "read",
                ),
                sa.and_(
                    job_events.c.kind == "extraction_summary",
                    job_events.c.details["status"].as_string() != "observed",
                ),
            ),
        )
    ).scalar_one()
    discovery_failed = (
        session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.workspace_id == scope(session),
                job_events.c.job_id == job["id"],
                job_events.c.kind == "discovery_summary",
            )
        )
        .scalars()
        .all()
    )
    from skriller.research.qualification import checkpoint_qualification
    from skriller.research.service import result_rows

    retained = result_rows(session, job["id"])
    job = checkpoint_qualification(session, job, retained)
    if job is None:
        return

    finish(
        session,
        job["id"],
        outcome="source_interrupted"
        if failed_reads
        or any(state != "succeeded" for state in rows)
        or any(item["source_failures"] for item in discovery_failed)
        else "source_exhausted",
        retained_results=len(retained),
        expected_version=job["version"],
    )
