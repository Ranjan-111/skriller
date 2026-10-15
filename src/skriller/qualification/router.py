"""Authenticated owner review of reversible, evidence-checked identity links."""

from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from skriller.auth import Identity, require_identity
from skriller.contracts import Contract
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.erasure import privacy_lock
from skriller.qualification.identity import identity_reviews, reverse_link, review_link, suggest
from skriller.qualification.review_context import IdentitySubjectView, review_context


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(private_response)])


class IdentityPair(Contract):
    source_id: UUID
    target_id: UUID


class IdentityReviewView(Contract):
    id: UUID
    source_id: UUID
    target_id: UUID
    state: Literal["suggestion", "linked", "reversed"]
    reason: str
    review_outcome: str | None = None


class IdentityReviewDetail(IdentityReviewView):
    source: IdentitySubjectView
    target: IdentitySubjectView
    eligible: bool
    current_reason: str
    can_review: bool


def visible(row):
    return {name: row.get(name) for name in IdentityReviewView.model_fields}


def mutation(request, identity, workspace_id, operation):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            privacy_lock(session)
            return visible(operation(session))
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except LookupError:
        raise HTTPException(404, "Identity review unavailable") from None
    except ValueError:
        raise HTTPException(409, "Identity review cannot perform this transition") from None


@router.post("/v1/workspaces/{workspace_id}/identity-reviews", response_model=IdentityReviewView)
def create_review(
    workspace_id: UUID,
    body: IdentityPair,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    def create(session):
        source_id, target_id = sorted((str(body.source_id), str(body.target_id)))
        if source_id == target_id:
            raise ValueError("Distinct records required")
        existing = (
            session.execute(
                sa.select(identity_reviews)
                .where(
                    identity_reviews.c.workspace_id == scope(session),
                    identity_reviews.c.source_id == source_id,
                    identity_reviews.c.target_id == target_id,
                    identity_reviews.c.state.in_(["suggestion", "linked"]),
                )
                .order_by(identity_reviews.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        return existing if existing is not None else suggest(session, source_id, target_id)

    return mutation(request, identity, workspace_id, create)


@router.post(
    "/v1/workspaces/{workspace_id}/identity-reviews/{review_id}/{action}",
    response_model=IdentityReviewView,
)
def change_review(
    workspace_id: UUID,
    review_id: UUID,
    action: Literal["approve", "reverse"],
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    def change(session):
        row = (
            session.execute(
                sa.select(identity_reviews)
                .where(
                    identity_reviews.c.workspace_id == scope(session),
                    identity_reviews.c.id == str(review_id),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("Review unavailable")
        if (action == "approve" and row["state"] == "linked") or (
            action == "reverse" and row["state"] == "reversed"
        ):
            return row
        operation = review_link if action == "approve" else reverse_link
        return operation(session, str(review_id))

    return mutation(request, identity, workspace_id, change)


@router.get(
    "/v1/workspaces/{workspace_id}/identity-reviews", response_model=list[IdentityReviewView]
)
def list_reviews(
    workspace_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            rows = (
                session.execute(
                    sa.select(identity_reviews)
                    .where(identity_reviews.c.workspace_id == scope(session))
                    .order_by(identity_reviews.c.created_at.desc(), identity_reviews.c.id)
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return [visible(row) for row in rows]
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


@router.get(
    "/v1/workspaces/{workspace_id}/identity-reviews/{review_id}",
    response_model=IdentityReviewDetail,
)
def review_detail(
    workspace_id: UUID,
    review_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            row = (
                session.execute(
                    sa.select(identity_reviews).where(
                        identity_reviews.c.workspace_id == scope(session),
                        identity_reviews.c.id == str(review_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError("Review unavailable")
            return visible(row) | review_context(session, row)
    except (WorkspaceAccessDenied, LookupError):
        raise HTTPException(404, "Identity review unavailable") from None
