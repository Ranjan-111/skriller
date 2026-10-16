"""Owner-reviewed source chronology; submitted values never replace saved evidence."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner
from skriller.qualification.contacts import DatedRole
from skriller.qualification.role_review import approve_role_refresh, review_context


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/role-refreshes", dependencies=[Depends(private_response)]
)


class RoleReference(Contract):
    role_claim_id: UUID
    date_claim_id: UUID
    evidence_id: UUID

    def observation(self):
        return DatedRole(str(self.role_claim_id), str(self.date_claim_id), str(self.evidence_id))


class RoleReviewInput(Contract):
    entity_id: UUID
    previous: RoleReference
    replacement: RoleReference


class RoleApproval(RoleReviewInput):
    same_subject_confirmed: bool = Field(strict=True)
    expected_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RoleSource(RoleReference):
    role: str = Field(max_length=512)
    effective_date: date
    excerpt: str = Field(max_length=4096)
    source_url: str = Field(max_length=4096)


class RoleReviewView(Contract):
    entity_id: UUID
    subject_name: str | None
    previous: RoleSource
    replacement: RoleSource
    review_origin: Literal["workspace_owner"]
    requires_same_subject_confirmation: Literal[True]
    review_hash: str


class RoleProjection(Contract):
    claim_id: UUID
    value: str | None
    freshness: Literal["current", "historical", "unknown"]
    event_at: datetime | None


class RoleDecision(Contract):
    entity_id: UUID
    outcome: Literal["superseded"]
    review_origin: Literal["workspace_owner"]
    roles: list[RoleProjection] = Field(max_length=100)


def operation(request, identity, workspace_id, run):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return run(session)
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except LookupError:
        raise HTTPException(404, "Role review unavailable") from None
    except ValueError:
        raise HTTPException(
            409, "Role review requires unchanged, current same-subject source evidence"
        ) from None


@router.post("/preview", response_model=RoleReviewView)
def preview(
    workspace_id: UUID,
    body: RoleReviewInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    return operation(
        request,
        identity,
        workspace_id,
        lambda session: review_context(
            session,
            str(body.entity_id),
            body.previous.observation(),
            body.replacement.observation(),
        ),
    )


@router.post("", response_model=RoleDecision)
def approve(
    workspace_id: UUID,
    body: RoleApproval,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    return operation(
        request,
        identity,
        workspace_id,
        lambda session: approve_role_refresh(
            session,
            str(body.entity_id),
            body.previous.observation(),
            body.replacement.observation(),
            same_subject_confirmed=body.same_subject_confirmed,
            expected_review_hash=body.expected_review_hash,
        ),
    )
