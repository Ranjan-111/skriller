"""One local-model repair job over owner-selected saved evidence; review before activation."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import Field

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope
from skriller.contracts import Contract, ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import entities, jobs
from skriller.entitlements import policy_for, used_runs
from skriller.erasure import privacy_lock, suppressed
from skriller.extraction.adaptive import validate_field
from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.repair import PreservedPage, _check, repair_mapping
from skriller.jobs.budget import locked_job
from skriller.jobs.outbox import submit
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.research.adaptive_templates import ReviewedTemplate
from skriller.research.template_registry import publish_template, selected_templates
from skriller.storage import BlobIntegrityError, BlobUnavailable


class RepairInput(Contract):
    expected_version: int = Field(ge=1, le=999999, strict=True)
    field_identifier: str = Field(min_length=1, max_length=200)
    current_evidence_id: UUID
    regression_evidence_ids: list[UUID] = Field(min_length=1, max_length=8)


class RepairView(Contract):
    job_id: UUID
    workspace_id: UUID
    template_id: UUID
    status: Literal["pending", "ready_for_review", "unknown", "approved"]
    reason: str | None
    proposal: ReviewedTemplate | None


def _record(session, job_id):
    row = (
        session.execute(
            sa.select(entities)
            .where(
                entities.c.workspace_id == scope(session),
                entities.c.kind == "other",
                entities.c.canonical_key == "template-repair:" + str(job_id),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    job = JobRepository.get(session, str(job_id))
    if (
        row is None
        or job is None
        or job["purpose"] != "template_repair"
        or row["attributes"].get("erased")
    ):
        raise LookupError("Repair request unavailable")
    return row, dict(row["attributes"])


def _evidence(session, identifier, source_url):
    row = ResearchRepository.get_evidence(session, str(identifier))
    if (
        row is None
        or row["source_url"] != source_url
        or row["source_platform"] != "web"
        or not row["object_key"]
        or not row["content_hash"]
        or row["expires_at"] is not None
        and row["expires_at"] <= datetime.now(UTC)
        or suppressed(session, url=source_url)
    ):
        raise BlobUnavailable("Saved repair evidence unavailable")
    return row


def _pages(session, storage, data):
    template = ReviewedTemplate.model_validate(data["template"])
    inputs = RepairInput.model_validate(data["input"])
    pages = []
    for index, identifier in enumerate(
        [inputs.current_evidence_id, *inputs.regression_evidence_ids]
    ):
        row = _evidence(session, identifier, template.source_url)
        raw = storage.retrieve(session, str(identifier))
        if len(raw) > (2048 if index == 0 else 2 * 1024 * 1024):
            raise ValueError("Preserved repair markup exceeds bounds")
        pages.append(PreservedPage(raw.decode("utf-8"), row["source_url"], row["content_hash"]))
    return template, inputs, pages


def create_repair(session, template_id, inputs: RepairInput, request_key):
    require_owner(session)
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 160:
        raise ValueError("Bounded repair request key required")
    key = "template-repair:" + request_key
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": key + ":" + scope(session)},
    )
    existing = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session),
                jobs.c.idempotency_key == key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        _, data = _record(session, existing["id"])
        if (
            data["input"] != inputs.model_dump(mode="json")
            or data["template"]["template_id"] != str(template_id)
            or existing["created_by"] != session.info["actor_id"]
        ):
            raise ValueError("Repair key belongs to another request")
        return existing
    template = next(
        (item for item in selected_templates(session) if item.template_id == template_id), None
    )
    if template is None:
        raise LookupError("Reviewed template unavailable")
    if (
        template.template_version != inputs.expected_version
        or not any(item.identifier == inputs.field_identifier for item in template.fields)
        or len(set(inputs.regression_evidence_ids)) != len(inputs.regression_evidence_ids)
        or inputs.current_evidence_id in inputs.regression_evidence_ids
    ):
        raise ValueError("Repair selection is invalid or stale")
    privacy_lock(session)
    for identifier in [inputs.current_evidence_id, *inputs.regression_evidence_ids]:
        _evidence(session, identifier, template.source_url)
    policy = policy_for(session)
    if not policy["enabled"] or used_runs(session) >= policy["run_limit"]:
        raise ValueError("Workspace run allowance is exhausted")
    conversation = ConversationRepository.create(session, "Review selector repair")
    plan = SearchPlan(
        workspace_id=UUID(scope(session)),
        conversation_id=UUID(conversation["id"]),
        revision=1,
        entity_type="company",
        sources=["web"],
        limits=Limits(
            result_limit=1,
            candidates=1,
            search_calls=0,
            fetch_attempts=0,
            llm_calls=1,
            token_cap=8192,
            deadline_seconds=120,
        ),
    )
    revision = ConversationRepository.revise_plan(
        session, conversation["id"], plan.model_dump(mode="json")
    )
    job = submit(session, conversation["id"], revision["id"], key)
    session.execute(
        sa.update(jobs)
        .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
        .values(purpose="template_repair")
    )
    ResearchRepository.entity(
        session,
        "other",
        "Selector repair request",
        canonical_key="template-repair:" + job["id"],
        attributes={
            "input": inputs.model_dump(mode="json"),
            "template": template.model_dump(mode="json"),
            "status": "pending",
            "reason": None,
            "proposal": None,
        },
    )
    return {**job, "purpose": "template_repair"}


def repair_view(session, job_id):
    require_owner(session)
    _, data = _record(session, job_id)
    job = JobRepository.get(session, str(job_id))
    if data["status"] == "pending" and job["state"] in {"cancelled", "paused", "failed"}:
        data = {**data, "status": "unknown", "reason": "job_interrupted", "proposal": None}
    return RepairView(
        job_id=job_id,
        workspace_id=scope(session),
        template_id=data["template"]["template_id"],
        status=data["status"],
        reason=data["reason"],
        proposal=data["proposal"],
    )


def _update(session, row, data):
    session.execute(
        sa.update(entities)
        .where(entities.c.workspace_id == scope(session), entities.c.id == row["id"])
        .values(attributes=data)
    )


def approve_repair(session, storage, job_id, expected_version):
    require_owner(session)
    locked_job(session, str(job_id))
    privacy_lock(session)
    row, data = _record(session, job_id)
    if expected_version != data["input"]["expected_version"]:
        raise ValueError("Repair approval version mismatch")
    if data["status"] == "approved":
        return repair_view(session, job_id)
    if data["status"] != "ready_for_review" or data["proposal"] is None:
        raise ValueError("No verified repair proposal is available")
    template, inputs, pages = _pages(session, storage, data)
    if expected_version != inputs.expected_version:
        raise ValueError("Repair approval version mismatch")
    proposal = ReviewedTemplate.model_validate(data["proposal"])
    for page in pages:
        for item in proposal.fields:
            if (
                item.identifier == inputs.field_identifier
                and _check(page, item.rule(), item.css)[0] is None
            ):
                raise ValueError("Repair regression no longer passes")
    publish_template(session, proposal, expected_version=template.template_version)
    _update(session, row, {**data, "status": "approved"})
    JobRepository.event(session, str(job_id), "repair:approved", "template_repair_approved")
    return repair_view(session, job_id)


def execute_template_repair(database, payload, *, storage, model=None):
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Repair attempt required")
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        require_owner(session)
        _, data = _record(session, job["id"])
        created = job["created_at"]

    def run(plan, timeout_seconds):
        context = ExecutionContext(
            workspace_id=identity.workspace_id,
            job_id=identity.job_id,
            actor_id=identity.actor_id,
            plan_revision=plan.revision,
            attempt_id=identity.attempt_id,
            attempt_budget=1,
            deadline=min(
                created + timedelta(seconds=plan.limits.deadline_seconds),
                datetime.now(UTC) + timedelta(seconds=max(0, timeout_seconds - 1)),
            ),
        )
        try:
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                require_owner(session)
                privacy_lock(session)
                template, inputs, pages = _pages(session, storage, data)
            field = next(
                item for item in template.fields if item.identifier == inputs.field_identifier
            )
            rule = field.rule()
            baseline_scope = StorageScope(
                context.workspace_id,
                "web",
                "public",
                template.template_id,
                template.template_version,
            )
            baseline = PostgreSQLStorageSystem(
                database, context.actor_id, baseline_scope, template.source_url
            )
            if baseline.retrieve(rule.identifier) is None:
                old = next(
                    (page for page in pages[1:] if _check(page, rule, rule.css)[0] is not None),
                    None,
                )
                if old is None:
                    return (
                        ("unknown", "baseline_regression_required", None),
                        Decimal(0),
                        {"llm_calls": 0},
                    )
                validate_field(
                    old.html,
                    old.source_url,
                    database=database,
                    context=context,
                    storage_scope=baseline_scope,
                    rule=rule,
                )
            result = asyncio.run(
                repair_mapping(
                    database,
                    context,
                    baseline_scope,
                    rule,
                    pages[0],
                    tuple(pages[1:]),
                    model=model if model is not None else LocalStructuredModel(),
                    operation_key="repair:" + str(identity.attempt_id),
                )
            )
            proposal = None
            if result.status == "promoted":
                proposal = template.model_dump(mode="json")
                proposal["template_version"] = result.scope.template_version
                for item in proposal["fields"]:
                    if item["identifier"] == inputs.field_identifier:
                        item["css"] = result.rule.css
                proposal = ReviewedTemplate.model_validate(proposal).model_dump(mode="json")
            return (
                ("ready_for_review" if proposal else "unknown", result.reason, proposal),
                Decimal(0),
                {"llm_calls": 0},
            )
        except (BlobUnavailable, BlobIntegrityError, UnicodeError, ValueError):
            return ("unknown", "saved_evidence_unavailable", None), Decimal(0), {"llm_calls": 0}

    def persist(session, result):
        require_owner(session)
        privacy_lock(session)
        row, latest = _record(session, str(identity.job_id))
        try:
            template, _, _ = _pages(session, storage, latest)
            active = next(
                (
                    item
                    for item in selected_templates(session)
                    if item.template_id == template.template_id
                ),
                None,
            )
            if active != template:
                result = ("unknown", "active_template_changed", None)
        except (BlobUnavailable, BlobIntegrityError, UnicodeError, ValueError):
            result = ("unknown", "saved_evidence_unavailable", None)
        status, reason, proposal = result
        _update(session, row, {**latest, "status": status, "reason": reason, "proposal": proposal})
        JobRepository.event(
            session,
            str(identity.job_id),
            "repair:proposal",
            "template_repair_proposed",
            {"status": status},
        )
        # Internal proposal records are not discovered candidates or export rows.
        return []

    handler = StageHandler(
        run, persist, Decimal(0), {"llm_calls": 0}, lease_seconds=115, run_with_deadline=run
    )
    outcome = CheckpointWorker(database, {"extracting": handler}).execute(payload)
    if outcome["status"] == "checkpointed":
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            if job["state"] in {"running", "queued"}:
                JobRepository.transition(session, job["id"], "completed", stage="extracting")
    return outcome
