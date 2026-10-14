"""Bearer-authenticated private export creation and download; no URL tokens."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from skriller.auth import Identity, require_identity
from skriller.db import WorkspaceAccessDenied
from skriller.exports import create_export, download_export
from skriller.exports.formats import Format
from skriller.storage import BlobIntegrityError, BlobTooLarge, BlobUnavailable

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/exports")


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    entity_ids: list[UUID] = Field(max_length=100)
    selected_near_ids: list[UUID] = Field(default_factory=list, max_length=100)
    format: Format


class ExportOutput(BaseModel):
    id: UUID
    format: Format
    row_count: int
    expires_at: datetime
    schema_version: str


@router.post("", response_model=ExportOutput)
def export_create(
    workspace_id: UUID,
    body: ExportInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return create_export(
                session,
                request.app.state.evidence_storage,
                str(body.plan_id),
                tuple(map(str, body.entity_ids)),
                format=body.format,
                selected_near_ids=tuple(map(str, body.selected_near_ids)),
            )
    except (WorkspaceAccessDenied, LookupError):
        raise HTTPException(404, "Export selection unavailable") from None
    except (ValueError, BlobTooLarge):
        raise HTTPException(
            422, "Export selection is invalid or exceeds supported bounds"
        ) from None


@router.get("/{export_id}")
def export_download(
    workspace_id: UUID,
    export_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            content, format = download_export(
                session, request.app.state.evidence_storage, str(export_id)
            )
    except (WorkspaceAccessDenied, BlobUnavailable, BlobIntegrityError, BlobTooLarge):
        raise HTTPException(404, "Export unavailable") from None
    mime = {"csv": "text/csv", "json": "application/json", "jsonl": "application/x-ndjson"}[format]
    return Response(
        content,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="skriller-results.{format}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
