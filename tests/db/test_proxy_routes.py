"""Durable sticky route, encryption, accounting and tenant isolation in PostgreSQL."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.connections.keys import Keyring
from skriller.connections.lifecycle import reconnect
from skriller.connections.store import ConnectionStore, ConnectionUnavailable, SecretPayload
from skriller.connections.tables import proxy_routes, secrets
from skriller.connectors import proxies
from skriller.contracts import ExecutionContext, Limits, SearchPlan
from skriller.db import ConversationRepository
from skriller.db.schema import reservations
from skriller.jobs.outbox import submit
from skriller.security.urls import Destination, EgressDenied

pytestmark = pytest.mark.integration_db


def setup(database, *, authenticated=False):
    actor = f"proxy-{uuid4()}"
    workspace = database.create_workspace(actor, "Proxy test")["id"]
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    raw = json.dumps(
        {
            "providers": [
                {
                    "server": "http://one.example",
                    "username": "sticky-one",
                    "password": "tenant-private-one",
                },
                {
                    "server": "http://two.example",
                    "username": "sticky-two",
                    "password": "tenant-private-two",
                },
            ],
            "usd_per_gb": "4",
            "max_attempts": 3,
            "max_bytes": 4096,
        }
    )
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Proxy fixture")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="person",
            sources=["linkedin"],
            limits=Limits(currency_cap="0.1"),
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
        provider = store.create(
            session,
            "proxy",
            "api_key",
            SecretPayload(credentials={"api_key": raw}),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        account = (
            store.create(
                session,
                "linkedin",
                "session",
                SecretPayload(credentials={"session_cookie": "account-cookie"}),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            if authenticated
            else None
        )
    context = ExecutionContext(
        workspace_id=UUID(workspace),
        job_id=UUID(job["id"]),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=2),
        attempt_budget=3,
        connection_ref=account.id if account else None,
    )
    return store, context, provider, raw


class Socket:
    def sendall(self, data):
        pass

    def recv(self, size):
        return b"body"

    def close(self):
        pass


def target(path="one"):
    return Destination(f"http://source.example/{path}", "source.example", 80, ("93.184.216.35",))


def test_sticky_multipage_encrypted_billing_and_reconnect(database, monkeypatch):
    store, context, provider, raw = setup(database, authenticated=True)
    used = []
    monkeypatch.setattr(
        proxies.Provider,
        "tunnel",
        lambda self, *_, **_kwargs: (used.append(self.server), Socket())[1],
    )
    for path in ("one", "two"):
        route = proxies.task_route(
            database, store, context, source="linkedin", proxy_connection_ref=provider.id
        )
        with route.connect(target(path)) as sock:
            sock.sendall(b"request")
            assert sock.recv(4) == b"body"
    assert used == ["http://one.example", "http://one.example"]
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        row = (
            session.execute(
                sa.select(proxy_routes).where(proxy_routes.c.job_id == str(context.job_id))
            )
            .mappings()
            .one()
        )
        assert row["traffic_bytes"] == 22 and row["attempts"] == 2
        accounting = (
            session.execute(
                sa.select(reservations).where(reservations.c.job_id == str(context.job_id))
            )
            .mappings()
            .all()
        )
        assert len(accounting) == 2 and all(
            r["reconciliation_status"] == "confirmed" for r in accounting
        )
        assert all(r["actual_cost_usd"] > 0 for r in accounting)
        encrypted = (
            session.execute(sa.select(secrets).where(secrets.c.connection_id == str(provider.id)))
            .mappings()
            .one()
        )
        assert b"tenant-private" not in encrypted["ciphertext"]
        replacement = reconnect(
            session,
            store,
            provider.id,
            SecretPayload(credentials={"api_key": raw}),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    with pytest.raises(ConnectionUnavailable):
        proxies.task_route(
            database, store, context, source="linkedin", proxy_connection_ref=provider.id
        )
    route = proxies.task_route(
        database, store, context, source="linkedin", proxy_connection_ref=replacement.id
    )
    with pytest.raises(EgressDenied, match="rebinding"):
        route.connect(target("three"))
    assert len(used) == 2


@pytest.mark.parametrize("authenticated", [True, False])
def test_failure_rotation_exhaustion_and_estimated_reservation(
    database, monkeypatch, authenticated
):
    store, context, provider, _ = setup(database, authenticated=authenticated)
    used = []

    def unavailable(self, *_, **_kwargs):
        used.append(self.server)
        raise OSError("connection refused private-token")

    monkeypatch.setattr(proxies.Provider, "tunnel", unavailable)
    route = proxies.task_route(
        database, store, context, source="linkedin", proxy_connection_ref=provider.id
    )
    with pytest.raises(proxies.ProxyUnavailable):
        route.connect(target())
    if authenticated:
        with pytest.raises(EgressDenied, match="Authenticated task route failed"):
            route.connect(target())
        assert used == ["http://one.example"]
    else:
        for _ in range(2):
            with pytest.raises(proxies.ProxyUnavailable):
                route.connect(target())
        with pytest.raises(EgressDenied, match="attempt budget"):
            route.connect(target())
        assert used == ["http://one.example", "http://two.example", "http://one.example"]
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        accounting = (
            session.execute(
                sa.select(reservations).where(reservations.c.job_id == str(context.job_id))
            )
            .mappings()
            .all()
        )
        assert all(
            r["reconciliation_status"] == "estimated" and r["amount_usd"] > 0 for r in accounting
        )


def test_direct_public_guard_private_provider_credentials_and_scope(database, monkeypatch):
    store, context, provider, _ = setup(database)
    calls = []
    monkeypatch.setattr(
        proxies, "connect_pinned", lambda d, **_kwargs: (calls.append(d), Socket())[1]
    )
    route = proxies.task_route(database, store, context, source="linkedin")
    with route.connect(target()) as sock:
        sock.sendall(b"request")
    assert len(calls) == 1
    with (
        database.tenant(context.actor_id, str(context.workspace_id)) as session,
        pytest.raises(ConnectionUnavailable),
    ):
        store.load_for_runner(
            session, context.model_copy(update={"connection_ref": provider.id}), "linkedin_read"
        )
    _other_store, other_context, _, _ = setup(database)
    with pytest.raises(ConnectionUnavailable):
        proxies.task_route(
            database, store, other_context, source="linkedin", proxy_connection_ref=provider.id
        )
    with database.tenant(other_context.actor_id, str(other_context.workspace_id)) as session:
        assert (
            session.execute(
                sa.select(proxy_routes).where(proxy_routes.c.job_id == str(context.job_id))
            ).first()
            is None
        )
    with pytest.raises(EgressDenied):
        proxies.task_route(
            database, store, context, source="reddit", proxy_connection_ref=provider.id
        )


def test_native_http_runtime_uses_tenant_provider_and_existing_fetch_budget(database, monkeypatch):
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from skriller.connectors.fetch import HTTPFetcher
    from skriller.security import proxy as gateway

    store, context, _provider, _ = setup(database)
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            captured.append(dict(self.headers))
            body = b"<html><body><h1>Public research page</h1><p>Independent researcher in software systems.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    providers_used = []

    def tunnel(self, _destination, **_kwargs):
        providers_used.append(self.server)
        return socket.create_connection(origin.server_address)

    monkeypatch.setattr(proxies.Provider, "tunnel", tunnel)
    monkeypatch.setattr(
        gateway,
        "resolve_public_destination",
        lambda url: Destination(url, "source.example", 80, ("93.184.216.35",)),
    )
    monkeypatch.setattr(ConnectionStore, "configured", classmethod(lambda cls, settings: store))
    try:
        artifact = HTTPFetcher(database, trusted_proxy_url="http://127.0.0.1:8080").fetch(
            context,
            "http://source.example/page",
            source="linkedin",
            operation_key="native-provider",
        )
        assert b"Public research page" in artifact.response.body
        assert artifact.attempts == 1
    finally:
        origin.shutdown()
        origin.server_close()
    assert providers_used == ["http://one.example"]
    assert "Proxy-Authorization" not in captured[0]
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        rows = (
            session.execute(
                sa.select(reservations).where(reservations.c.job_id == str(context.job_id))
            )
            .mappings()
            .all()
        )
        assert sum(r["actual_dimensions"].get("fetch_attempts", 0) for r in rows) == 1
        assert any(r["actual_cost_usd"] > 0 for r in rows)


def test_stop_and_traffic_budget_are_enforced_before_provider_call(database, monkeypatch):
    from skriller.jobs.control import cancel

    store, context, provider, _ = setup(database)
    used = []
    monkeypatch.setattr(
        proxies.Provider,
        "tunnel",
        lambda self, *_, **kwargs: (used.append(self.server), Socket())[1],
    )
    route = proxies.task_route(
        database, store, context, source="linkedin", proxy_connection_ref=provider.id
    )
    with route.connect(target()) as sock:
        sock.sendall(b"x" * 4096)
    with pytest.raises(EgressDenied, match="traffic budget"):
        route.connect(target("two"))
    assert len(used) == 1
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        cancel(session, str(context.job_id))
    with pytest.raises(EgressDenied, match="scope unavailable"):
        route.connect(target("three"))
    assert len(used) == 1


def test_configured_provider_prevents_browser_route_fallback(database):
    from skriller.connectors.browser import DynamicBrowserAdapter
    from skriller.connectors.fetch import FetchUnavailable

    _store, context, _provider, _ = setup(database)

    class Executor:
        def execute(self, *_args, **_kwargs):
            pytest.fail("Browser must not silently use another route")

    browser = DynamicBrowserAdapter(database, executor=Executor(), isolation_verified=True)
    with pytest.raises(FetchUnavailable) as caught:
        browser.fetch(
            context,
            "http://source.example/page",
            source="linkedin",
            readiness_selector="body",
            operation_key="browser-provider",
        )
    assert caught.value.failure.code == "unsupported_operation"
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert (
            session.execute(
                sa.select(reservations).where(reservations.c.job_id == str(context.job_id))
            ).first()
            is None
        )


def test_explicit_direct_binding_survives_provider_added_mid_task(database):
    store, context, provider, raw = setup(database, authenticated=True)
    # Start with no active provider; account task still has its explicit account ref.
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        store.revoke(session, provider.id)
    for expected_pages in (1, 2):
        with proxies.configured_task_proxy(
            database, context, source="linkedin", trusted_proxy_url="http://127.0.0.1:8080"
        ) as url:
            assert url == "http://127.0.0.1:8080"
        if expected_pages == 1:
            with database.tenant(context.actor_id, str(context.workspace_id)) as session:
                store.create(
                    session,
                    "proxy",
                    "api_key",
                    SecretPayload(credentials={"api_key": raw}),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        row = (
            session.execute(
                sa.select(proxy_routes).where(proxy_routes.c.job_id == str(context.job_id))
            )
            .mappings()
            .one()
        )
        assert row["connection_id"] is None and row["configuration_digest"] == "direct"
        assert row["account_connection_id"] == str(context.connection_ref)
