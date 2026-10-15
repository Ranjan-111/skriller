"""Authenticated owner review; source/model content cannot publish templates."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner
from skriller.research.adaptive_templates import ReviewedTemplate
from skriller.research.template_registry import (
    publish_template,
    rollback_template,
    selected_templates,
)


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/page-templates", dependencies=[Depends(private_response)]
)


class TemplatePublication(Contract):
    template: ReviewedTemplate
    expected_version: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)


class TemplateRollback(Contract):
    target_version: int = Field(ge=1, le=1_000_000, strict=True)
    expected_version: int = Field(ge=1, le=1_000_000, strict=True)


def operation(request, identity, workspace_id, run):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return run(session)
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except LookupError:
        raise HTTPException(404, "Reviewed template version unavailable") from None
    except ValueError:
        raise HTTPException(
            409, "Reviewed template conflicts with its scope, selectors or active version"
        ) from None


@router.get("", response_model=list[ReviewedTemplate])
def active_templates(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    return operation(request, identity, workspace_id, selected_templates)


@router.post("", response_model=ReviewedTemplate, status_code=201)
def publish(
    workspace_id: UUID,
    body: TemplatePublication,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    return operation(
        request,
        identity,
        workspace_id,
        lambda session: publish_template(
            session, body.template, expected_version=body.expected_version
        ),
    )


@router.post("/{template_id}/rollback", response_model=ReviewedTemplate)
def rollback(
    workspace_id: UUID,
    template_id: UUID,
    body: TemplateRollback,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    return operation(
        request,
        identity,
        workspace_id,
        lambda session: rollback_template(
            session,
            template_id,
            target_version=body.target_version,
            expected_version=body.expected_version,
        ),
    )
