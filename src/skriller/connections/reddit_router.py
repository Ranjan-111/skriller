"""Reddit owner consent routes adapted from the existing X OAuth route contract."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.reddit_oauth import RedditConsentStore, consents
from skriller.connections.router import ConnectionMetadata, PrivateValidationRoute
from skriller.connections.store import ConnectionStore, ConnectionUnavailable
from skriller.connections.x_oauth import complete_consent, refresh_consent
from skriller.connectors.reddit_oauth import RedditOAuth, RedditOAuthUnavailable, configuration
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope

router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/reddit/oauth", route_class=PrivateValidationRoute
)


class RedditConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opt_in: bool


class RedditConsentOutput(BaseModel):
    consent_id: UUID
    authorization_url: str
    expires_at: datetime


class RedditCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    consent_id: UUID
    state: SecretStr = Field(min_length=43, max_length=128, repr=False)
    code: SecretStr = Field(min_length=1, max_length=8192, repr=False)


class RedditConsentMetadata(BaseModel):
    consent_id: UUID
    connection_id: UUID | None
    state: Literal["pending", "exchanging", "active"]
    expires_at: datetime
    access_expires_at: datetime | None = None
    access_state: Literal["active", "expired", "revoked"] | None = None
    remote_revocation: Literal["not_performed"] = "not_performed"


def store_for(request):
    return getattr(request.app.state, "reddit_consent_store", None) or RedditConsentStore(
        Keyring.load(request.app.state.settings.source_encryption_key_file)
    )


def provider_for(request):
    return getattr(request.app.state, "reddit_oauth_provider", None) or RedditOAuth()


ERRORS = (
    WorkspaceAccessDenied,
    KeyUnavailable,
    RedditOAuthUnavailable,
    ConnectionUnavailable,
    ValueError,
)


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        raise HTTPException(403, "Workspace owner permission required") from None
    if isinstance(exc, KeyUnavailable):
        raise HTTPException(503, "Reddit authorization is not configured") from None
    raise HTTPException(
        409, "Reddit authorization unavailable; reconnect or check configuration"
    ) from None


@router.get("", response_model=list[RedditConsentMetadata])
def list_consents(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            rows = session.execute(
                sa.select(consents)
                .where(
                    consents.c.workspace_id == scope(session),
                    consents.c.created_by == identity.uid,
                    consents.c.state != "revoked",
                    consents.c.expires_at > sa.func.clock_timestamp(),
                )
                .order_by(consents.c.created_at.desc())
                .limit(3)
            ).mappings()
            result = []
            for row in rows:
                reference = (
                    ConnectionStore(None).metadata(session, UUID(row["connection_id"]))
                    if row["connection_id"]
                    else None
                )
                result.append(
                    {
                        "consent_id": row["id"],
                        "connection_id": row["connection_id"],
                        "state": row["state"],
                        "expires_at": row["expires_at"],
                        "access_expires_at": reference.expires_at if reference else None,
                        "access_state": reference.state if reference else None,
                    }
                )
            return result
    except ERRORS as exc:
        fail(exc)


@router.post("/start", response_model=RedditConsentOutput, status_code=201)
def start(
    workspace_id: UUID,
    body: RedditConsentInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return store_for(request).start(
                session, configuration(request.app.state.settings), opt_in=body.opt_in
            )
    except ERRORS as exc:
        fail(exc)


@router.post("/complete", response_model=ConnectionMetadata, status_code=201)
def complete(
    workspace_id: UUID,
    body: RedditCompletionInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return complete_consent(
            request.app.state.database,
            store_for(request),
            configuration(request.app.state.settings),
            provider_for(request),
            identity.uid,
            str(workspace_id),
            body.consent_id,
            body.state.get_secret_value(),
            body.code.get_secret_value(),
        )
    except ERRORS as exc:
        fail(exc)


@router.post("/{consent_id}/refresh", response_model=ConnectionMetadata)
def refresh(
    workspace_id: UUID,
    consent_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return refresh_consent(
            request.app.state.database,
            store_for(request),
            configuration(request.app.state.settings),
            provider_for(request),
            identity.uid,
            str(workspace_id),
            consent_id,
        )
    except ERRORS as exc:
        fail(exc)


@router.post("/{consent_id}/revoke", status_code=204)
def revoke(
    workspace_id: UUID,
    consent_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            store_for(request).revoke(session, consent_id)
        return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
    except ERRORS as exc:
        fail(exc)
