"""Durable bounded thread reads, bound to the discovery credential generation."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.store import ConnectionUnavailable
from skriller.connectors.candidates import native_reference
from skriller.connectors.reddit_executor import RedditUnavailable
from skriller.connectors.reddit_request import RedditRead
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.worker import StageHandler


def reddit_collection_handler(
    database, identity, attributes, entity_id, storage, created_at, reader, store
):
    def run(plan, timeout_seconds):
        data = context = None
        failure = None
        calls = 0
        started = monotonic()
        try:
            if reader is None or store is None or attributes.get("provider") != "reddit_oauth":
                raise RedditUnavailable("needs_connection")
            native = native_reference(attributes["url"])
            match = re.fullmatch(
                r"/r/([A-Za-z0-9_]{1,32})/comments/([a-z0-9]{3,13})(?:/[^/]+)?/?",
                urlsplit(attributes["url"]).path,
            )
            if not match or native != {"namespace": "reddit_post", "id": match[2]}:
                raise RedditUnavailable("unsupported_operation")
            connection = UUID(attributes["_read_connection_ref"])
            credential = UUID(attributes["_read_credential_ref"])
            remaining = min(30, timeout_seconds - 2)
            if remaining <= 0:
                raise RedditUnavailable("deadline_exceeded")
            context = ExecutionContext(
                workspace_id=plan.workspace_id,
                job_id=identity.job_id,
                actor_id=identity.actor_id,
                plan_revision=plan.revision,
                connection_ref=connection,
                attempt_id=identity.attempt_id,
                attempt_budget=1,
                deadline=min(
                    created_at + timedelta(seconds=plan.limits.deadline_seconds),
                    datetime.now(UTC) + timedelta(seconds=remaining),
                ),
            )
            # Admission before I/O also refuses stale discovery checkpoints.
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                material = store.load_for_runner(session, context, "reddit_oauth_read")
                if material.credential_ref != credential:
                    raise RedditUnavailable("needs_connection")
            calls = 1
            data = reader.read(
                RedditRead(post_id=match[2], subreddit=match[1]),
                database=database,
                store=store,
                context=context,
                timeout=remaining,
                expected_credential_ref=credential,
            )
        except (RedditUnavailable, ConnectionUnavailable) as exc:
            code = getattr(exc, "code", "auth_required")
            failure = Failure.model_validate(
                {
                    "code": code
                    if code
                    in {
                        "auth_expired",
                        "access_denied",
                        "not_found",
                        "rate_limited",
                        "source_unavailable",
                        "unsupported_operation",
                        "deadline_exceeded",
                    }
                    else "auth_required",
                    "message": "Reddit thread read unavailable; reconnect and start a fresh run if needed",
                    "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
                }
            )
        except (KeyError, ValueError):
            failure = Failure(
                code="auth_required", message="A fresh connected Reddit run is required"
            )
        return (
            (data, failure, monotonic() - started, context),
            Decimal(0),
            {"fetch_attempts": calls},
        )

    def persist(session, result):
        data, failure, elapsed, context = result
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
        native = native_reference(attributes["url"])
        if native and suppressed(session, native_id=native):
            session.execute(
                sa.update(entities)
                .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
                .values(
                    attributes={"erased": True}, display_name=None, canonical_key=None, kind="other"
                )
            )
            return []
        if data is not None:
            try:
                material = store.load_for_runner(session, context, "reddit_oauth_read")
                if str(material.credential_ref) != attributes["_read_credential_ref"]:
                    raise ConnectionUnavailable("needs_connection")
            except ConnectionUnavailable:
                data = None
                failure = Failure(
                    code="auth_required", message="Reddit access changed before saving"
                )
        updated = dict(entity["attributes"])
        updated.pop("reddit_thread", None)
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if data is not None:
            blocked = set()
            kept = []
            for comment in data.comments:
                if comment.parent_id in blocked or suppressed(
                    session,
                    native_id={
                        "namespace": "reddit_comment",
                        "id": comment.native_id.removeprefix("t1_"),
                    },
                ):
                    blocked.add(comment.native_id)
                else:
                    kept.append(comment)
            data = data.model_copy(
                update={
                    "comments": tuple(kept),
                    "omitted_comments": data.omitted_comments + len(blocked),
                    "coverage_complete": data.coverage_complete and not blocked,
                }
            )
            saved = storage.store(
                session,
                data.model_dump_json().encode(),
                source_url=data.post.source_url,
                source_platform="reddit",
                collected_at=data.observed_at,
                excerpt=data.post.excerpt,
            )
            # Content-free child indexes make erasure of a comment invalidate
            # the shared thread blob, including after a backup restore.
            for comment in data.comments:
                ResearchRepository.entity(
                    session,
                    "other",
                    "Reddit comment reference",
                    canonical_key=f"{identity.job_id}:reddit-comment:{comment.native_id}",
                    attributes={
                        "url": comment.source_url,
                        "_source_native_id": {
                            "namespace": "reddit_comment",
                            "id": comment.native_id.removeprefix("t1_"),
                        },
                        "_collection_body_evidence_id": saved["id"],
                    },
                )
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["reddit_thread"] = {
                "evidence_id": str(saved["id"]),
                "thread": data.model_dump(mode="json"),
            }
            summary.update(
                status="read",
                observed_at=data.observed_at.isoformat(),
                final_url=data.post.source_url,
                content_hash=saved["content_hash"],
                coverage_complete=data.coverage_complete,
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
                "source": "reddit",
                "status": summary["status"],
                "failure_code": summary["failure_code"],
                "provider_io_seconds": elapsed,
            },
        )
        return [entity_id]

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {"fetch_attempts": 1},
        lease_seconds=40,
        run_with_deadline=run,
        capacity_kind="http",
        capacity_source="reddit",
        capacity_host="oauth.reddit.com",
        minimum_interval=2,
        feedback_failure=lambda result: result[1],
    )
