"""Authenticated credential configuration with metadata-only responses/errors."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from skriller.auth import Identity, require_identity
from skriller.connections.lifecycle import list_metadata, reconnect
from skriller.connections.store import ConnectionStore, ConnectionUnavailable, SecretPayload
from skriller.contracts import Source
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner

MAX_BODY = 65536


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            size = 0

            async def bounded_receive():
                nonlocal size
                message = await request.receive()
                if message["type"] == "http.request":
                    size += len(message.get("body", b""))
                    if size > MAX_BODY:
                        raise HTTPException(413, "Connection request exceeds size limit")
                return message

            private_request = Request(request.scope, receive=bounded_receive)
            try:
                return await original(private_request)
            except RequestValidationError:
                # FastAPI's ordinary validation response contains input and ctx,
                # including malformed secrets. No input/errors are serialized here.
                return JSONResponse(
                    {
                        "detail": {
                            "code": "invalid_connection_configuration",
                            "message": "Provide valid source credentials, read-only scopes and a bounded expiry.",
                        }
                    },
                    status_code=422,
                )

        return handler


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/connections", route_class=PrivateValidationRoute
)
AuthKind = Literal["session", "oauth", "api_key"]
ConnectionSource = Source | Literal["proxy"]


def read_scopes() -> list[Literal["read", "discover"]]:
    return ["read"]


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source: ConnectionSource
    auth_kind: AuthKind
    payload: SecretPayload = Field(repr=False)
    expires_at: datetime
    scopes: list[Literal["read", "discover"]] = Field(
        default_factory=read_scopes, min_length=1, max_length=2
    )


class ReconnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    payload: SecretPayload = Field(repr=False)
    expires_at: datetime
    auth_kind: AuthKind | None = None
    scopes: list[Literal["read", "discover"]] | None = Field(
        default=None, min_length=1, max_length=2
    )


class ConnectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID
    workspace_id: UUID
    source: ConnectionSource
    auth_kind: AuthKind
    scopes: tuple[str, ...]
    state: Literal["active", "expired", "revoked"]
    expires_at: datetime
    access_validation: Literal["not_performed"] = "not_performed"
    remote_revocation: Literal["not_performed"] = "not_performed"


def configured_store(request):
    return getattr(request.app.state, "connection_store", None) or ConnectionStore.configured(
        request.app.state.settings
    )


def fail_connection(exc):
    if exc.reason in {"encryption_key_missing", "runner_or_key_unavailable"}:
        raise HTTPException(
            503,
            {
                "code": "needs_connection",
                "message": "Source credential encryption is not configured",
            },
        ) from None
    raise HTTPException(
        404, {"code": "needs_connection", "message": "Source connection is unavailable"}
    ) from None


@router.get("", response_model=list[ConnectionMetadata])
def list_connections(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return list_metadata(session, ConnectionStore(None))
    except WorkspaceAccessDenied:
        raise HTTPException(404, "Workspace unavailable") from None


@router.post("", response_model=ConnectionMetadata, status_code=201)
def connect(
    workspace_id: UUID,
    body: ConnectionInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return configured_store(request).create(
                session,
                body.source,
                body.auth_kind,
                body.payload,
                expires_at=body.expires_at,
                scopes=tuple(body.scopes),
            )
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except ConnectionUnavailable as exc:
        fail_connection(exc)
    except ValueError:
        raise HTTPException(
            422,
            {
                "code": "invalid_connection_configuration",
                "message": "Connection settings are invalid",
            },
        ) from None


@router.post("/{connection_id}/reconnect", response_model=ConnectionMetadata, status_code=201)
def reconnect_source(
    workspace_id: UUID,
    connection_id: UUID,
    body: ReconnectInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return reconnect(
                session,
                configured_store(request),
                connection_id,
                body.payload,
                expires_at=body.expires_at,
                scopes=tuple(body.scopes) if body.scopes is not None else None,
                auth_kind=body.auth_kind,
            )
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except ConnectionUnavailable as exc:
        fail_connection(exc)
    except ValueError:
        raise HTTPException(
            422,
            {
                "code": "invalid_connection_configuration",
                "message": "Connection settings are invalid",
            },
        ) from None


@router.post("/{connection_id}/revoke", response_model=ConnectionMetadata)
def revoke_source(
    workspace_id: UUID,
    connection_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return configured_store(request).revoke(session, connection_id)
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
    except ConnectionUnavailable as exc:
        fail_connection(exc)


@router.post("/purge-expired")
def purge_expired(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return {"purged": configured_store(request).purge_expired(session)}
    except WorkspaceAccessDenied:
        raise HTTPException(403, "Workspace owner permission required") from None
