"""Authenticated initiating-owner CRM selection and delivery management."""

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.router import PrivateValidationRoute
from skriller.crm.consents import ConsentStore, refresh_destination
from skriller.crm.oauth import SalesforceOAuth, configuration
from skriller.crm.queue import deliveries, enqueue
from skriller.crm.queue import public as delivery_public
from skriller.crm.salesforce import SalesforceUnavailable
from skriller.crm.store import DestinationStore, destinations, public
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.erasure import privacy_lock
from skriller.storage import BlobUnavailable


class CRMValidationRoute(PrivateValidationRoute):
    invalid_detail: ClassVar[dict[str, str]] = {
        "code": "invalid_crm_request",
        "message": "Provide a bounded CRM selection or valid OAuth completion.",
    }


router = APIRouter(prefix="/v1/workspaces/{workspace_id}/crm", route_class=CRMValidationRoute)


class DestinationOutput(BaseModel):
    id: UUID
    instance_url: str
    enabled: bool
    expires_at: datetime
    generation: int


class DeliveryOutput(BaseModel):
    id: UUID
    destination_id: UUID
    entity_id: UUID
    state: Literal["pending", "delivering", "succeeded", "failed", "suppressed", "cancelled"]
    attempts: int
    last_code: str | None


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    destination_id: UUID
    plan_id: UUID
    entity_id: UUID
    field_map: dict[str, str] = Field(min_length=1, max_length=8)
    selected_near: bool = Field(default=False, strict=True)
    opt_in: bool = Field(strict=True)
    idempotency_key: str = Field(min_length=1, max_length=100)


def store_for(request):
    override = getattr(request.app.state, "crm_store", None)
    return override or DestinationStore(
        Keyring.load(request.app.state.settings.source_encryption_key_file)
    )


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        raise HTTPException(403, "Workspace owner permission required") from None
    if isinstance(exc, KeyUnavailable):
        raise HTTPException(
            503, {"code": "crm_not_configured", "message": "CRM connection requires configuration"}
        ) from None
    if isinstance(exc, SalesforceUnavailable):
        raise HTTPException(
            409, {"code": "crm_unavailable", "message": "CRM selection or destination unavailable"}
        ) from None
    raise HTTPException(
        422,
        {
            "code": "invalid_crm_selection",
            "message": "Choose accessible qualified evidence, a valid mapping and explicit consent",
        },
    ) from None


ERRORS = (WorkspaceAccessDenied, KeyUnavailable, SalesforceUnavailable, BlobUnavailable, ValueError)


