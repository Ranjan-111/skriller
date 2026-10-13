"""Authenticated conversation submission and persisted discovery results."""

from datetime import datetime
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
from skriller.db.schema import conversations, jobs, messages, plans
from skriller.jobs.control import cancel
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


class QueryProvenance(Contract):
    source: Source
    original_url: str = Field(max_length=4096)
    query: str = Field(max_length=2000)
    rank: int = Field(ge=1)
    provider: Literal["exa_keyless"]
    observed_at: datetime
    evidence_kind: Literal["search_snippet"]


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
                previous_plan = ConversationRepository.get_plan(session, existing["plan_id"])
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
                fetch_attempts=0,
                llm_calls=0,
                token_cap=0,
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
