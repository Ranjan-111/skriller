"""Durable owner-bound profile reads; orchestration follows linkedin_collection."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.store import ConnectionUnavailable
from skriller.connectors.facebook_read import FacebookProfile, FacebookRead
from skriller.connectors.instagram_read import InstagramProfile, InstagramRead
from skriller.connectors.social_executor import SocialUnavailable
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.worker import StageHandler


def request_for_url(source, url):
    parts = urlsplit(url)
    schema = InstagramRead if source == "instagram" else FacebookRead
    request = schema(username=parts.path.strip("/"))
    allowed = (
        {request.target_url()}
        if source == "instagram"
        else {request.target_url(), request.target_url() + "/"}
    )
    if url not in allowed:
        raise ValueError("A canonical named profile reference is required")
    return request


def social_collection_handler(
    database, identity, attributes, entity_id, storage, created_at, reader, store
):
    source = attributes["source"]
    if source not in {"instagram", "facebook"}:
        raise ValueError("A named social source is required")
    operation = source + "_profile"
    maximum_calls = 3 if source == "instagram" else 1

    def run(plan, timeout_seconds):
        data = context = receipt = None
        failure = None
        calls = 0
        started = monotonic()
        try:
            if (
                reader is None
                or store is None
                or reader.source != source
                or attributes.get("provider") != "opencli_" + source
            ):
                raise ConnectionUnavailable("needs_connection")
            request = request_for_url(source, attributes["url"])
            connection = UUID(attributes["_read_connection_ref"])
            credential = UUID(attributes["_read_credential_ref"])
            remaining = min(40, timeout_seconds - 2)
            if remaining <= 0:
                raise SocialUnavailable()
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
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                material = store.load_for_runner(session, context, operation)
                if material.credential_ref != credential:
                    raise ConnectionUnavailable("needs_connection")
            # A dispatched failed/uncertain call retains the full possible API
            # reservation. A successful Instagram primary/fallback reconciles 1/3.
            calls = maximum_calls
            receipt = reader.execute(
                request,
                database=database,
                store=store,
                context=context,
                timeout=remaining,
                expected_credential_ref=credential,
            )
            data = receipt.data
            if not isinstance(data, InstagramProfile if source == "instagram" else FacebookProfile):
                raise SocialUnavailable()
            calls = receipt.api_requests if source == "instagram" else 1
        except ConnectionUnavailable:
            failure = Failure(
                code="auth_required", message="Reconnect this source and start a fresh run"
            )
        except SocialUnavailable as exc:
            data = None
            failure = Failure.model_validate(
                {
                    "code": "auth_required" if exc.code == "needs_connection" else exc.code,
                    "message": "Source profile read unavailable; review access before a fresh run",
                }
            )
        except (KeyError, ValueError, TypeError):
            data = None
            failure = Failure(
                code="unsupported_operation",
                message="A supported fresh connected named profile reference is required",
            )
        return (
            (data, failure, monotonic() - started, context, receipt),
            Decimal(0),
            {"fetch_attempts": calls},
        )

    def persist(session, result):
        data, failure, elapsed, context, receipt = result
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
            or suppressed(
                session,
                entity_id=entity_id,
                url=attributes["url"],
                native_id=attributes.get("_source_native_id"),
            )
        ):
            return []
        if data is not None:
            try:
                material = store.load_for_runner(session, context, operation)
                if str(material.credential_ref) != attributes["_read_credential_ref"]:
                    raise ConnectionUnavailable()
            except ConnectionUnavailable:
                data = None
                failure = Failure(
                    code="auth_required", message="Source access changed before saving"
                )
        updated = dict(entity["attributes"])
        updated.pop("social_read", None)
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if data is not None and not suppressed(session, url=data.source_url):
            text = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, allow_nan=False)
            body = ("<main><pre>" + escape(text) + "</pre></main>").encode()
            saved = storage.store(
                session,
                body,
                source_url=data.source_url,
                source_platform=source,
                collected_at=data.observed_at,
                excerpt=text[:4096],
            )
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["social_read"] = {
                "evidence_id": str(saved["id"]),
                "resource": data.model_dump(mode="json"),
                "api_requests": receipt.api_requests,
                "network_requests_seen": receipt.network_requests_seen,
            }
            summary.update(
                status="read",
                observed_at=data.observed_at.isoformat(),
                final_url=data.source_url,
                content_hash=saved["content_hash"],
                coverage_complete=False,
                prepared_chunks=0,
                browser_seconds=elapsed,
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
                "source": source,
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
        {"fetch_attempts": maximum_calls},
        lease_seconds=50,
        run_with_deadline=run,
        capacity_kind="browser",
        capacity_source=source,
        capacity_host="www." + source + ".com",
        minimum_interval=2,
        feedback_failure=lambda result: result[1],
    )
