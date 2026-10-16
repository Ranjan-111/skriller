"""Authenticated owner OAuth completion; codes and state never appear in URLs here."""

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from skriller.analytics.google import AnalyticsUnavailable, GoogleAnalyticsOAuth, OAuthConfiguration
from skriller.analytics.jobs import cancel_summary, create_summary, existing_summary, summary_view
from skriller.analytics.private_jobs import PrivateSummaryStore
from skriller.analytics.reports import AnalyticsReport, ReportRequest, read_report
from skriller.analytics.service import AnalyticsStore, now, public, purge_expired, refresh_grant
from skriller.analytics.tables import grants
from skriller.auth import Identity, require_identity
from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.router import PrivateValidationRoute
from skriller.db import WorkspaceAccessDenied
from skriller.db.repositories import require_owner, scope
from skriller.entitlements import policy_for, used_runs
from skriller.research.reports import ResearchReport


class AnalyticsValidationRoute(PrivateValidationRoute):
    invalid_detail: ClassVar[dict[str, str]] = {
        "code": "invalid_analytics_request",
        "message": "Provide bounded OAuth values or a valid historical report request.",
    }


router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/youtube-analytics", route_class=AnalyticsValidationRoute
)


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opt_in: bool


class ConsentOutput(BaseModel):
    grant_id: UUID
    authorization_url: str
    expires_at: datetime


class CompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    grant_id: UUID
    state: SecretStr = Field(min_length=32, max_length=128, repr=False)
    code: SecretStr = Field(min_length=1, max_length=8192, repr=False)


class GrantOutput(BaseModel):
    id: UUID
    workspace_id: UUID
    created_by: str
    state: Literal["pending", "exchanging", "active", "expired", "revoked"]
    channel_id: str | None
    scopes: list[str]
    expires_at: datetime
    access_expires_at: datetime | None
    remote_revocation: Literal["not_performed"]


def configuration(request):
    settings = request.app.state.settings
    if (
        not settings.youtube_analytics_oauth_client_id
        or not settings.youtube_analytics_oauth_client_secret
        or not settings.youtube_analytics_oauth_redirect_uri
    ):
        raise AnalyticsUnavailable("analytics_oauth_not_configured")
    return OAuthConfiguration(
        settings.youtube_analytics_oauth_client_id,
        settings.youtube_analytics_oauth_client_secret.get_secret_value(),
        settings.youtube_analytics_oauth_redirect_uri,
        production=settings.environment == "production",
    )


def store_for(request):
    override = getattr(request.app.state, "analytics_store", None)
    if override is not None:
        return override
    try:
        return AnalyticsStore(Keyring.load(request.app.state.settings.source_encryption_key_file))
    except KeyUnavailable:
        raise AnalyticsUnavailable("analytics_oauth_not_configured") from None


def fail(exc):
    if isinstance(exc, WorkspaceAccessDenied):
        raise HTTPException(403, "Workspace owner permission required") from None
    if isinstance(exc, AnalyticsUnavailable):
        status = (
            503
            if exc.code == "analytics_oauth_not_configured"
            else 429
            if exc.code == "analytics_run_allowance_exhausted"
            else 409
        )
        raise HTTPException(
            status,
            {
                "code": exc.code,
                "message": "Owner analytics connection requires configuration or renewed consent",
            },
        ) from None
    raise HTTPException(422, "Invalid owner analytics configuration") from None


