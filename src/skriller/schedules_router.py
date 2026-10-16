"""Explicit owner scheduling; research results require normal review and retrieval."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from skriller.auth import Identity, require_identity
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.scheduling import create_schedule, disable_schedule, resume_schedule, runs, schedules

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/research-schedules")


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    list_id: UUID
    opt_in: bool = Field(strict=True)
    cadence_hours: int = Field(ge=1, le=720, strict=True)
    max_runs: int = Field(ge=1, le=25, strict=True)
    required_connection_ids: list[UUID] = Field(default_factory=list, max_length=9)


class ScheduleOutput(BaseModel):
    id: UUID
    list_id: UUID
    enabled: bool
    cadence_hours: int
    max_runs: int
    run_count: int
    next_due_at: datetime
    last_job_id: UUID | None
    last_reason: str | None
    required_connection_ids: list[UUID]


class RunOutput(BaseModel):
    id: UUID
    schedule_id: UUID
    scheduled_for: datetime
    job_id: UUID


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opt_in: bool = Field(strict=True)


@router.post("/{schedule_id}/resume", response_model=ScheduleOutput)
def resume(
    workspace_id: UUID,
    schedule_id: UUID,
    body: ResumeInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return resume_schedule(session, str(schedule_id), opt_in=body.opt_in)
    except (ValueError, LookupError, WorkspaceAccessDenied) as exc:
        fail(exc)


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        if str(exc) == "Workspace owner permission required":
            raise HTTPException(403, "Workspace owner permission required") from None
        raise HTTPException(404, "Workspace unavailable") from None
    if isinstance(exc, LookupError):
        raise HTTPException(404, "Saved list, source connection or schedule unavailable") from None
    if isinstance(exc, IntegrityError):
        raise HTTPException(409, "A schedule already exists for this saved list") from None
    raise HTTPException(422, "Provide explicit opt-in and a bounded cadence/run limit") from None


@router.post("", response_model=ScheduleOutput, status_code=201)
def create(
    workspace_id: UUID,
    body: ScheduleInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return create_schedule(
                session,
                str(body.list_id),
                opt_in=body.opt_in,
                cadence_hours=body.cadence_hours,
                max_runs=body.max_runs,
                required_connection_ids=tuple(str(value) for value in body.required_connection_ids),
            )
    except (ValueError, LookupError, WorkspaceAccessDenied, IntegrityError) as exc:
        fail(exc)


@router.get("", response_model=list[ScheduleOutput])
def listing(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return [
                dict(row)
                for row in session.execute(
                    sa.select(schedules)
                    .where(schedules.c.workspace_id == scope(session))
                    .order_by(schedules.c.created_at)
                    .limit(10)
                ).mappings()
            ]
    except WorkspaceAccessDenied as exc:
        fail(exc)


@router.delete("/{schedule_id}", status_code=204)
def disable(
    workspace_id: UUID,
    schedule_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            disable_schedule(session, str(schedule_id))
    except (LookupError, WorkspaceAccessDenied) as exc:
        fail(exc)


@router.get("/{schedule_id}/runs", response_model=list[RunOutput])
def history(
    workspace_id: UUID,
    schedule_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return [
                dict(row)
                for row in session.execute(
                    sa.select(runs)
                    .where(
                        runs.c.workspace_id == scope(session),
                        runs.c.schedule_id == str(schedule_id),
                    )
                    .order_by(runs.c.created_at.desc())
                    .limit(25)
                ).mappings()
            ]
    except WorkspaceAccessDenied as exc:
        fail(exc)
