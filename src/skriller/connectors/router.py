"""Authenticated operation diagnostics and workspace owner kill switches."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from skriller.auth import Identity, require_identity
from skriller.connections.store import ConnectionStore
from skriller.connectors.diagnostics import SourceDiagnostic, diagnose
from skriller.connectors.registry import Operation
from skriller.connectors.switches import set_disabled
from skriller.contracts import Source
from skriller.db import WorkspaceAccessDenied

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/sources")


class SwitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: StrictBool


@router.get("", response_model=list[SourceDiagnostic])
def source_status(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return diagnose(
                session,
                search_enabled=request.app.state.settings.search_provider != "disabled",
                youtube_image=request.app.state.settings.public_youtube_image,
                x_image=request.app.state.settings.public_x_image,
                reddit_image=request.app.state.settings.public_reddit_image,
                linkedin_image=request.app.state.settings.public_linkedin_image,
                social_image=request.app.state.settings.public_social_image,
                database=request.app.state.database,
                connection_store=ConnectionStore.configured(request.app.state.settings),
            )
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


@router.put("/{source}/{operation}", response_model=SourceDiagnostic)
def source_switch(
    workspace_id: UUID,
    source: Source,
    operation: Operation,
    body: SwitchInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            set_disabled(session, source, operation, body.disabled)
            return next(
                row
                for row in diagnose(
                    session,
                    search_enabled=request.app.state.settings.search_provider != "disabled",
                    youtube_image=request.app.state.settings.public_youtube_image,
                    x_image=request.app.state.settings.public_x_image,
                    reddit_image=request.app.state.settings.public_reddit_image,
                    linkedin_image=request.app.state.settings.public_linkedin_image,
                    social_image=request.app.state.settings.public_social_image,
                    database=request.app.state.database,
                    connection_store=ConnectionStore.configured(request.app.state.settings),
                )
                if row.capability.source == source and row.capability.operation == operation
            )
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
