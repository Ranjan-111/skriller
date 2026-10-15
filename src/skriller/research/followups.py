"""Durable follow-up jobs over current qualification evidence only."""

import asyncio
import re
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa

from skriller.contracts import Criterion, ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import (
    attempts,
    followup_reports,
    job_events,
    jobs,
    plans,
    stage_checkpoints,
)
from skriller.entitlements import policy_for, request_denial, used_runs
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import locked_job
from skriller.jobs.control import permit_call, plan_for_job
from skriller.jobs.outbox import submit
from skriller.jobs.worker import TaskIdentity
from skriller.qualification.service import qualify_entity
from skriller.research.reports import ResearchReport, answer_followup
from skriller.research.service import result_rows


def _qualification_evidence(session, source_job, entity_id):
    if source_job["purpose"] != "research" or source_job["state"] not in {"completed", "partial"}:
        raise ValueError("A finished research run is required")
    if entity_id not in {row["id"] for row in result_rows(session, source_job["id"])}:
        raise LookupError("Result unavailable")
    plan = plan_for_job(session, source_job)
    fit = qualify_entity(session, plan, entity_id)
    identifiers = list(
        dict.fromkeys(
            str(evidence_id)
            for group in (fit.essential, fit.exclusions, fit.preferences)
            for criterion in group
            if criterion.outcome in {"matched", "contradicted"}
            for evidence_id in criterion.evidence_ids
        )
    )
    if not identifiers:
        raise ValueError("This result has no current qualification evidence to cite")
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    eligible = []
    for identifier in identifiers:
        row = ResearchRepository.get_evidence(session, identifier)
        if (
            row is not None
            and row["excerpt"]
            and len(row["excerpt"]) <= 300
            and len(row["source_url"]) <= 2048
            and (row["expires_at"] is None or row["expires_at"] > now)
        ):
            eligible.append(identifier)
        if len(eligible) == 5:
            break
    if not eligible:
        raise ValueError("Current qualification evidence exceeds the report bounds")
    return eligible, plan


def create_followup(session, source_job_id, entity_id, question, request_key):
    """Create one scoped queued report with a fresh one-call plan and immutable source."""
    if (
        not isinstance(question, str)
        or not 3 <= len(question.strip()) <= 500
        or len(question.strip().encode()) > 500
    ):
        raise ValueError("A bounded follow-up question is required")
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 170:
        raise ValueError("Invalid follow-up request key")
    key = "followup:" + request_key
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "followup:" + scope(session) + ":" + key},
    )
    existing = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session), jobs.c.idempotency_key == key
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        record = (
            session.execute(
                sa.select(followup_reports).where(
                    followup_reports.c.workspace_id == scope(session),
                    followup_reports.c.job_id == existing["id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            record is None
            or record["source_job_id"] != source_job_id
            or record["entity_id"] != entity_id
            or record["question"] != question.strip()
            or record["created_by"] != session.info["actor_id"]
        ):
            raise ValueError("Follow-up request key belongs to another question")
        return dict(existing)
    source = JobRepository.get(session, source_job_id)
    if source is None:
        raise LookupError("Research run unavailable")
    evidence_ids, source_plan = _qualification_evidence(session, source, entity_id)
    policy = policy_for(session)
    if not policy["enabled"] or used_runs(session) >= policy["run_limit"]:
        raise ValueError("Workspace run allowance is exhausted")
    conversation = ConversationRepository.create(session, "Research follow-up")
    ConversationRepository.add_message(session, conversation["id"], "user", question.strip())
    plan = SearchPlan.model_validate(
        {
            **source_plan.model_dump(mode="json"),
            "conversation_id": conversation["id"],
            "revision": 1,
            "limits": Limits(
                result_limit=1,
                search_calls=0,
                fetch_attempts=0,
                llm_calls=1,
                token_cap=4096,
                deadline_seconds=120,
            ).model_dump(mode="json"),
        }
    )
    revision = ConversationRepository.revise_plan(
        session, conversation["id"], plan.model_dump(mode="json")
    )
    job = submit(session, conversation["id"], revision["id"], key)
    session.execute(
        sa.update(jobs)
        .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
        .values(purpose="followup")
    )
    insert_row(
        session,
        followup_reports,
        job_id=job["id"],
        source_job_id=source_job_id,
        entity_id=entity_id,
        question=question.strip(),
        evidence_ids=evidence_ids,
        status="pending",
        citation_hashes={},
        unknowns=[],
        created_by=session.info["actor_id"],
    )
    return {**job, "purpose": "followup"}


def expand_research(session, source_job_id, prompt, request_key):
    """Only a user request may start the registered discovery pipeline as a new run."""
    if (
        not isinstance(prompt, str)
        or not 3 <= len(prompt.strip()) <= 1500
        or len(prompt.strip().encode()) > 1500
    ):
        raise ValueError("A bounded research prompt is required")
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 170:
        raise ValueError("Invalid expansion request key")
    key = "expand:" + request_key
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "expand:" + scope(session) + ":" + key},
    )
    existing = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session), jobs.c.idempotency_key == key
            )
        )
        .mappings()
        .one_or_none()
    )
    digest = sha256(prompt.strip().encode()).hexdigest()
    if existing is not None:
        event = session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.workspace_id == scope(session),
                job_events.c.job_id == existing["id"],
                job_events.c.event_key == "source_expansion",
            )
        ).scalar_one_or_none()
        if existing["created_by"] != session.info["actor_id"] or event != {
            "source_job_id": source_job_id,
            "prompt_sha256": digest,
        }:
            raise ValueError("Expansion request key belongs to another prompt")
        return dict(existing)
    source = JobRepository.get(session, source_job_id)
    if source is None:
        raise LookupError("Research run unavailable")
    if source["purpose"] != "research" or source["state"] not in {"completed", "partial"}:
        raise ValueError("A finished research run is required")
    source_plan = plan_for_job(session, source)
    policy = policy_for(session)
    if request_denial(
        policy, result_limit=source_plan.limits.result_limit, sources=source_plan.sources
    ):
        raise ValueError("Workspace settings limit this expansion")
    if used_runs(session) >= policy["run_limit"]:
        raise ValueError("Workspace run allowance is exhausted")
    conversation = ConversationRepository.create(session, "Expanded research")
    ConversationRepository.add_message(session, conversation["id"], "user", prompt.strip())
    plan = SearchPlan.model_validate(
        {
            **source_plan.model_dump(mode="json"),
            "conversation_id": conversation["id"],
            "revision": 1,
        }
    )
    revision = ConversationRepository.revise_plan(
        session, conversation["id"], plan.model_dump(mode="json")
    )
    job = submit(session, conversation["id"], revision["id"], key)
    JobRepository.event(
        session,
        job["id"],
        "source_expansion",
        "research_expansion",
        {"source_job_id": source_job_id, "prompt_sha256": digest},
    )
    return job


