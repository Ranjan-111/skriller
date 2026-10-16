"""Authenticated conversation submission and persisted discovery results."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from pydantic import Field, field_validator, model_validator

from skriller.auth import Identity, require_identity
from skriller.connectors.platform_references import PlatformReference
from skriller.connectors.youtube import YouTubeVideoEvidence
from skriller.contracts import (
    Contract,
    JobSnapshot,
    JobState,
    Limits,
    SearchPlan,
    Source,
    default_sources,
)
from skriller.db import (
    ConversationRepository,
    JobRepository,
    ResearchRepository,
    WorkspaceAccessDenied,
)
from skriller.db.schema import (
    claim_evidence,
    conversations,
    jobs,
    messages,
    plans,
    stage_checkpoints,
)
from skriller.jobs.budget import stage_observation_report, usage_report
from skriller.jobs.control import ResumeStatus, cancel, resume, resume_readiness
from skriller.jobs.outbox import submit
from skriller.qualification.criteria import Fit
from skriller.research.bootstrap import create_clarification_job
from skriller.research.followups import (
    create_followup,
    expand_research,
    followup_view,
    refine_research,
)
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


class ConversationListOutput(ConversationOutput):
    title: str
    created_at: datetime


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


class ComponentTimings(Contract):
    observations: int = Field(ge=0)
    network_seconds: str | None
    network_samples: int = Field(ge=0)
    parser_seconds: str | None
    parser_samples: int = Field(ge=0)
    browser_seconds: str | None
    browser_samples: int = Field(ge=0)

    @model_validator(mode="after")
    def bounded_samples(self):
        from decimal import Decimal

        for component in ("network", "parser", "browser"):
            samples = getattr(self, f"{component}_samples")
            raw = getattr(self, f"{component}_seconds")
            if (samples == 0) != (raw is None) or samples > self.observations:
                raise ValueError("Component timing samples exceed their observation denominator")
            if raw is not None:
                try:
                    value = Decimal(raw)
                except Exception as error:
                    raise ValueError("Invalid component timing") from error
                if not value.is_finite() or not 0 <= value <= Decimal(180 * samples):
                    raise ValueError("Component timing exceeds its bounded sample duration")
        return self


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
    outcomes: dict[str, int] = Field(max_length=16)
    correlated_attempt_observations: int = Field(ge=0)
    queue_wait_seconds: str
    queue_wait_samples: int = Field(ge=0)
    collection_timings: ComponentTimings | None = None

    @field_validator("outcomes")
    @classmethod
    def bounded_outcomes(cls, value):
        from skriller.jobs.budget import STAGE_OUTCOMES

        if any(
            key not in STAGE_OUTCOMES or isinstance(count, bool) or count < 0
            for key, count in value.items()
        ):
            raise ValueError("Invalid stage outcome counts")
        return value

    @model_validator(mode="after")
    def outcome_denominator(self):
        if (
            sum(self.outcomes.values()) != self.observations
            or self.correlated_attempt_observations > self.observations
            or self.queue_wait_samples > self.observations
            or (
                self.collection_timings is not None
                and self.collection_timings.observations > self.observations
            )
            or self.succeeded != self.outcomes.get("succeeded", 0)
            or self.failed != self.observations - self.succeeded
        ):
            raise ValueError("Stage outcome counts exceed their observed denominator")
        return self


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
    provider: Literal["exa_keyless", "x_api_v2"]
    observed_at: datetime
    evidence_kind: Literal["search_snippet", "public_post"]


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
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=10)


class ExtractionView(Contract):
    status: Literal["observed", "unavailable"]
    failure_code: str | None
    observations: list[PageObservation] = Field(max_length=60)
    rejected_claims: int = Field(ge=0)
    coverage_complete: bool
    omitted_chunks: int = Field(ge=0)
    expired_observations: int = Field(default=0, ge=0)


class FeedEntryView(Contract):
    entry_id: str = Field(max_length=4096)
    title: str = Field(max_length=1000)
    url: str = Field(max_length=4096)
    published_at: datetime | None
    updated_at: datetime | None
    summary: str = Field(max_length=4096)
    summary_truncated: bool


class FeedView(Contract):
    feed_url: str = Field(max_length=4096)
    entries: list[FeedEntryView] = Field(max_length=20)
    duplicate_count: int = Field(ge=0)
    invalid_link_count: int = Field(ge=0)
    omitted_entry_count: int = Field(ge=0)
    evidence_expired: bool


class DiscussionView(Contract):
    resource_kind: Literal["post", "comment"]
    evidence_kind: Literal["indexed_reference"]
    author_handle: None = None
    author_identity: Literal["unknown"] = "unknown"


class YouTubeCaptionView(Contract):
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(max_length=4000)
    evidence_id: UUID
    claim_id: UUID


class YouTubeView(Contract):
    metadata: YouTubeVideoEvidence | None
    metadata_truncated: bool
    caption_status: Literal[
        "retrieved", "unavailable", "unsupported_format_or_language", "read_failed"
    ]
    caption_origin: Literal["provided", "platform_automatic"] | None
    caption_language: Literal["en", "en-orig", "en-US", "en-GB"] | None
    segments: list[YouTubeCaptionView] = Field(max_length=20)
    omitted_segments: int = Field(ge=0)
    subject_identity: Literal["unknown"]
    evidence_expired: bool


class ResearchCandidate(Contract):
    id: UUID
    title: str = Field(max_length=300)
    url: str = Field(max_length=4096)
    snippet: str = Field(max_length=4096)
    source: Source
    provider: Literal["exa_keyless", "x_api_v2"]
    evidence_kind: Literal["search_snippet", "public_post"]
    qualification: Literal["unverified"]
    fit: Fit | None = None
    observed_at: datetime
    provenance: list[QueryProvenance] = Field(max_length=200)
    collection: CollectionView | None = None
    extraction: ExtractionView | None = None
    feed: FeedView | None = None
    discussion: DiscussionView | None = None
    platform_reference: PlatformReference | None = None
    youtube: YouTubeView | None = None


class QualificationGroups(Contract):
    confirmed: list[UUID] = Field(max_length=100)
    near_match: list[UUID] = Field(max_length=100)
    excluded: list[UUID] = Field(max_length=100)
    unverified: list[UUID] = Field(max_length=100)


class ResearchResults(Contract):
    job_id: UUID
    workspace_id: UUID
    state: JobState
    results: list[ResearchCandidate] = Field(max_length=100)
    limitations: list[str]
    groups: QualificationGroups | None = None
    resume_status: ResumeStatus = "not_paused"


class EvidenceCitation(Contract):
    id: UUID
    source_url: str = Field(max_length=4096)
    source_platform: Source
    collected_at: datetime
    expires_at: datetime | None
    excerpt: str = Field(max_length=4096)
    excerpt_truncated: bool
    content_hash: str | None
    content_hash_status: Literal["stored_metadata_not_revalidated"]


class FollowupInput(Contract):
    entity_id: UUID
    question: str = Field(min_length=3, max_length=500)


class ExpansionInput(Contract):
    prompt: str = Field(min_length=3, max_length=1500)


class RefinementInput(Contract):
    prompt: str = Field(min_length=3, max_length=500)


class ClarificationInput(Contract):
    answer: str = Field(min_length=1, max_length=500)


class FollowupSubmission(Contract):
    job_id: UUID
    workspace_id: UUID
    state: JobState


class FollowupObservation(Contract):
    evidence_id: UUID
    quote: str = Field(max_length=300)
    source_url: str = Field(max_length=2048)
    source_platform: Source
    collected_at: datetime
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification: Literal["source_statement_not_independently_verified"]


class FollowupView(Contract):
    job_id: UUID
    source_job_id: UUID
    entity_id: UUID
    state: JobState
    status: Literal["pending", "answered", "unknown"]
    observations: list[FollowupObservation] = Field(max_length=5)
    unknowns: list[str] = Field(max_length=10)
    coverage_complete: Literal[False]
    inference_status: Literal["unavailable"]
    expansion_status: Literal["unavailable"]


def safe_dispatch(database, broker_url, actor, workspace):
    try:
        dispatch(database, broker_url, actor, workspace)
    except Exception:  # noqa: BLE001 - durable outbox remains queued; never log credentials
        return False
    return True


@router.post("/jobs/{job_id}/followups", status_code=202, response_model=FollowupSubmission)
def submit_followup(
    job_id: UUID,
    body: FollowupInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=170)] = None,
):
    workspace, _ = read_job(request, identity, job_id, workspace_id)
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            job = create_followup(
                session,
                str(job_id),
                str(body.entity_id),
                body.question,
                idempotency_key or str(uuid4()),
            )
    except LookupError:
        raise HTTPException(404, "Research result unavailable") from None
    except ValueError as exc:
        status = 429 if "allowance" in str(exc) else 409 if "key belongs" in str(exc) else 422
        raise HTTPException(status, str(exc)) from None
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        workspace,
    )
    return {"job_id": job["id"], "workspace_id": workspace, "state": job["state"]}


@router.get("/jobs/{job_id}/report", response_model=FollowupView)
def read_followup_report(
    job_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, _ = read_job(request, identity, job_id, workspace_id)
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            return followup_view(session, str(job_id))
    except LookupError:
        raise HTTPException(404, "Follow-up unavailable") from None


@router.post("/jobs/{job_id}/expand", status_code=202, response_model=FollowupSubmission)
def submit_expansion(
    job_id: UUID,
    body: ExpansionInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=170)] = None,
):
    workspace, _ = read_job(request, identity, job_id, workspace_id)
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            job = expand_research(
                session,
                str(job_id),
                body.prompt,
                idempotency_key or str(uuid4()),
            )
    except LookupError:
        raise HTTPException(404, "Research run unavailable") from None
    except ValueError as exc:
        status = 429 if "allowance" in str(exc) else 409 if "key belongs" in str(exc) else 422
        raise HTTPException(status, str(exc)) from None
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        workspace,
    )
    return {"job_id": job["id"], "workspace_id": workspace, "state": job["state"]}


@router.post("/jobs/{job_id}/refine", status_code=202, response_model=FollowupSubmission)
def submit_refinement(
    job_id: UUID,
    body: RefinementInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=170)] = None,
):
    workspace, _ = read_job(request, identity, job_id, workspace_id)
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            job = refine_research(
                session,
                str(job_id),
                body.prompt,
                idempotency_key or str(uuid4()),
                enable_model=request.app.state.settings.enable_ai_planning,
            )
    except LookupError:
        raise HTTPException(404, "Research run unavailable") from None
    except ValueError as exc:
        status = (
            429
            if "allowance" in str(exc)
            else 409
            if "key belongs" in str(exc) or "latest plan" in str(exc)
            else 422
        )
        raise HTTPException(status, str(exc)) from None
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        workspace,
    )
    return {"job_id": job["id"], "workspace_id": workspace, "state": job["state"]}


@router.post("/jobs/{job_id}/clarifications", status_code=202, response_model=FollowupSubmission)
def submit_clarification(
    job_id: UUID,
    body: ClarificationInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=170)] = None,
):
    workspace, _ = read_job(request, identity, job_id, workspace_id)
    try:
        with request.app.state.database.tenant(identity.uid, workspace) as session:
            job = create_clarification_job(
                session, str(job_id), body.answer, idempotency_key or str(uuid4())
            )
    except LookupError:
        raise HTTPException(404, "Research run unavailable") from None
    except ValueError as exc:
        status = 409 if "request key belongs" in str(exc) else 422
        raise HTTPException(status, str(exc)) from None
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        workspace,
    )
    return {"job_id": job["id"], "workspace_id": workspace, "state": job["state"]}


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
    workspace_id: UUID | None = None,
):
    if request.app.state.search_provider is None:
        raise HTTPException(503, "Search discovery is disabled")
    if not body.content.strip():
        raise HTTPException(422, "A search objective is required")
    database = request.app.state.database
    try:
        workspace, _ = locate(
            database, identity.uid, ConversationRepository, conversation_id, workspace_id
        )
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
                llm_calls=1
                if request.app.state.settings.enable_ai_planning
                else min(10, body.options.result_limit * 2)
                if request.app.state.settings.enable_page_extraction
                else 0,
                token_cap=4096
                if request.app.state.settings.enable_ai_planning
                else 40960
                if request.app.state.settings.enable_page_extraction
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


@router.get("/workspaces/{workspace_id}/conversations", response_model=list[ConversationListOutput])
def list_conversations(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return (
                session.execute(
                    sa.select(
                        conversations.c.id,
                        conversations.c.workspace_id,
                        conversations.c.title,
                        conversations.c.created_at,
                    )
                    .where(conversations.c.workspace_id == str(workspace_id))
                    .order_by(conversations.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


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
                        "correlated_attempt_observations",
                        "queue_wait_samples",
                    )
                },
                "outcomes": {name: count for name, count in metric["outcomes"].items() if count},
                "stage_io_seconds": money_text(metric["stage_io_seconds"]),
                "queue_wait_seconds": money_text(metric["queue_wait_seconds"]),
                "collection_timings": (
                    {
                        "observations": metric["collection_timings"]["observations"],
                        **{
                            f"{component}_{field}": (
                                money_text(metric["collection_timings"][f"{component}_seconds"])
                                if field == "seconds"
                                and metric["collection_timings"][f"{component}_seconds"] is not None
                                else metric["collection_timings"][f"{component}_samples"]
                                if field == "samples"
                                else None
                            )
                            for component in ("network", "parser", "browser")
                            for field in ("seconds", "samples")
                        },
                    }
                    if metric["collection_timings"] is not None
                    else None
                ),
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
        resume_status = resume_readiness(session, job)
        from skriller.research.refinements import refinement_source

        if refinement_source(session, str(job_id)) is not None:
            limitations.append(
                "Refinement coverage is limited to candidates and evidence retained by the original run."
            )
    for event in planning:
        if event["status"] != "ready":
            limitations.append("Planning stopped: " + event["status"].replace("_", " ") + ".")
    if plan.get("clarification"):
        limitations.append("Clarification required: " + plan["clarification"])
    if job["failure_code"] == "checkpoint_failed":
        limitations.append(
            "Research paused because a result could not be saved. Previously saved results remain "
            "available; call usage is retained. This run requires reconciliation before resuming."
        )
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
        "resume_status": resume_status,
        "results": rows,
        "groups": {
            status: [
                row["id"]
                for row in rows
                if (row.get("fit") or {}).get("status", "unverified") == status
            ]
            for status in ("confirmed", "near_match", "excluded", "unverified")
        },
        "limitations": list(dict.fromkeys(limitations)),
    }


@router.get("/jobs/{job_id}/evidence/{evidence_id}", response_model=EvidenceCitation)
def cited_evidence(
    job_id: UUID,
    evidence_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
    workspace_id: UUID | None = None,
):
    workspace, _job = read_job(request, identity, job_id, workspace_id)
    response.headers["Cache-Control"] = "private, no-store"
    with request.app.state.database.tenant(identity.uid, workspace) as session:
        rows = result_rows(session, str(job_id))
        permitted = set()
        observed_claims = []
        for row in rows:
            fit = row.get("fit") or {}
            for group in ("essential", "exclusions", "preferences"):
                for result in fit.get(group, []):
                    permitted.update(result["evidence_ids"])
            for observation in (row.get("extraction") or {}).get("observations", []):
                observed_claims.append(observation["claim_id"])
        if observed_claims:
            permitted.update(
                session.execute(
                    sa.select(claim_evidence.c.evidence_id).where(
                        claim_evidence.c.workspace_id == workspace,
                        claim_evidence.c.claim_id.in_(observed_claims),
                    )
                ).scalars()
            )
        record = (
            ResearchRepository.get_evidence(session, str(evidence_id))
            if str(evidence_id) in permitted
            else None
        )
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            record is None
            or not record["excerpt"]
            or record["expires_at"] is not None
            and record["expires_at"] <= now
            or record["source_platform"] not in {"web", "github", "rss", "youtube"}
        ):
            # Account-backed evidence requires the separate source-access integration.
            raise HTTPException(404, "Current cited evidence unavailable")
        excerpt = record["excerpt"]
        return {
            "id": record["id"],
            "source_url": record["source_url"],
            "source_platform": record["source_platform"],
            "collected_at": record["collected_at"],
            "expires_at": record["expires_at"],
            "excerpt": excerpt[:4096],
            "excerpt_truncated": len(excerpt) > 4096,
            "content_hash": record["content_hash"],
            "content_hash_status": "stored_metadata_not_revalidated",
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
    stage = _job["stage"] or {
        "planning": "planning",
        "followup": "reporting",
        "template_repair": "extracting",
    }.get(_job["purpose"], "discovering")
    if stage == "discovering" and request.app.state.search_provider is None:
        raise HTTPException(503, "Search discovery is disabled")
    if stage == "collecting" and not request.app.state.settings.public_collection_proxy_url:
        raise HTTPException(503, "Source collection is disabled")
    if stage == "extracting" and not request.app.state.settings.enable_page_extraction:
        raise HTTPException(503, "Page extraction is disabled")
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
