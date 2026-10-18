"""One owner-bound resource read per durable LinkedIn collection attempt."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from time import monotonic
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.store import ConnectionUnavailable
from skriller.connectors.linkedin_executor import LinkedInUnavailable
from skriller.connectors.linkedin_read import request_for_url
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.worker import StageHandler


def linkedin_collection_handler(
    database, identity, attributes, entity_id, storage, created_at, reader, store
):
    def run(plan, timeout_seconds):
        data = context = None
        failure = None
        calls = 0
        started = monotonic()
        try:
            if reader is None or store is None or attributes.get("provider") != "linkedin_mcp":
                raise ConnectionUnavailable("needs_connection")
            request = request_for_url(attributes["url"])
            connection = UUID(attributes["_read_connection_ref"])
            credential = UUID(attributes["_read_credential_ref"])
            remaining = min(40, timeout_seconds - 2)
            if remaining <= 0:
                raise LinkedInUnavailable()
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
                material = store.load_for_runner(session, context, "linkedin_resource_read")
                if material.credential_ref != credential:
                    raise ConnectionUnavailable("needs_connection")
            calls = 1
            data = reader.read(
                request,
                database=database,
                store=store,
                context=context,
                timeout=remaining,
                expected_credential_ref=credential,
            )
        except ConnectionUnavailable:
            failure = Failure(
                code="auth_required", message="Reconnect LinkedIn and start a fresh run"
            )
        except LinkedInUnavailable as exc:
            failure = Failure.model_validate(
                {
                    "code": exc.code,
                    "message": "LinkedIn resource read unavailable; check source access before a fresh run",
                }
            )
        except (KeyError, ValueError):
            failure = Failure(
                code="unsupported_operation",
                message="A supported fresh connected LinkedIn reference is required",
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
                material = store.load_for_runner(session, context, "linkedin_resource_read")
                if str(material.credential_ref) != attributes["_read_credential_ref"]:
                    raise ConnectionUnavailable("needs_connection")
            except ConnectionUnavailable:
                data = None
                failure = Failure(
                    code="auth_required", message="LinkedIn access changed before saving"
                )
        updated = dict(entity["attributes"])
        updated.pop("linkedin_read", None)
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if data is not None and not suppressed(session, url=data.source_url):
            # The saved graph receives escaped content, never source-authored HTML/instructions.
            body = (
                "<main>"
                + "".join(
                    "<p>" + escape(line) + "</p>" for line in data.text.splitlines() if line.strip()
                )
                + "</main>"
            ).encode()
            saved = storage.store(
                session,
                body,
                source_url=data.source_url,
                source_platform="linkedin",
                collected_at=data.observed_at,
                excerpt=data.text[:4096],
            )
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["linkedin_read"] = {
                "evidence_id": str(saved["id"]),
                "resource": data.model_dump(mode="json"),
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
                "source": "linkedin",
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
        lease_seconds=50,
        run_with_deadline=run,
        capacity_kind="browser",
        capacity_source="linkedin",
        capacity_host="www.linkedin.com",
        minimum_interval=2,
        feedback_failure=lambda result: result[1],
    )
