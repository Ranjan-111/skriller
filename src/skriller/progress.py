"""Tenant-authorised persisted snapshots and resumable server-sent events."""

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from skriller.auth import Identity, require_identity
from skriller.contracts import JobSnapshot, ProgressEvent
from skriller.db import Database, JobRepository, WorkspaceAccessDenied

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/jobs")
TERMINAL = {"completed", "partial", "failed", "cancelled"}


def database_for(request: Request) -> Database:
    return request.app.state.database


def read_batch(database, actor, workspace, job_id, cursor):
    try:
        with database.tenant(actor, str(workspace)) as session:
            job = JobRepository.get(session, str(job_id))
            if job is None:
                raise HTTPException(404, "Job unavailable")
            events = [dict(row) for row in JobRepository.events_after(session, str(job_id), cursor)]
            return dict(job), events
    except WorkspaceAccessDenied as exc:
        raise HTTPException(404, "Job unavailable") from exc


def reject_query_credentials(request):
    if any(
        name.lower() in {"token", "access_token", "authorization", "api_key"}
        for name in request.query_params
    ):
        raise HTTPException(400, "Use the Authorization header for sign-in")


@router.get("/{job_id}", response_model=JobSnapshot)
async def snapshot(
    workspace_id: UUID,
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    database: Annotated[Database, Depends(database_for)],
):
    reject_query_credentials(request)
    job, _events = await asyncio.to_thread(
        read_batch, database, identity.uid, workspace_id, job_id, 0
    )
    # Counts, qualifications and results are not invented by the transport.
    return JobSnapshot.model_validate({name: job[name] for name in JobSnapshot.model_fields})


@router.get(
    "/{job_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def events(
    workspace_id: UUID,
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
    database: Annotated[Database, Depends(database_for)],
    last_event_id: Annotated[str | None, Header()] = None,
):
    reject_query_credentials(request)
    try:
        cursor = int(last_event_id or "0")
        if cursor < 0 or cursor > 2**63 - 1:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, "Invalid progress cursor") from exc
    # Authorise before sending response headers; repeat membership checks on each poll.
    first = await asyncio.to_thread(
        read_batch, database, identity.uid, workspace_id, job_id, cursor
    )

    async def stream():
        nonlocal cursor
        job, batch = first
        while True:
            for row in batch:
                cursor = row["sequence"]
                payload = json.dumps(
                    ProgressEvent(kind=row["kind"], details=row["details"]).model_dump(mode="json"),
                    separators=(",", ":"),
                )
                yield f"id: {cursor}\nevent: progress\ndata: {payload}\n\n"
            if job["state"] in TERMINAL and len(batch) < 100:
                return
            if await request.is_disconnected():
                return
            yield ": heartbeat\n\n"
            if len(batch) < 100:
                await asyncio.sleep(1)
            try:
                job, batch = await asyncio.to_thread(
                    read_batch, database, identity.uid, workspace_id, job_id, cursor
                )
            except HTTPException:
                # Membership revoked while connected: stop without exposing other workspace data.
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