@router.get("/destinations", response_model=list[DestinationOutput])
def list_destinations(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            rows = (
                session.execute(
                    sa.select(destinations)
                    .where(
                        destinations.c.workspace_id == scope(session),
                        destinations.c.created_by == identity.uid,
                    )
                    .order_by(destinations.c.created_at.desc())
                    .limit(3)
                )
                .mappings()
                .all()
            )
            return [public(row) for row in rows]
    except ERRORS as exc:
        fail(exc)


@router.post("/destinations/{destination_id}/revoke", response_model=DestinationOutput)
def revoke_destination(
    workspace_id: UUID,
    destination_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            store = store_for(request)
            store.revoke(session, destination_id)
            return public(store.get(session, destination_id))
    except ERRORS as exc:
        fail(exc)


@router.post("/deliveries", response_model=DeliveryOutput, status_code=202)
def select_delivery(
    workspace_id: UUID,
    body: SelectionInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        if body.opt_in and request.app.state.settings.salesforce_oauth_client_id:
            refresh_destination(
                request.app.state.database,
                ConsentStore(store_for(request)),
                configuration(request.app.state.settings),
                provider_for(request),
                identity.uid,
                str(workspace_id),
                str(body.destination_id),
            )
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return enqueue(
                session,
                request.app.state.evidence_storage,
                store_for(request),
                body.destination_id,
                body.plan_id,
                body.entity_id,
                field_map=body.field_map,
                selected_near=body.selected_near,
                opt_in=body.opt_in,
                idempotency_key=body.idempotency_key,
            )
    except ERRORS as exc:
        fail(exc)


@router.get("/deliveries", response_model=list[DeliveryOutput])
def list_deliveries(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            rows = (
                session.execute(
                    sa.select(deliveries)
                    .where(
                        deliveries.c.workspace_id == scope(session),
                        deliveries.c.created_by == identity.uid,
                    )
                    .order_by(deliveries.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return [delivery_public(row) for row in rows]
    except ERRORS as exc:
        fail(exc)


@router.post("/deliveries/{delivery_id}/cancel", response_model=DeliveryOutput)
def cancel_delivery(
    workspace_id: UUID,
    delivery_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            # Same privacy fence as actual send/revoke: an in-flight bounded send
            # may finish before this returns; completed delivery is not undone.
            privacy_lock(session)
            row = (
                session.execute(
                    sa.select(deliveries)
                    .where(
                        deliveries.c.workspace_id == scope(session),
                        deliveries.c.id == str(delivery_id),
                        deliveries.c.created_by == identity.uid,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SalesforceUnavailable()
            if row["state"] in {"pending", "delivering"}:
                row = (
                    session.execute(
                        sa.update(deliveries)
                        .where(
                            deliveries.c.workspace_id == scope(session),
                            deliveries.c.id == str(delivery_id),
                        )
                        .values(
                            state="cancelled",
                            last_code="user_cancelled",
                            lease_token=None,
                            lease_expires_at=None,
                        )
                        .returning(deliveries)
                    )
                    .mappings()
                    .one()
                )
            return delivery_public(row)
    except ERRORS as exc:
        fail(exc)


class OAuthConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opt_in: bool = Field(strict=True)


class OAuthConsentOutput(BaseModel):
    consent_id: UUID
    authorization_url: str
    expires_at: datetime


class OAuthCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    consent_id: UUID
    state: SecretStr = Field(min_length=32, max_length=128, repr=False)
    code: SecretStr = Field(min_length=1, max_length=8192, repr=False)


def provider_for(request):
    return getattr(request.app.state, "crm_oauth_provider", None) or SalesforceOAuth()


@router.post("/oauth/start", response_model=OAuthConsentOutput, status_code=201)
def start_oauth(
    workspace_id: UUID,
    body: OAuthConsentInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return ConsentStore(store_for(request)).start(
                session, configuration(request.app.state.settings), opt_in=body.opt_in
            )
    except ERRORS as exc:
        fail(exc)


@router.post("/oauth/complete", response_model=DestinationOutput, status_code=201)
def complete_oauth(
    workspace_id: UUID,
    body: OAuthCompletionInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        store = ConsentStore(store_for(request))
        config = configuration(request.app.state.settings)
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            verifier, version = store.consume(
                session, config, body.consent_id, body.state.get_secret_value()
            )
        try:
            document = provider_for(request).exchange(
                config, body.code.get_secret_value(), verifier
            )
            with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
                return store.activate(session, config, body.consent_id, version, document)
        except Exception:  # noqa: BLE001 - never replay consumed codes or expose credentials
            with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
                row = store.get(session, body.consent_id)
                if row["version"] == version and row["state"] == "exchanging":
                    store.revoke(session, body.consent_id)
            raise SalesforceUnavailable() from None
    except ERRORS as exc:
        fail(exc)


@router.post("/destinations/{destination_id}/refresh", response_model=DestinationOutput)
def refresh_oauth(
    workspace_id: UUID,
    destination_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        store = store_for(request)
        refresh_destination(
            request.app.state.database,
            ConsentStore(store),
            configuration(request.app.state.settings),
            provider_for(request),
            identity.uid,
            str(workspace_id),
            str(destination_id),
        )
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return public(store.get(session, destination_id))
    except ERRORS as exc:
        fail(exc)
