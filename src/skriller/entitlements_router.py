"""Members see usage; owners can lower settings within provisioned ceilings."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, StrictBool, StrictInt

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.entitlements import policy_view, update_settings

router = APIRouter()


class EntitlementView(Contract):
    workspace_id: UUID
    can_manage: bool
    tier: Literal["trial", "pilot"]
    enabled: bool
    run_limit: int
    result_cap: int
    source_cap: int
    result_limit: int
    source_limit: int
    used_runs: int
    remaining_runs: int


class EntitlementSettings(Contract):
    enabled: StrictBool
    result_limit: StrictInt = Field(ge=1, le=100)
    source_limit: StrictInt = Field(ge=1, le=9)


@router.get("/v1/workspaces/{workspace_id}/entitlements", response_model=EntitlementView)
def read(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return policy_view(session)
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


@router.put("/v1/workspaces/{workspace_id}/entitlements", response_model=EntitlementView)
def update(
    workspace_id: UUID,
    body: EntitlementSettings,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return update_settings(session, **body.model_dump())
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except ValueError:
        raise HTTPException(422, "Settings exceed the provisioned workspace ceilings") from None


@router.get("/v1/workspace/entitlements", response_model=EntitlementView)
def personal(request: Request, identity: Annotated[Identity, Depends(require_identity)]):
    from skriller.research.service import personal_workspace

    workspace = personal_workspace(request.app.state.database, identity.uid)
    with request.app.state.database.tenant(identity.uid, str(workspace["id"])) as session:
        from skriller.retention_runtime import register

        register(session)
        return {"workspace_id": workspace["id"], **policy_view(session)}
