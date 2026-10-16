"""Owner-only saved-evidence selector repair and explicit reviewed activation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import Field, StrictBool

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.research.router import safe_dispatch
from skriller.research.template_repair import (
    RepairInput,
    RepairView,
    approve_repair,
    create_repair,
    repair_view,
)
from skriller.research.template_router import private_response
from skriller.storage import BlobIntegrityError, BlobUnavailable
from skriller.storage.configuration import configured_storage

router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/page-templates", dependencies=[Depends(private_response)]
)


class RepairApproval(Contract):
    expected_version: int = Field(ge=1, le=999999, strict=True)
    confirm_review: StrictBool


def _operation(request, identity, workspace_id, run):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return run(session)
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except (LookupError, BlobUnavailable):
        raise HTTPException(404, "Saved repair request or source is unavailable") from None
    except (ValueError, BlobIntegrityError):
        raise HTTPException(409, "Repair selection changed or cannot be safely approved") from None


@router.post("/{template_id}/repairs", response_model=RepairView, status_code=202)
def request_repair(
    workspace_id: UUID,
    template_id: UUID,
    body: RepairInput,
    request: Request,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=160)],
):
    if not request.app.state.settings.enable_page_extraction:
        raise HTTPException(503, "Saved-page extraction is disabled")

    def create(session):
        job = create_repair(session, template_id, body, idempotency_key)
        return repair_view(session, job["id"])

    view = _operation(request, identity, workspace_id, create)
    background.add_task(
        safe_dispatch,
        request.app.state.database,
        request.app.state.settings.broker_url,
        identity.uid,
        str(workspace_id),
    )
    return view


@router.get("/repairs/{job_id}", response_model=RepairView)
def view_repair(
    workspace_id: UUID,
    job_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    return _operation(request, identity, workspace_id, lambda session: repair_view(session, job_id))


@router.post("/repairs/{job_id}/approve", response_model=RepairView)
def review_repair(
    workspace_id: UUID,
    job_id: UUID,
    body: RepairApproval,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    if not body.confirm_review:
        raise HTTPException(409, "Explicit review confirmation is required")
    with configured_storage(request.app.state.settings) as storage:
        return _operation(
            request,
            identity,
            workspace_id,
            lambda session: approve_repair(session, storage, job_id, body.expected_version),
        )