@router.post("/oauth/start", response_model=ConsentOutput, status_code=201)
def start(
    workspace_id: UUID,
    body: ConsentInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            return store_for(request).start(session, configuration(request), opt_in=body.opt_in)
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


@router.post("/oauth/complete", response_model=GrantOutput, status_code=201)
def complete(
    workspace_id: UUID,
    body: CompletionInput,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        store, config = store_for(request), configuration(request)
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            verifier, version = store.consume(
                session, config, body.grant_id, body.state.get_secret_value()
            )
        # Single use is committed before exchange. An uncertain exchange requires
        # fresh consent, never blind replay of an authorization code.
        provider = getattr(request.app.state, "analytics_provider", None) or GoogleAnalyticsOAuth()
        try:
            tokens, channel_id = provider.exchange(config, body.code.get_secret_value(), verifier)
            with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
                return store.activate(session, config, body.grant_id, version, tokens, channel_id)
        except Exception:  # noqa: BLE001 - prevent provider/code/secret exception disclosure
            with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
                row = store.get(session, body.grant_id, lock=True)
                if row["state"] == "exchanging" and row["version"] == version:
                    store.revoke(session, body.grant_id)
            raise AnalyticsUnavailable("analytics_consent_exchange_failed") from None
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


@router.get("/grants", response_model=list[GrantOutput])
def list_grants(
    workspace_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            require_owner(session)
            purge_expired(session)
            rows = (
                session.execute(
                    sa.select(grants)
                    .where(grants.c.workspace_id == scope(session))
                    .order_by(grants.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return [public(row, now(session)) for row in rows]
    except WorkspaceAccessDenied as exc:
        fail(exc)


@router.post("/grants/{grant_id}/revoke", response_model=GrantOutput)
def revoke(
    workspace_id: UUID,
    grant_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return store_for(request).revoke(session, grant_id)
    except (WorkspaceAccessDenied, AnalyticsUnavailable) as exc:
        fail(exc)


@router.post("/grants/{grant_id}/refresh", response_model=GrantOutput)
def refresh(
    workspace_id: UUID,
    grant_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        provider = getattr(request.app.state, "analytics_provider", None) or GoogleAnalyticsOAuth()
        return refresh_grant(
            request.app.state.database,
            store_for(request),
            configuration(request),
            provider,
            identity.uid,
            str(workspace_id),
            grant_id,
        )
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


@router.post("/grants/{grant_id}/reports", response_model=AnalyticsReport)
def report(
    workspace_id: UUID,
    grant_id: UUID,
    body: ReportRequest,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        provider = getattr(request.app.state, "analytics_provider", None) or GoogleAnalyticsOAuth()
        result = read_report(
            request.app.state.database,
            store_for(request),
            configuration(request),
            provider,
            identity.uid,
            str(workspace_id),
            grant_id,
            body,
        )
        return result.report
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


class SummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID
    report: ReportRequest


class SummaryOutput(BaseModel):
    job_id: UUID
    state: str
    summary_state: str
    result: ResearchReport | None = None


@router.post("/summary-jobs", response_model=SummaryOutput, status_code=202)
def submit_summary(
    workspace_id: UUID,
    body: SummaryInput,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    identity: Annotated[Identity, Depends(require_identity)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=170)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        store = PrivateSummaryStore(store_for(request))
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            existing = existing_summary(session, store, body.grant_id, body.report, idempotency_key)
            if existing:
                return summary_view(session, store, existing["id"])
            policy = policy_for(session)
            if not policy["enabled"] or used_runs(session) >= policy["run_limit"]:
                raise AnalyticsUnavailable("analytics_run_allowance_exhausted")
        provider = getattr(request.app.state, "analytics_provider", None) or GoogleAnalyticsOAuth()
        verified = read_report(
            request.app.state.database,
            store.grants,
            configuration(request),
            provider,
            identity.uid,
            str(workspace_id),
            body.grant_id,
            body.report,
        )
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            job = create_summary(session, store, verified, body.report, idempotency_key)
            result = summary_view(session, store, job["id"])
        from skriller.research.router import safe_dispatch

        background.add_task(
            safe_dispatch,
            request.app.state.database,
            request.app.state.settings.broker_url,
            identity.uid,
            str(workspace_id),
        )
        return result
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


@router.get("/summary-jobs/{job_id}", response_model=SummaryOutput)
def get_summary(
    workspace_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return summary_view(session, PrivateSummaryStore(store_for(request)), str(job_id))
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)


@router.post("/summary-jobs/{job_id}/cancel", response_model=SummaryOutput)
def stop_summary(
    workspace_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_identity)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with request.app.state.database.tenant(identity.uid, str(workspace_id)) as session:
            return cancel_summary(session, PrivateSummaryStore(store_for(request)), str(job_id))
    except (WorkspaceAccessDenied, AnalyticsUnavailable, ValueError) as exc:
        fail(exc)
