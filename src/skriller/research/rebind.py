"""Explicit owner consent to replace credentials for undispatched collection work."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import Field, model_validator

from skriller.connections.store import ConnectionUnavailable
from skriller.connections.tables import connections, proxy_routes
from skriller.contracts import Contract, ExecutionContext
from skriller.db import JobRepository, WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import attempts, entities, job_events
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.budget import locked_job
from skriller.jobs.control import (
    ResumeStatus,
    permit_call,
    plan_for_job,
    remaining_seconds,
    resume,
    resume_readiness,
)


def pause_for_read_connection(database, identity, store, readers):
    """Keep known stale native read work pending before any reservation or I/O."""
    if store is None:
        return None
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        if job["created_by"] != identity.actor_id:
            raise WorkspaceAccessDenied("Only the initiating actor can admit this read")
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
            .one_or_none()
        )
        if (
            attempt is None
            or attempt["state"] != "pending"
            or attempt["reservation_id"]
            or job["state"] not in {"queued", "running"}
            or remaining_seconds(session, job) <= 0
        ):
            return None
        identifier = attempt["logical_key"].removeprefix("collecting:")
        attributes = session.execute(
            sa.select(entities.c.attributes).where(
                entities.c.workspace_id == scope(session),
                entities.c.id == identifier,
            )
        ).scalar_one_or_none()
        if not attributes or not readers.get(attributes.get("source")):
            return None
        source = attributes["source"]
        if attributes.get("provider") != {"linkedin": "linkedin_mcp", "reddit": "reddit_oauth"}.get(
            source
        ):
            return None
        discovered = (
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
        if not any(identifier in batch for batch in discovered):
            raise LookupError("Candidate is outside this discovery checkpoint")
        if permit_call(session, job["id"]) <= 0:
            return {"status": "not_dispatchable"}
        plan = plan_for_job(session, job)
        try:
            context = ExecutionContext(
                workspace_id=UUID(scope(session)),
                job_id=UUID(job["id"]),
                actor_id=identity.actor_id,
                plan_revision=plan.revision,
                connection_ref=UUID(attributes["_read_connection_ref"]),
                attempt_id=identity.attempt_id,
                attempt_budget=1,
                deadline=job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds),
            )
            material = store.load_for_runner(
                session,
                context,
                {
                    "linkedin": "linkedin_resource_read",
                    "reddit": "reddit_oauth_read",
                }[source],
            )
            if str(material.credential_ref) != attributes["_read_credential_ref"]:
                raise ConnectionUnavailable()
        except (ConnectionUnavailable, KeyError, ValueError, TypeError):
            JobRepository.transition(session, job["id"], "paused", failure_code="auth_required")
            JobRepository.event(
                session,
                job["id"],
                f"connection:required:{attempt['id']}:{job['version']}",
                "connection_required",
                {"source": source, "dispatched": False},
            )
            return {"status": "connection_required"}
    return None


class RebindSourceOption(Contract):
    source: Literal["linkedin", "reddit"]
    previous_connection_ref: UUID
    entity_ids: list[UUID] = Field(min_length=1, max_length=100)


class RebindOptionsView(Contract):
    job_id: UUID
    job_version: int = Field(ge=1)
    resume_status: ResumeStatus
    options: list[RebindSourceOption] = Field(max_length=2)
    confirmation_required: Literal[True] = True


def rebind_options(session, job):
    """Advisory opaque selection metadata; mutation rechecks every admission rule."""
    require_owner(session)
    if job["created_by"] != session.info["actor_id"]:
        raise WorkspaceAccessDenied("Only the initiating owner can inspect bindings")
    status = resume_readiness(session, job)
    view = RebindOptionsView(
        job_id=job["id"], job_version=job["version"], resume_status=status, options=[]
    )
    if status != "available" or job["stage"] != "collecting" or job["purpose"] != "research":
        return view
    pending = (
        session.execute(
            sa.select(attempts).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job["id"],
                attempts.c.stage == "collecting",
                attempts.c.state == "pending",
            )
        )
        .mappings()
        .all()
    )
    ids = {row["logical_key"].removeprefix("collecting:") for row in pending}
    rows = (
        session.execute(
            sa.select(entities).where(
                entities.c.workspace_id == scope(session),
                entities.c.id.in_(sorted(ids)),
            )
        )
        .mappings()
        .all()
    )
    for source, provider in (("linkedin", "linkedin_mcp"), ("reddit", "reddit_oauth")):
        group = [
            row
            for row in rows
            if row["attributes"].get("source") == source
            and row["attributes"].get("provider") == provider
        ]
        refs = {row["attributes"].get("_read_connection_ref") for row in group}
        if (
            not group
            or len(refs) != 1
            or any(
                row["attributes"].get("erased")
                or row["attributes"].get("collection") is not None
                or not row["attributes"].get("_read_credential_ref")
                or suppressed(session, entity_id=row["id"], url=row["attributes"].get("url"))
                for row in group
            )
        ):
            continue
        try:
            view.options.append(
                RebindSourceOption(
                    source=cast(Literal["linkedin", "reddit"], source),
                    previous_connection_ref=UUID(next(iter(refs))),
                    entity_ids=sorted(row["id"] for row in group),
                )
            )
        except (ValueError, TypeError):
            continue
    return view


class RebindResumeInput(Contract):
    source: Literal["linkedin", "reddit"]
    previous_connection_ref: UUID
    replacement_connection_ref: UUID
    expected_job_version: int = Field(ge=1)
    entity_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_entities(self):
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("Duplicate candidates are not allowed")
        return self


def rebind_and_resume(session, job_id, request_key, selection: RebindResumeInput, store):
    """Caller owns the transaction: binding and queue transition commit together.

    No source calls or pagination cursors are replayed. A replacement is checked
    through the same trusted runner admission used at dispatch, and later dispatch
    must still pass all current authority and generation checks.
    """
    require_owner(session)
    job = locked_job(session, job_id)
    actor = session.info["actor_id"]
    if job["created_by"] != actor:
        raise WorkspaceAccessDenied("Only the initiating owner can rebind this run")
    if not request_key or len(request_key) > 200:
        raise ValueError("Bounded request key required")
    fingerprint = hashlib.sha256(
        json.dumps(selection.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    key = "control:rebind:" + hashlib.sha256(request_key.encode()).hexdigest()
    prior = session.execute(
        sa.select(job_events.c.details).where(
            job_events.c.workspace_id == scope(session),
            job_events.c.job_id == job_id,
            job_events.c.event_key == key,
        )
    ).scalar_one_or_none()
    if prior is not None:
        if prior.get("fingerprint") != fingerprint:
            raise ValueError("Rebind request key was already used for another selection")
        return dict(job)
    if (
        job["version"] != selection.expected_job_version
        or job["stage"] != "collecting"
        or job["purpose"] != "research"
        or resume_readiness(session, job) != "available"
    ):
        raise ValueError("This checkpoint cannot be rebound")
    ids = {str(value) for value in selection.entity_ids}
    pending = (
        session.execute(
            sa.select(attempts).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job_id,
                attempts.c.stage == "collecting",
                attempts.c.state == "pending",
            )
        )
        .mappings()
        .all()
    )
    by_entity = {row["logical_key"].removeprefix("collecting:"): row for row in pending}
    if not ids <= by_entity.keys() or any(by_entity[value]["reservation_id"] for value in ids):
        raise ValueError("Only undispatched collection candidates can be rebound")
    discovery = (
        session.execute(
            sa.select(attempts.c.result_entity_ids).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job_id,
                attempts.c.stage == "discovering",
                attempts.c.state == "succeeded",
            )
        )
        .scalars()
        .all()
    )
    if not ids <= {value for batch in discovery for value in batch}:
        raise ValueError("Candidate is outside the discovery checkpoint")
    # Match initiating ownership for both platforms, including co-owner callers.
    owner = session.execute(
        sa.select(connections.c.created_by).where(
            connections.c.workspace_id == scope(session),
            connections.c.id == str(selection.replacement_connection_ref),
        )
    ).scalar_one_or_none()
    if owner != actor:
        raise WorkspaceAccessDenied("Replacement connection is not owned by the initiator")
    privacy_lock(session)
    rows = (
        session.execute(
            sa.select(entities)
            .where(
                entities.c.workspace_id == scope(session),
                entities.c.id.in_(sorted(ids)),
            )
            .order_by(entities.c.id)
            .with_for_update()
        )
        .mappings()
        .all()
    )
    if len(rows) != len(ids):
        raise ValueError("Candidate unavailable")
    provider = {"linkedin": "linkedin_mcp", "reddit": "reddit_oauth"}[selection.source]
    pending_attributes = session.execute(
        sa.select(entities.c.id, entities.c.attributes).where(
            entities.c.workspace_id == scope(session),
            entities.c.id.in_(list(by_entity)),
        )
    ).all()
    source_pending = {
        identifier
        for identifier, attributes in pending_attributes
        if attributes.get("source") == selection.source and attributes.get("provider") == provider
    }
    if ids != source_pending:
        raise ValueError("Select all pending candidates for this connected source")
    for row in rows:
        attributes = row["attributes"]
        if (
            attributes.get("source") != selection.source
            or attributes.get("provider") != provider
            or attributes.get("_read_connection_ref") != str(selection.previous_connection_ref)
            or not attributes.get("_read_credential_ref")
            or attributes.get("collection") is not None
            or attributes.get("erased")
            or suppressed(session, entity_id=row["id"], url=attributes.get("url"))
        ):
            raise ValueError("Candidate cannot change its saved read binding")
    result = resume(session, job_id, "rebind:" + hashlib.sha256(request_key.encode()).hexdigest())
    plan = plan_for_job(session, job)
    runner = {"linkedin": "linkedin_resource_read", "reddit": "reddit_oauth_read"}[selection.source]
    context = ExecutionContext(
        workspace_id=UUID(scope(session)),
        job_id=UUID(job_id),
        actor_id=actor,
        plan_revision=plan.revision,
        connection_ref=selection.replacement_connection_ref,
        attempt_id=UUID(by_entity[min(ids)]["id"]),
        attempt_budget=1,
        deadline=min(
            job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds),
            datetime.now(UTC) + timedelta(seconds=30),
        ),
    )
    material = store.load_for_runner(session, context, runner)
    if material.credential_ref is None:
        raise ValueError("Replacement generation unavailable")
    route = (
        session.execute(
            sa.select(proxy_routes)
            .where(
                proxy_routes.c.workspace_id == scope(session),
                proxy_routes.c.job_id == job_id,
                proxy_routes.c.source == selection.source,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if route is not None:
        if (
            route["account_connection_id"] != str(selection.previous_connection_ref)
            or route["failed"]
        ):
            raise ValueError("Existing task route cannot be rebound")
        # Preserve provider choice, traffic/attempt usage and configuration digest.
        session.execute(
            sa.update(proxy_routes)
            .where(
                proxy_routes.c.workspace_id == scope(session),
                proxy_routes.c.id == route["id"],
            )
            .values(account_connection_id=str(material.connection_ref))
        )
    for row in rows:
        attributes = dict(row["attributes"])
        if attributes["_read_connection_ref"] == str(material.connection_ref) and attributes[
            "_read_credential_ref"
        ] == str(material.credential_ref):
            raise ValueError("Replacement must change the saved generation")
        attributes.update(
            _read_connection_ref=str(material.connection_ref),
            _read_credential_ref=str(material.credential_ref),
        )
        session.execute(
            sa.update(entities)
            .where(
                entities.c.workspace_id == scope(session),
                entities.c.id == row["id"],
            )
            .values(attributes=attributes)
        )
    JobRepository.event(
        session,
        job_id,
        key,
        "connection_rebound",
        {
            "fingerprint": fingerprint,
            "source": selection.source,
            "candidate_count": len(ids),
        },
    )
    return result
