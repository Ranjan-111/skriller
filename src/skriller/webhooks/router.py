"""Owner-only opt-in endpoints; signing secrets returned once with no-store."""

from datetime import datetime
from typing import Annotated, ClassVar
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.router import PrivateValidationRoute
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.webhooks.service import create_endpoint, disable_endpoint, public_endpoint
from skriller.webhooks.tables import deliveries, endpoints


class WebhookRoute(PrivateValidationRoute):
    max_body = 8192
    size_message = "Webhook request exceeds size limit"
    invalid_detail: ClassVar[dict[str, str]] = {
        "code": "invalid_webhook",
        "message": "Provide a valid endpoint and explicit opt-in.",
    }


router = APIRouter(prefix="/v1/workspaces/{workspace_id}/webhooks", route_class=WebhookRoute)


class EndpointInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    list_id: UUID
    url: str = Field(min_length=1, max_length=2048)
    opt_in: bool = Field(strict=True)


class EndpointOutput(BaseModel):
    id: UUID
    list_id: UUID
    url: str
    enabled: bool
    created_at: datetime


class EndpointCreated(EndpointOutput):
    signing_secret: str


class DeliveryOutput(BaseModel):
    id: UUID
    endpoint_id: UUID
    snapshot_id: UUID
    state: str
    attempts: int
    last_code: str | None
    delivered_at: datetime | None


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        if str(exc) == "Workspace owner permission required":
            raise HTTPException(403, "Workspace owner permission required") from None
        raise HTTPException(404, "Workspace unavailable") from None
    if isinstance(exc, KeyUnavailable):
        raise HTTPException(503, "Webhook encryption is not configured") from None
    if isinstance(exc, LookupError):
        raise HTTPException(404, "Webhook or saved list unavailable") from None
    raise HTTPException(422, "Invalid webhook endpoint or opt-in") from None


@router.post("", response_model=EndpointCreated, status_code=201)
def create(
    workspace_id: UUID,
    body: EndpointInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            ring = Keyring.load(request.app.state.settings.source_encryption_key_file)
            return create_endpoint(
                session, str(body.list_id), body.url, opt_in=body.opt_in, keyring=ring
            )
    except (ValueError, LookupError, WorkspaceAccessDenied, KeyUnavailable) as exc:
        fail(exc)


@router.get("", response_model=list[EndpointOutput])
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
                public_endpoint(row)
                for row in session.execute(
                    sa.select(endpoints)
                    .where(endpoints.c.workspace_id == scope(session))
                    .order_by(endpoints.c.created_at)
                    .limit(10)
                ).mappings()
            ]
    except WorkspaceAccessDenied as exc:
        fail(exc)


@router.delete("/{endpoint_id}", status_code=204)
def disable(
    workspace_id: UUID,
    endpoint_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            disable_endpoint(session, str(endpoint_id))
    except (LookupError, WorkspaceAccessDenied) as exc:
        fail(exc)


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryOutput])
def history(
    workspace_id: UUID,
    endpoint_id: UUID,
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
                    sa.select(deliveries)
                    .where(
                        deliveries.c.workspace_id == scope(session),
                        deliveries.c.endpoint_id == str(endpoint_id),
                    )
                    .order_by(deliveries.c.created_at.desc())
                    .limit(100)
                ).mappings()
            ]
    except WorkspaceAccessDenied as exc:
        fail(exc)