def refine_research(session, source_job_id, prompt, request_key, *, enable_model=False):
    """Apply only an explicit supported refinement to a new immutable plan revision."""
    normalized = prompt.strip().casefold().rstrip(".!")
    company_type = {
        "exclude agencies": "agency",
        "without agencies": "agency",
        "exclude agency companies": "agency",
        "exclude consultancies": "consultancy",
        "without consultancies": "consultancy",
    }.get(normalized)
    relaxation = re.fullmatch(r"relax must-have ([a-z][a-z0-9_]*) (.+)", normalized)
    model_refinement = company_type is None and relaxation is None
    if model_refinement and not enable_model:
        raise ValueError(
            "This refinement needs clarification; try 'Exclude agencies' or "
            "'Relax must-have location India'"
        )
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 170:
        raise ValueError("Invalid refinement request key")
    key = "refine:" + request_key
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "refine:" + scope(session) + ":" + key},
    )
    digest = sha256(prompt.strip().encode()).hexdigest()
    existing = (
        session.execute(
            sa.select(jobs).where(
                jobs.c.workspace_id == scope(session), jobs.c.idempotency_key == key
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        details = session.execute(
            sa.select(job_events.c.details).where(
                job_events.c.workspace_id == scope(session),
                job_events.c.job_id == existing["id"],
                job_events.c.event_key == "source_refinement",
            )
        ).scalar_one_or_none()
        if existing["created_by"] != session.info["actor_id"] or details != {
            "source_job_id": source_job_id,
            "prompt_sha256": digest,
        }:
            raise ValueError("Refinement request key belongs to another prompt")
        return dict(existing)
    source = JobRepository.get(session, source_job_id)
    if source is None:
        raise LookupError("Research run unavailable")
    if source["purpose"] != "research" or source["state"] not in {"completed", "partial"}:
        raise ValueError("A finished research run is required")
    parent = ConversationRepository.get_plan(session, source["plan_id"])
    original = SearchPlan.model_validate(parent["interpretation"])
    latest = session.execute(
        sa.select(sa.func.max(plans.c.revision)).where(
            plans.c.workspace_id == scope(session),
            plans.c.conversation_id == source["conversation_id"],
        )
    ).scalar_one()
    if latest != parent["revision"]:
        raise ValueError("Refine the latest plan rather than an older run")
    revised_values = original.model_dump(mode="json")
    if company_type is not None:
        criterion = Criterion(field="company_type", operator="eq", value=company_type)
        if any(
            item.field == criterion.field
            and item.operator == criterion.operator
            and str(item.value).casefold() == company_type
            for item in original.exclusions
        ):
            raise ValueError("This exclusion is already in the current plan")
        revised_values["exclusions"] = [*original.exclusions, criterion]
    elif relaxation is not None:
        assert relaxation is not None
        field, value = relaxation.groups()
        matches = [
            item
            for item in original.must_have
            if item.field == field and str(item.value).casefold() == value
        ]
        if len(matches) != 1:
            raise ValueError("Name exactly one existing must-have criterion to relax")
        revised_values["must_have"] = [item for item in original.must_have if item != matches[0]]
    else:
        if original.limits.llm_calls < 1 or original.limits.token_cap < 4096:
            raise ValueError("This run has no model planning allowance; name an exact criterion")
        revised_values["limits"] = original.limits.model_copy(
            update={
                "llm_calls": 1,
                "token_cap": 4096,
                "fetch_attempts": 0,
                "currency_cap": Decimal(0),
            }
        )
    revised = SearchPlan.model_validate(
        {
            **revised_values,
            "revision": original.revision + 1,
        }
    )
    policy = policy_for(session)
    if request_denial(policy, result_limit=revised.limits.result_limit, sources=revised.sources):
        raise ValueError("Workspace settings limit this refinement")
    if used_runs(session) >= policy["run_limit"]:
        raise ValueError("Workspace run allowance is exhausted")
    message = ConversationRepository.add_message(
        session, source["conversation_id"], "user", prompt.strip()
    )
    revision = ConversationRepository.revise_plan(
        session, source["conversation_id"], revised.model_dump(mode="json"), parent_id=parent["id"]
    )
    job = submit(session, source["conversation_id"], revision["id"], key)
    JobRepository.event(
        session,
        job["id"],
        "source_refinement",
        "research_refinement",
        {"source_job_id": source_job_id, "prompt_sha256": digest},
    )
    if model_refinement:
        session.execute(
            sa.update(jobs)
            .where(jobs.c.workspace_id == scope(session), jobs.c.id == job["id"])
            .values(purpose="planning")
        )
        JobRepository.event(
            session,
            job["id"],
            "refinement_context",
            "refinement_context",
            {"message_id": message["id"]},
        )
        return {**job, "purpose": "planning"}
    return job


def followup_view(session, job_id):
    job = JobRepository.get(session, job_id)
    record = (
        session.execute(
            sa.select(followup_reports).where(
                followup_reports.c.workspace_id == scope(session),
                followup_reports.c.job_id == job_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if job is None or job["purpose"] != "followup" or record is None:
        raise LookupError("Follow-up unavailable")
    status = record["status"]
    unknowns = list(record["unknowns"])
    observations: list[dict[str, object]] = []
    if status == "answered":
        source = JobRepository.get(session, record["source_job_id"])
        try:
            current, _ = _qualification_evidence(session, source, record["entity_id"])
        except (LookupError, ValueError, TypeError):
            current = []
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        hashes = record["citation_hashes"]
        if (
            not isinstance(hashes, dict)
            or not hashes
            or len(hashes) > 5
            or not set(hashes) <= set(current)
        ):
            status, unknowns = "unknown", ["evidence_no_longer_accessible"]
        else:
            for identifier, digest in hashes.items():
                row = ResearchRepository.get_evidence(session, identifier)
                if (
                    row is None
                    or not row["excerpt"]
                    or (row["expires_at"] is not None and row["expires_at"] <= now)
                    or sha256(row["excerpt"].encode()).hexdigest() != digest
                ):
                    status, unknowns, observations = (
                        "unknown",
                        ["evidence_no_longer_accessible"],
                        [],
                    )
                    break
                observations.append(
                    {
                        "evidence_id": identifier,
                        "quote": row["excerpt"],
                        "source_url": row["source_url"],
                        "source_platform": row["source_platform"],
                        "collected_at": row["collected_at"],
                        "excerpt_sha256": digest,
                        "qualification": "source_statement_not_independently_verified",
                    }
                )
    if status == "pending" and job["state"] in {"paused", "failed", "cancelled"}:
        status, unknowns = "unknown", ["report_unavailable"]
    return {
        "job_id": job_id,
        "source_job_id": record["source_job_id"],
        "entity_id": record["entity_id"],
        "state": job["state"],
        "status": status,
        "observations": observations,
        "unknowns": unknowns,
        "coverage_complete": False,
        "inference_status": "unavailable",
        "expansion_status": "unavailable",
    }


def _report_attempt(session, identity):
    row = (
        session.execute(
            sa.select(attempts)
            .where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == str(identity.job_id),
                attempts.c.id == str(identity.attempt_id),
                attempts.c.stage == "reporting",
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Report attempt unavailable")
    return row


def execute_followup(database, payload, model=None):
    """Lease once; a lost model call is never retried with a second charge."""
    identity = TaskIdentity.model_validate(payload)
    if identity.attempt_id is None:
        raise ValueError("Report attempt identity required")
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = _report_attempt(session, identity)
        if attempt["state"] == "succeeded":
            return {"status": "checkpointed"}
        if job["purpose"] != "followup" or job["state"] not in {"queued", "running"}:
            return {"status": "not_dispatchable"}
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if attempt["state"] == "running":
            if attempt["lease_expires_at"] > now:
                return {"status": "leased"}
            session.execute(
                sa.update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(state="failed", finished_at=now)
            )
            JobRepository.transition(
                session, job["id"], "paused", failure_code="report_interrupted"
            )
            return {"status": "report_interrupted"}
        if attempt["state"] != "pending" or permit_call(session, job["id"]) <= 0:
            return {"status": "not_dispatchable"}
        record = (
            session.execute(
                sa.select(followup_reports).where(
                    followup_reports.c.workspace_id == scope(session),
                    followup_reports.c.job_id == job["id"],
                )
            )
            .mappings()
            .one()
        )
        token, generation = str(uuid4()), attempt["generation"] + 1
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == attempt["id"])
            .values(
                state="running",
                lease_owner=token,
                lease_expires_at=now + timedelta(seconds=115),
                generation=generation,
                started_at=now,
            )
        )
        JobRepository.transition(session, job["id"], "running", stage="reporting")
        plan = plan_for_job(session, job)
        context = ExecutionContext(
            workspace_id=identity.workspace_id,
            job_id=identity.job_id,
            actor_id=identity.actor_id,
            plan_revision=plan.revision,
            deadline=job["created_at"] + timedelta(seconds=plan.limits.deadline_seconds),
            attempt_budget=1,
            attempt_id=identity.attempt_id,
        )
        question = record["question"]
        evidence_ids = tuple(record["evidence_ids"])
    try:
        report: ResearchReport = asyncio.run(
            answer_followup(
                database,
                context,
                question,
                evidence_ids,
                operation_key=f"followup:{identity.attempt_id}",
                model=model if model is not None else LocalStructuredModel(),
            )
        )
    except Exception:  # noqa: BLE001 - no prompt/provider payload in durable diagnostics
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            attempt = _report_attempt(session, identity)
            if attempt["lease_owner"] == token and job["state"] in {"queued", "running"}:
                session.execute(
                    sa.update(attempts)
                    .where(attempts.c.id == attempt["id"])
                    .values(state="failed", finished_at=sa.func.clock_timestamp())
                )
                JobRepository.transition(
                    session, job["id"], "paused", failure_code="report_interrupted"
                )
        return {"status": "report_interrupted"}
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = locked_job(session, str(identity.job_id))
        attempt = _report_attempt(session, identity)
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            attempt["lease_owner"] != token
            or attempt["lease_expires_at"] <= now
            or job["state"] not in {"queued", "running"}
            or permit_call(session, job["id"]) <= 0
        ):
            return {"status": "lost_lease"}
        hashes = {item.evidence_id: item.excerpt_sha256 for item in report.observations}
        session.execute(
            sa.update(followup_reports)
            .where(
                followup_reports.c.workspace_id == scope(session),
                followup_reports.c.job_id == job["id"],
            )
            .values(status=report.status, citation_hashes=hashes, unknowns=list(report.unknowns))
        )
        session.execute(
            sa.update(attempts)
            .where(attempts.c.id == attempt["id"])
            .values(state="succeeded", finished_at=now, result_entity_ids=[])
        )
        insert_row(
            session,
            stage_checkpoints,
            job_id=job["id"],
            attempt_id=attempt["id"],
            generation=generation,
            stage="reporting",
            result_refs={"report_id": record["id"]},
        )
        JobRepository.transition(session, job["id"], "completed", stage="reporting")
        JobRepository.event(
            session,
            job["id"],
            f"followup:{attempt['id']}",
            "followup_summary",
            {"status": report.status, "citation_count": len(hashes)},
        )
        return {"status": "checkpointed", "report_status": report.status}
