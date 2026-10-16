"""Explicit bounded operator billing intake and periodic reconciliation."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from skriller.billing.access import bindings, operator
from skriller.billing.catalog import load, queue_refresh, receive_bound
from skriller.billing.events import MAX_BODY, InvalidBillingEvent
from skriller.billing.inbox import inbox
from skriller.billing.providers import fetch_subscription
from skriller.billing.reconcile import audit, reconcile


@dataclass(frozen=True)
class ProviderConfiguration:
    provider: str
    account_id: str | None
    live_mode: bool
    webhook_secret: bytes = field(repr=False)
    api_key: str = field(repr=False)
    api_secret: str | None = field(default=None, repr=False)
    stripe_version: str | None = None

    def __post_init__(self):
        import re

        if (
            self.provider not in {"stripe", "razorpay"}
            or type(self.live_mode) is not bool
            or not isinstance(self.webhook_secret, bytes)
            or not 16 <= len(self.webhook_secret) <= 8192
            or not isinstance(self.api_key, str)
            or not 16 <= len(self.api_key) <= 8192
            or (self.provider == "razorpay" and (not self.account_id or not self.api_secret))
            or (
                self.account_id is not None
                and not re.fullmatch(r"[A-Za-z0-9_]{1,180}", self.account_id)
            )
            or (self.provider == "stripe" and not self.stripe_version)
            or not self.api_key.isascii()
            or any(char.isspace() for char in self.api_key)
            or not self.api_key.startswith(
                ("sk_" if self.provider == "stripe" else "rzp_")
                + ("live_" if self.live_mode else "test_")
            )
            or (
                self.provider == "stripe"
                and not re.fullmatch(
                    r"20[0-9]{2}-[0-9]{2}-[0-9]{2}\.[a-z]+", self.stripe_version or ""
                )
            )
            or (
                self.provider == "stripe"
                and self.account_id is not None
                and not self.account_id.startswith("acct_")
            )
            or (
                self.provider == "razorpay"
                and (not self.api_secret or not 16 <= len(self.api_secret) <= 8192)
            )
        ):
            raise ValueError("Complete explicit billing configuration required")

    @property
    def scope(self):
        return (self.account_id or "self") + (":live" if self.live_mode else ":test")

    def fetch(self, binding):
        return fetch_subscription(
            binding,
            api_key=self.api_key,
            api_secret=self.api_secret,
            stripe_version=self.stripe_version,
        )


def create_ingress(engine, configurations: tuple[ProviderConfiguration, ...]):
    """Separate operator service; never mounted in the tenant application.

    Paths select reviewed endpoint config, not sender-provided account/workspace.
    No checkout state or source credentials are accepted. TLS belongs to the
    deployment reverse proxy. No service is started by importing this module.
    """
    if not 1 <= len(configurations) <= 8:
        raise ValueError("Configure one to eight billing endpoints")
    endpoints = {(config.provider, config.scope): config for config in configurations}
    if len(endpoints) != len(configurations):
        raise ValueError("Duplicate billing endpoint configuration")
    with engine.connect() as connection:
        operator(connection)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/webhooks/{provider}/{account_scope}")
    async def receive_webhook(provider: str, account_scope: str, request: Request):
        config = endpoints.get((provider, account_scope))
        if config is None:
            raise HTTPException(404, "Billing endpoint unavailable")
        header = b"stripe-signature" if provider == "stripe" else b"x-razorpay-signature"
        signatures = [value for key, value in request.scope["headers"] if key.lower() == header]
        if len(signatures) != 1 or len(signatures[0]) > 4096:
            raise HTTPException(400, "Invalid billing event")
        deadline, body = time.monotonic() + 5, bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY or time.monotonic() > deadline:
                        raise HTTPException(413, "Billing event exceeds intake bounds")
                    body.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Billing event intake timed out") from None
        try:
            signature = signatures[0].decode("ascii")

            def persist():
                with engine.begin() as connection:
                    connection.execute(sa.text("SET LOCAL statement_timeout='3000ms'"))
                    return receive_bound(
                        connection,
                        provider,
                        bytes(body),
                        signature,
                        secret=config.webhook_secret,
                        now=int(time.time()),
                        account_id=config.account_id,
                        live_mode=config.live_mode,
                    )

            status = await run_in_threadpool(persist)
            return {"status": status}
        except (InvalidBillingEvent, UnicodeError, LookupError):
            raise HTTPException(400, "Invalid billing event") from None
        except sa.exc.SQLAlchemyError:
            raise HTTPException(503, "Billing intake unavailable") from None

    return app


def _process(connection, workspace, config, fetch):
    """Session advisory lock spans committed attempt accounting and provider read."""
    lock_key = "billing-runtime:" + str(workspace)
    leased = connection.execute(
        sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": lock_key}
    ).scalar_one()
    connection.commit()
    if not leased:
        return "busy"
    try:
        with connection.begin():
            binding = (
                connection.execute(sa.select(bindings).where(bindings.c.workspace_id == workspace))
                .mappings()
                .one()
            )
            pending = (
                connection.execute(
                    sa.select(inbox)
                    .where(
                        inbox.c.workspace_id == workspace,
                        inbox.c.provider == config.provider,
                        inbox.c.account_scope == config.scope,
                        inbox.c.state == "pending",
                    )
                    .order_by(inbox.c.received_at, inbox.c.event_key)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            now = connection.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            if pending is None:
                has_audit = connection.execute(
                    sa.select(audit.c.id).where(audit.c.workspace_id == workspace).limit(1)
                ).scalar_one_or_none()
                if has_audit and binding["updated_at"] > now - timedelta(minutes=5):
                    return "idle"
                key = queue_refresh(connection, workspace)
                pending = (
                    connection.execute(
                        sa.select(inbox).where(
                            inbox.c.provider == config.provider,
                            inbox.c.account_scope == config.scope,
                            inbox.c.event_key == key,
                        )
                    )
                    .mappings()
                    .one()
                )
            if pending["next_attempt_at"] > now:
                return "deferred"
            where = (
                inbox.c.provider == config.provider,
                inbox.c.account_scope == config.scope,
                inbox.c.event_key == pending["event_key"],
            )
            if pending["attempt_count"] >= 5:
                connection.execute(sa.update(inbox).where(*where).values(state="quarantined"))
                return "quarantined"
            attempt = pending["attempt_count"] + 1
            # Commit before I/O so worker loss cannot erase attempt consumption.
            connection.execute(
                sa.update(inbox)
                .where(*where)
                .values(
                    attempt_count=attempt,
                    next_attempt_at=now + timedelta(seconds=min(60 * 2 ** (attempt - 1), 900)),
                )
            )
            key = pending["event_key"]
        try:
            with connection.begin():
                connection.execute(sa.text("SET LOCAL lock_timeout='3000ms'"))
                return reconcile(
                    connection,
                    workspace,
                    key,
                    allowance=load(connection, workspace),
                    fetch_current=fetch,
                )
        except Exception:  # noqa: BLE001 - retain bounded retry, never log provider secrets
            connection.rollback()
            if attempt == 5:
                with connection.begin():
                    connection.execute(
                        sa.update(inbox)
                        .where(*where, inbox.c.state == "pending")
                        .values(state="quarantined")
                    )
            return "retry" if attempt < 5 else "quarantined"
    finally:
        connection.rollback()
        connection.execute(
            sa.text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": lock_key}
        )
        connection.commit()


def run_once(
    engine, configurations: tuple[ProviderConfiguration, ...], *, limit=10, fetch_current=None
):
    """At most ten workspaces, one bounded GET each; no unconfigured accounts."""
    if type(limit) is not int or not 1 <= limit <= 10 or not 1 <= len(configurations) <= 8:
        raise ValueError("Bounded billing batch required")
    configs = {(config.provider, config.scope): config for config in configurations}
    if len(configs) != len(configurations):
        raise ValueError("Duplicate billing endpoint configuration")
    with engine.begin() as connection:
        operator(connection)
        pending = sa.exists(
            sa.select(inbox.c.event_key).where(
                inbox.c.workspace_id == bindings.c.workspace_id,
                inbox.c.state == "pending",
            )
        )
        due = sa.exists(
            sa.select(inbox.c.event_key).where(
                inbox.c.workspace_id == bindings.c.workspace_id,
                inbox.c.state == "pending",
                inbox.c.next_attempt_at <= sa.func.clock_timestamp(),
            )
        )
        quarantined = sa.exists(
            sa.select(inbox.c.event_key).where(
                inbox.c.workspace_id == bindings.c.workspace_id,
                inbox.c.state == "quarantined",
            )
        )
        history = sa.exists(
            sa.select(audit.c.id).where(audit.c.workspace_id == bindings.c.workspace_id)
        )
        rows = (
            connection.execute(
                sa.select(bindings)
                .where(
                    sa.or_(
                        *(
                            sa.and_(
                                bindings.c.provider == provider, bindings.c.account_scope == scope
                            )
                            for provider, scope in configs
                        )
                    ),
                    sa.or_(
                        due,
                        sa.and_(
                            ~pending,
                            ~quarantined,
                            sa.or_(
                                ~history,
                                bindings.c.updated_at
                                <= sa.func.clock_timestamp() - timedelta(minutes=5),
                            ),
                        ),
                    ),
                )
                .order_by(bindings.c.updated_at, bindings.c.workspace_id)
                .limit(limit)
            )
            .mappings()
            .all()
        )
    statuses = []
    for binding in rows:
        config = configs[(binding["provider"], binding["account_scope"])]
        with engine.connect() as connection:
            statuses.append(
                _process(connection, binding["workspace_id"], config, fetch_current or config.fetch)
            )
    return statuses
