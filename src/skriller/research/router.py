"""Authenticated conversation submission and persisted discovery results."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import Field

from skriller.auth import Identity, require_identity
from skriller.contracts import (
    Contract,
    JobSnapshot,
    JobState,
    Limits,
    SearchPlan,
    Source,
    default_sources,
)
from skriller.db import ConversationRepository, JobRepository, WorkspaceAccessDenied
from skriller.db.schema import conversations, jobs, messages, plans, stage_checkpoints
from skriller.jobs.budget import stage_observation_report, usage_report
from skriller.jobs.control import cancel, resume
from skriller.jobs.outbox import submit
from skriller.research.service import LIMITATIONS, dispatch, locate, personal_workspace, result_rows

router = APIRouter(prefix="/v1")


class ConversationInput(Contract):
    title: str = Field(default="Research", min_length=1, max_length=200)


class ResearchOptions(Contract):
    mode: Literal["leads", "research"] = "leads"
    sources: list[Source] = Field(default_factory=default_sources, min_length=1, max_length=9)
    result_limit: int = Field(default=25, ge=1, le=100)


class MessageInput(Contract):
    content: str = Field(min_length=3, max_length=1500)
    options: ResearchOptions = Field(default_factory=ResearchOptions)


class ConversationOutput(Contract):
    id: UUID
    workspace_id: UUID


class SubmissionOutput(Contract):
    message_id: UUID
    plan_id: UUID
    job_id: UUID
    workspace_id: UUID
    limitations: list[str]


class ResearchSnapshot(JobSnapshot):
    result_count: int = Field(ge=0, le=100)


class PlanView(Contract):
    job_id: UUID
    plan_id: UUID
    interpretation: SearchPlan
    status: Literal[
        "search_objective",
        "planning",
        "ready",
        "clarification_required",
        "unsupported_criteria",
        "rejected",
        "stopped",
    ]


class StageMetric(Contract):
    stage: str = Field(min_length=1, max_length=50)
    source: str = Field(min_length=1, max_length=100)
    observations: int = Field(ge=1)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    accepted_result_count: int = Field(ge=0)
    stage_io_seconds: str
    confirmed_cost_usd: str
    estimated_cost_usd: str
    unpriced_observations: int = Field(ge=0)


class JobUsage(Contract):
    job_id: UUID
    workspace_id: UUID
    currency: Literal["USD"] = "USD"
    budget_cap_usd: str
    confirmed_cost_usd: str
    estimated_cost_usd: str
    reserved_cost_usd: str
    exposure_ceiling_usd: str
    remaining_budget_usd: str
    dimensions: dict[str, dict[str, int]]
    stage_metrics: list[StageMetric] = Field(max_length=100)
    invalid_stage_observations: int = Field(ge=0)
    stage_metrics_truncated: bool


class QueryProvenance(Contract):
    source: Source
    original_url: str = Field(max_length=4096)
    query: str = Field(max_length=2000)
    rank: int = Field(ge=1)
    provider: Literal["exa_keyless"]
    observed_at: datetime
    evidence_kind: Literal["search_snippet"]


class CollectionView(Contract):
    status: Literal["read", "unavailable", "preparation_failed"]
    failure_code: str | None
    observed_at: datetime | None = None
    final_url: str | None = None
    content_hash: str | None = None
    network_seconds: float | None = None
    parser_seconds: float | None = None
    browser_seconds: float | None = None
    coverage_complete: bool | None = None
    prepared_chunks: int | None = None


class PageObservation(Contract):
    claim_id: UUID
    field: str = Field(max_length=40)
    value: str | int | float | bool
    quote: str = Field(max_length=4096)
    status: Literal["unverified", "conflict", "accepted"]


class ExtractionView(Contract):
    status: Literal["observed", "unavailable"]
    failure_code: str | None
    observations: list[PageObservation] = Field(max_length=60)
    rejected_claims: int = Field(ge=0)
    coverage_complete: bool
    omitted_chunks: int = Field(ge=0)
    expired_observations: int = Field(default=0, ge=0)


class ResearchCandidate(Contract):
    id: UUID
    title: str = Field(max_length=300)
    url: str = Field(max_length=4096)
    snippet: str = Field(max_length=4096)
    source: Source
    provider: Literal["exa_keyless"]
    evidence_kind: Literal["search_snippet"]
    qualification: Literal["unverified"]
    observed_at: datetime
    provenance: list[QueryProvenance] = Field(max_length=200)
    collection: CollectionView | None = None
    extraction: ExtractionView | None = None


class ResearchResults(Contract):
    job_id: UUID
    workspace_id: UUID
    state: JobState
    results: list[ResearchCandidate] = Field(max_length=100)
    limitations: list[str]


def safe_dispatch(database, broker_url, actor, workspace):
    try:
        dispatch(database, broker_url, actor, workspace)
    except Exception:  # noqa: BLE001 - durable outbox remains queued; never log credentials
        return False
    return True


@router.post("/conversations", status_code=201, response_model=ConversationOutput)
def create_conversation(
    body: ConversationInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    database = request.app.state.database
    workspace = personal_workspace(database, identity.uid)
    with database.tenant(identity.uid, str(workspace["id"])) as session:
        conversation = ConversationRepository.create(session, body.title)
    return {"id": conversation["id"], "workspace_id": str(workspace["id"])}


@router.post(
    "/conversations/{conversation_id}/messages", status_code=202, response_model=SubmissionOutput
)
def message(
    conversation_id: UUID,
    body: MessageInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    if request.app.state.search_provider is None:
        raise HTTPException(503, "Search discovery is disabled")
    if not body.content.strip():
        raise HTTPException(422, "A search objective is required")
    database = request.app.state.database
    try:
        workspace, _ = locate(database, identity.uid, ConversationRepository, conversation_id)
    except (LookupError, WorkspaceAccessDenied) as exc:
        raise HTTPException(404, "Conversation unavailable") from exc
    with database.tenant(identity.uid, workspace) as session:
        session.execute(
            sa.select(conversations.c.id)
            .where(
                conversations.c.workspace_id == workspace,
                conversations.c.id == str(conversation_id),
            )
            .with_for_update()
        ).scalar_one()
        if idempotency_key:
            existing = (
                session.execute(
                    sa.select(jobs).where(
                        jobs.c.workspace_id == workspace,
                        jobs.c.idempotency_key == idempotency_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                previous_plan = (
                    session.execute(
                        sa.select(plans)
                        .where(
                            plans.c.workspace_id == workspace,
                            plans.c.conversation_id == str(conversation_id),
                        )
                        .order_by(plans.c.revision)
                        .limit(1)
                    )
                    .mappings()
                    .one()
                )
                previous_message = (
                    session.execute(
                        sa.select(messages)
                        .where(
                            messages.c.workspace_id == workspace,
                            messages.c.conversation_id == str(conversation_id),
                            messages.c.role == "user",
                        )
                        .order_by(messages.c.sequence)
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    existing["conversation_id"] != str(conversation_id)
                    or previous_plan["interpretation"]["entity_type"]
                    != ("person" if body.options.mode == "leads" else "discussion")
                    or previous_message is None
                    or previous_message["content"] != body.content.strip()
                    or previous_plan["interpretation"]["sources"] != body.options.sources
                    or previous_plan["interpretation"]["limits"]["result_limit"]
                    != body.options.result_limit
                ):
                    raise HTTPException(409, "Idempotency key belongs to another objective")
                background.add_task(
                    safe_dispatch,
                    database,
                    request.app.state.settings.broker_url,
                    identity.uid,
                    workspace,
                )
                return {
                    "message_id": previous_message["id"],
                    "plan_id": existing["plan_id"],
                    "job_id": existing["id"],
                    "workspace_id": workspace,
                    "limitations": LIMITATIONS,
                }
        previous = (
            session.execute(
                sa.select(plans)
                .where(
                    plans.c.workspace_id == workspace,
                    plans.c.conversation_id == str(conversation_id),
                )
                .order_by(plans.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        # Until refinement semantics land, each conversation accepts one immutable request.
        if previous is not None:
            raise HTTPException(409, "Start a new conversation for another research objective")
        from skriller.entitlements import policy_for, request_denial, used_runs

        policy = policy_for(session)
        if request_denial(
            policy, result_limit=body.options.result_limit, sources=body.options.sources
        ):
            raise HTTPException(
                422,
                "Workspace settings limit this request; reduce result or source count, or ask the owner to review execution settings",
                headers={"X-Skriller-Failure": "entitlement_limits"},
            )
        if used_runs(session) >= policy["run_limit"]:
            raise HTTPException(
                429, "Workspace run quota exhausted; ask the owner to review the pilot allowance"
            )
        record = ConversationRepository.add_message(
            session, str(conversation_id), "user", body.content.strip()
        )
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=conversation_id,
            revision=1,
            entity_type="person" if body.options.mode == "leads" else "discussion",
            sources=body.options.sources,
            requested_fields=["title", "url", "snippet"],
            limits=Limits(
                result_limit=body.options.result_limit,
                search_calls=len(body.options.sources),
                fetch_attempts=min(30, body.options.result_limit * 3)
                if request.app.state.settings.public_collection_proxy_url
                and not request.app.state.settings.enable_ai_planning
                else 0,
                llm_calls=min(10, body.options.result_limit * 2)
                if request.app.state.settings.enable_page_extraction
                else 1
                if request.app.state.settings.enable_ai_planning
                else 0,
                token_cap=40960
                if request.app.state.settings.enable_page_extraction
                else 4096
                if request.app.state.settings.enable_ai_planning
                else 0,
                deadline_seconds=120,
            ),
        )
        revision = ConversationRepository.revise_plan(
            session, str(conversation_id), plan.model_dump(mode="json")
        )
        job = submit(
            session,
            str(conversation_id),
            revision["id"],
            idempotency_key or f"message:{record['id']}:{uuid4()}",
        )
        if request.app.state.settings.enable_ai_planning:
            session.execute(
                sa.update(jobs)
                .where(jobs.c.workspace_id == workspace, jobs.c.id == job["id"])
                .values(purpose="planning")
            )
    background.add_task(
        safe_dispatch, database, request.app.state.settings.broker_url, identity.uid, workspace
    )
    return {
        "message_id": record["id"],
        "plan_id": revision["id"],
        "job_id": job["id"],
        "workspace_id": workspace,
        "limitations": LIMITATIONS,
    }


def read_job(request, identity, job_id, workspace_id):
    try:
        return locate(request.app.state.database, identity.uid, JobRepository, job_id, workspace_id)
    except (LookupError, WorkspaceAccessDenied) as exc:
        raise HTTPException(404, "Job unavailable") from exc


@router.get("/jobs/{job_id}/plan", response_model=PlanView)
def job_plan(
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, job = read_job(request, identity, job_id, workspace_id)
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        revision = ConversationRepository.get_plan(session, job["plan_id"])
        interpreted = (
            session.execute(
                sa.select(stage_checkpoints.c.id).where(
                    stage_checkpoints.c.workspace_id == workspace,
                    stage_checkpoints.c.job_id == str(job_id),
                    stage_checkpoints.c.stage == "planning",
                )
            ).first()
            is not None
        )
    plan = SearchPlan.model_validate(revision["interpretation"])
    if interpreted:
        status = (
            "clarification_required"
            if plan.clarification
            else "unsupported_criteria"
            if plan.unsupported_criteria
            else "ready"
        )
    elif job["purpose"] == "planning":
        status = (
            "stopped"
            if job["state"] == "cancelled"
            else "rejected"
            if job["state"] == "paused"
            else "planning"
        )
    else:
        status = "search_objective"
    return {"job_id": job_id, "plan_id": job["plan_id"], "interpretation": plan, "status": status}


@router.get("/jobs/{job_id}/usage", response_model=JobUsage)
def job_usage(
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, job = read_job(request, identity, job_id, workspace_id)
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        plan_row = ConversationRepository.get_plan(session, job["plan_id"])
        plan = SearchPlan.model_validate(plan_row["interpretation"])
        amounts, dimensions = usage_report(session, str(job_id))
        stage_metrics, invalid_observations, metrics_truncated = stage_observation_report(
            session, str(job_id)
        )
    exposure = sum(amounts.values(), Decimal(0))
    remaining = max(Decimal(0), plan.limits.currency_cap - exposure)

    def money_text(amount):
        return format(amount.normalize(), "f")

    return {
        "job_id": job_id,
        "workspace_id": workspace,
        "currency": "USD",
        "budget_cap_usd": money_text(plan.limits.currency_cap),
        "confirmed_cost_usd": money_text(amounts["confirmed"]),
        "estimated_cost_usd": money_text(amounts["estimated"]),
        "reserved_cost_usd": money_text(amounts["reserved"]),
        "exposure_ceiling_usd": money_text(exposure),
        "remaining_budget_usd": money_text(remaining),
        "dimensions": dimensions,
        "stage_metrics": [
            {
                **{
                    name: metric[name]
                    for name in (
                        "stage",
                        "source",
                        "observations",
                        "succeeded",
                        "failed",
                        "accepted_result_count",
                        "unpriced_observations",
                    )
                },
                "stage_io_seconds": money_text(metric["stage_io_seconds"]),
                "confirmed_cost_usd": money_text(metric["confirmed_cost_usd"]),
                "estimated_cost_usd": money_text(metric["estimated_cost_usd"]),
            }
            for metric in stage_metrics
        ],
        "invalid_stage_observations": invalid_observations,
        "stage_metrics_truncated": metrics_truncated,
    }


@router.get("/jobs/{job_id}", response_model=ResearchSnapshot)
def job_snapshot(
    job_id: UUID,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, job = read_job(request, identity, job_id, workspace_id)
    if job["state"] == "queued":
        background.add_task(
            safe_dispatch,
            request.app.state.database,
            request.app.state.settings.broker_url,
            identity.uid,
            workspace,
        )
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        count = len(result_rows(session, str(job_id)))
    return {
        **{
            key: job[key]
            for key in ("id", "workspace_id", "state", "stage", "version", "terminal_reason")
        },
        "result_count": count,
    }


@router.get("/jobs/{job_id}/results", response_model=ResearchResults)
def results(
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, job = read_job(request, identity, job_id, workspace_id)
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        rows = result_rows(session, str(job_id))
        summaries = [
            event["details"]
            for event in JobRepository.events_after(session, str(job_id), limit=1000)
            if event["kind"] == "discovery_summary"
        ]
    limitations = list(LIMITATIONS)
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        planning = [
            event["details"]
            for event in JobRepository.events_after(session, str(job_id), limit=1000)
            if event["kind"] == "planning_summary"
        ]
        plan = ConversationRepository.get_plan(session, job["plan_id"])["interpretation"]
    for event in planning:
        if event["status"] != "ready":
            limitations.append("Planning stopped: " + event["status"].replace("_", " ") + ".")
    if plan.get("clarification"):
        limitations.append("Clarification required: " + plan["clarification"])
    for summary in summaries:
        for failure in summary.get("source_failures", []):
            limitations.append(
                f"{failure['source']}: search interrupted ({failure['code'].replace('_', ' ')})."
            )
        if summary.get("query_warnings"):
            limitations.append(
                "Search operators and candidate matches still require source evidence; "
                "search does not prove that all requested criteria match."
            )
    return {
        "job_id": str(job_id),
        "workspace_id": workspace,
        "state": job["state"],
        "results": rows,
        "limitations": list(dict.fromkeys(limitations)),
    }


@router.post("/jobs/{job_id}/cancel", response_model=JobSnapshot)
def cancel_job(
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, _job = read_job(request, identity, job_id, workspace_id)
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        job = cancel(session, str(job_id))
    return {
        key: job[key]
        for key in ("id", "workspace_id", "state", "stage", "version", "terminal_reason")
    }


@router.post("/jobs/{job_id}/resume", response_model=JobSnapshot)
def resume_job(
    job_id: UUID,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    workspace_id: UUID | None = None,
):
    workspace, _job = read_job(request, identity, job_id, workspace_id)
    if request.app.state.search_provider is None:
        raise HTTPException(503, "Search discovery is disabled")
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            job = resume(session, str(job_id), idempotency_key)
    except ValueError:
        raise HTTPException(
            409,
            "This run cannot resume with its existing deadline, budget or pending work. "
            "Resolve its requirements or start a new run.",
        ) from None
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        workspace,
    )
    return {
        key: job[key]
        for key in ("id", "workspace_id", "state", "stage", "version", "terminal_reason")
    }
