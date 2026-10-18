"""Opt-in owner checkout API in the isolated billing service."""

from datetime import datetime
from types import SimpleNamespace
from typing import Annotated, ClassVar, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from skriller.auth import Identity, require_identity
from skriller.billing.access import bindings
from skriller.billing.checkout import (
    RAZORPAY_CYCLES,
    CheckoutUnavailable,
    create_checkout,
    intents,
    require_checkout_owner,
    view,
)
from skriller.billing.plans import PLANS
from skriller.billing.provisioning import remote_plans
from skriller.connections.router import PrivateValidationRoute


class CheckoutValidationRoute(PrivateValidationRoute):
    max_body = 4096
    size_message = "Checkout request exceeds size limit"
    invalid_detail: ClassVar[dict[str, str]] = {
        "code": "invalid_checkout",
        "message": "Choose an approved plan and explicitly confirm checkout.",
    }


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/checkout", route_class=CheckoutValidationRoute
)


class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Literal["stripe", "razorpay"]
    plan: Literal["starter", "pro"]
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    opt_in: bool


class CheckoutOutput(BaseModel):
    id: UUID
    provider: Literal["stripe", "razorpay"]
    plan: Literal["starter", "pro"]
    state: Literal["dispatching", "ready", "uncertain", "bound"]
    expires_at: datetime
    checkout_url: str | None
    maximum_monthly_cycles: int | None


class CheckoutOffer(BaseModel):
    provider: Literal["stripe", "razorpay"]
    plan: Literal["starter", "pro"]
    amount_minor: int
    currency: Literal["USD", "INR"]
    interval: Literal["month"] = "month"
    maximum_monthly_cycles: int | None
    runs_per_month: int
    results_per_run: int
    sources_per_run: int
    configured: bool


class CheckoutCatalog(BaseModel):
    can_start: bool
    offers: list[CheckoutOffer]
    current: CheckoutOutput | None


@router.get("", response_model=CheckoutCatalog)
def offers(
    workspace_id: UUID, request: Request, identity: Annotated[Identity, Depends(require_identity)]
):
    try:
        with request.app.state.billing_engine.begin() as connection:
            workspace = require_checkout_owner(connection, workspace_id, identity.uid)
            current_id = connection.execute(
                sa.select(intents.c.id).where(intents.c.workspace_id == workspace)
            ).scalar_one_or_none()
            bound = connection.execute(
                sa.select(bindings.c.workspace_id).where(bindings.c.workspace_id == workspace)
            ).scalar_one_or_none()
            rows = []
            for provider in ("stripe", "razorpay"):
                configs = [
                    config
                    for config in request.app.state.billing_configurations
                    if config.provider == provider
                ]
                if len(configs) != 1:
                    continue
                for slug, plan in PLANS.items():
                    ready = connection.execute(
                        sa.select(remote_plans.c.remote_id).where(
                            remote_plans.c.provider == provider,
                            remote_plans.c.account_scope == configs[0].scope,
                            remote_plans.c.slug == slug,
                            remote_plans.c.state == "ready",
                        )
                    ).scalar_one_or_none()
                    rows.append(
                        {
                            "provider": provider,
                            "plan": slug,
                            "amount_minor": plan.usd_cents
                            if provider == "stripe"
                            else plan.inr_paise,
                            "currency": "USD" if provider == "stripe" else "INR",
                            "maximum_monthly_cycles": RAZORPAY_CYCLES
                            if provider == "razorpay"
                            else None,
                            "runs_per_month": plan.runs,
                            "results_per_run": plan.results,
                            "sources_per_run": plan.sources,
                            "configured": ready is not None,
                        }
                    )
            return {
                "can_start": current_id is None and bound is None,
                "offers": rows,
                "current": view(connection, workspace, identity.uid, current_id)
                if current_id
                else None,
            }
    except CheckoutUnavailable:
        raise HTTPException(404, "Checkout unavailable") from None


@router.post("", response_model=CheckoutOutput)
def start(
    workspace_id: UUID,
    body: CheckoutInput,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    configurations = [
        config
        for config in request.app.state.billing_configurations
        if config.provider == body.provider
    ]
    if len(configurations) != 1:
        raise HTTPException(503, "Checkout provider is not configured uniquely")
    try:
        return create_checkout(
            request.app.state.billing_engine,
            configurations[0],
            request.app.state.checkout_options,
            str(workspace_id),
            identity.uid,
            body.plan,
            body.idempotency_key,
            opt_in=body.opt_in,
            transport=getattr(request.app.state, "checkout_transport", None),
        )
    except CheckoutUnavailable:
        raise HTTPException(
            409, "Checkout unavailable or requires operator reconciliation"
        ) from None


@router.get("/{checkout_id}", response_model=CheckoutOutput)
def status(
    workspace_id: UUID,
    checkout_id: UUID,
    request: Request,
    identity: Annotated[Identity, Depends(require_identity)],
):
    try:
        with request.app.state.billing_engine.begin() as connection:
            return view(connection, str(workspace_id), identity.uid, str(checkout_id))
    except CheckoutUnavailable:
        raise HTTPException(404, "Checkout unavailable") from None


def attach_checkout(app, engine, configurations, options):
    options.__post_init__()
    app.state.settings = SimpleNamespace(firebase_project_id=options.firebase_project_id)
    app.state.billing_engine = engine
    app.state.billing_configurations = configurations
    app.state.checkout_options = options
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[options.return_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.include_router(router)
