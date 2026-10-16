"""Authenticated immutable list snapshots; accepts IDs, never caller lead values."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert

from skriller.auth import Identity, require_identity
from skriller.connectors.candidates import canonical_url
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import suppressions
from skriller.lists import create_list, list_snapshots, refresh_list, saved_lists, snapshot
from skriller.qualification.contacts import email_domain
from skriller.qualification.criteria import Fit
from skriller.research.changes import meaningful_changes

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/lists")


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    plan_id: UUID
    entity_ids: list[UUID] = Field(max_length=100)


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_ids: list[UUID] = Field(max_length=100)
    expected_revision: int = Field(ge=1, le=1_000_000, strict=True)


class ListMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    workspace_id: UUID
    name: str
    plan_id: UUID
    created_by: str
    created_at: datetime


class SnapshotEvidence(BaseModel):
    id: UUID
    source_url: str
    source_platform: str
    collected_at: datetime
    excerpt: str
    excerpt_truncated: bool


class SnapshotValue(BaseModel):
    field: str
    value: str | int | float | bool
    evidence: list[SnapshotEvidence]
    claim_ids: list[UUID] = Field(default_factory=list, max_length=300)
    source_entity_ids: list[UUID] = Field(default_factory=list, max_length=100)


class SnapshotMember(BaseModel):
    entity_id: UUID
    display_name: str | None
    fit: Fit
    values: list[SnapshotValue]
    identity_status: Literal["suppression_unresolved", "reviewed_facts"]


class SnapshotOmission(BaseModel):
    entity_id: UUID
    reason: Literal["suppressed"]


class SnapshotPayload(BaseModel):
    snapshot_at: datetime
    members: list[SnapshotMember]
    omitted: list[SnapshotOmission]
    refresh_scope: Literal["persisted_reviewed_facts_only"]


class SnapshotOutput(BaseModel):
    id: UUID
    workspace_id: UUID
    list_id: UUID
    revision: int
    plan_id: UUID
    created_at: datetime
    created_by: str
    payload: SnapshotPayload


class SuppressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["entity", "profile", "email", "domain"]
    key: str = Field(min_length=1, max_length=4096)
    reason: str = Field(min_length=1, max_length=500)


class SuppressionOutput(BaseModel):
    state: Literal["active"]
    kind: Literal["entity", "profile", "email", "domain"]
    applies_to: Literal["future_list_refresh"]
    historical_snapshot_action: Literal["unchanged"]


class ChangeCitation(BaseModel):
    source_url: str
    source_platform: str
    collected_at: datetime
    quote: str
    excerpt_sha256: str


class ChangeReport(BaseModel):
    entity_id: UUID
    display_name: str | None
    field: Literal["current_role"]
    previous_value: str | int | float | bool
    current_value: str | int | float | bool
    qualification: Literal["accepted_observation_not_independently_verified"]
    citations: list[ChangeCitation]


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        if str(exc) != "Workspace owner permission required":
            raise HTTPException(404, "Workspace unavailable") from None
        raise HTTPException(403, "Workspace owner permission required") from None
    if isinstance(exc, LookupError):
        raise HTTPException(404, "Saved list, plan or entity unavailable") from None
    if str(exc) == "Refresh must reference latest immutable snapshot":
        raise HTTPException(
            409, {"code": "stale_snapshot_revision", "message": "Refresh the latest saved revision"}
        ) from None
    raise HTTPException(
        422,
        {
            "code": "invalid_list_request",
            "message": "List request exceeds supported bounds or is invalid",
        },
    ) from None


def headers(response, result, view):
    response.headers["X-Skriller-Snapshot-Revision"] = str(result["revision"])
    response.headers["X-Skriller-Snapshot-View"] = view
    response.headers["ETag"] = f'"{result["list_id"]}:{result["revision"]}"'
    response.headers["Cache-Control"] = "private, no-store"


@router.post("", response_model=ListMetadata, status_code=201)
def save_list(
    workspace_id: UUID,
    body: ListInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return create_list(
                session, body.name, str(body.plan_id), tuple(map(str, body.entity_ids))
            )
    except (WorkspaceAccessDenied, LookupError, ValueError) as exc:
        fail(exc)


@router.get("", response_model=list[ListMetadata])
def list_saved(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return (
                session.execute(
                    sa.select(saved_lists)
                    .where(saved_lists.c.workspace_id == scope(session))
                    .order_by(saved_lists.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


@router.post("/{list_id}/refresh", response_model=SnapshotOutput, status_code=201)
def refresh(
    workspace_id: UUID,
    list_id: UUID,
    body: RefreshInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            result = refresh_list(
                session,
                str(list_id),
                tuple(map(str, body.entity_ids)),
                expected_revision=body.expected_revision,
            )
        headers(response, result, "frozen")
        return result
    except (WorkspaceAccessDenied, LookupError, ValueError) as exc:
        fail(exc)


@router.get("/{list_id}/snapshots/latest", response_model=SnapshotOutput)
def latest_snapshot(
    workspace_id: UUID,
    list_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            revision = session.execute(
                sa.select(sa.func.max(list_snapshots.c.revision)).where(
                    list_snapshots.c.workspace_id == scope(session),
                    list_snapshots.c.list_id == str(list_id),
                )
            ).scalar_one()
            if revision is None:
                raise LookupError("Saved snapshot unavailable")
            result = snapshot(session, str(list_id), revision)
        headers(response, result, "latest")
        return result
    except (WorkspaceAccessDenied, LookupError):
        raise HTTPException(404, "Saved snapshot unavailable") from None


@router.get("/{list_id}/snapshots/{revision}", response_model=SnapshotOutput)
def historical_snapshot(
    workspace_id: UUID,
    list_id: UUID,
    revision: int,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    if revision < 1:
        raise HTTPException(422, "Positive snapshot revision required")
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            result = snapshot(session, str(list_id), revision)
        headers(response, result, "frozen")
        return result
    except (WorkspaceAccessDenied, LookupError):
        raise HTTPException(404, "Saved snapshot unavailable") from None


@router.get("/{list_id}/snapshots/{revision}/changes", response_model=list[ChangeReport])
def snapshot_changes(
    workspace_id: UUID,
    list_id: UUID,
    revision: int,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    """Return cited, deterministic supported changes from the previous revision."""
    if revision < 1:
        raise HTTPException(422, "Positive snapshot revision required")
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            current = snapshot(session, str(list_id), revision)
            previous = snapshot(session, str(list_id), revision - 1) if revision > 1 else None
        if previous is None:
            return []
        return meaningful_changes(previous["payload"], current["payload"])
    except (WorkspaceAccessDenied, LookupError):
        raise HTTPException(404, "Saved snapshot unavailable") from None


@router.post("/suppressions", response_model=SuppressionOutput, status_code=201)
def suppress(
    workspace_id: UUID,
    body: SuppressionInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        key = body.key
        if body.kind == "entity":
            key = str(UUID(key))
        elif body.kind == "profile":
            key = canonical_url(key)
        elif body.kind == "email":
            if email_domain(key) is None:
                raise ValueError("Invalid contact key")
            key = key.casefold()
        elif body.kind == "domain":
            domain = email_domain("validation@" + key)
            if domain is None:
                raise ValueError("Invalid domain key")
            key = domain
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            if body.kind == "entity":
                from skriller.db.repositories import ResearchRepository

                if ResearchRepository.get_entity(session, key) is None:
                    raise LookupError("Entity unavailable")
            query = insert(suppressions).values(
                workspace_id=scope(session),
                kind=body.kind,
                key=key,
                reason=body.reason,
                created_by=identity.uid,
            )
            session.execute(
                query.on_conflict_do_nothing(index_elements=["workspace_id", "kind", "key"])
            )
        return {
            "state": "active",
            "kind": body.kind,
            "applies_to": "future_list_refresh",
            "historical_snapshot_action": "unchanged",
        }
    except (WorkspaceAccessDenied, LookupError, ValueError) as exc:
        fail(exc)
