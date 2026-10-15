"""Task-scoped upstream tunnels behind the mandatory public egress guard.

Provider credentials are encrypted proxy-purpose connections, never destination
headers. A route object belongs to one validated task; clients cannot select it.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import ssl
from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from pydantic import SecretStr
from scrapling.engines.toolbelt.proxy_rotation import ProxyRotator, cyclic_rotation, is_proxy_error

from skriller.security.urls import (
    Destination,
    EgressDenied,
    connect_pinned,
    resolve_public_destination,
)


class ProxyUnavailable(OSError):
    """Redacted provider failure; never embeds an endpoint or credential."""


@dataclass(frozen=True)
class Provider:
    server: str
    username: SecretStr = field(repr=False)
    password: SecretStr = field(repr=False)

    def __post_init__(self):
        parsed = urlsplit(self.server)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}
        ):
            raise ValueError("Provider requires a standard public HTTP(S) endpoint")
        for value in (self.username, self.password):
            plain = value.get_secret_value()
            if not 1 <= len(plain) <= 1024 or any(c in plain for c in "\r\n\0"):
                raise ValueError("Invalid provider credential")
        if ":" in self.username.get_secret_value():
            raise ValueError("Invalid provider username")

    def tunnel(self, destination: Destination, *, timeout=10):
        """Provider must CONNECT to the vetted numeric IP, never resolve target DNS."""
        sock = None
        deadline = monotonic() + timeout
        try:
            endpoint = resolve_public_destination(self.server)
            sock = connect_pinned(endpoint, timeout=timeout)
            if urlsplit(self.server).scheme == "https":
                sock = ssl.create_default_context().wrap_socket(
                    sock, server_hostname=endpoint.hostname
                )
            address = destination.addresses[0]
            authority = (
                f"[{address}]:{destination.port}"
                if ":" in address
                else f"{address}:{destination.port}"
            )
            credentials = f"{self.username.get_secret_value()}:{self.password.get_secret_value()}"
            auth = base64.b64encode(credentials.encode()).decode("ascii")
            sock.sendall(
                (
                    f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                    f"Proxy-Authorization: Basic {auth}\r\n\r\n"
                ).encode("ascii")
            )
            # Read exactly the handshake; never discard initial tunneled bytes.
            response = bytearray()
            while not response.endswith(b"\r\n\r\n"):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ProxyUnavailable("Provider handshake deadline reached")
                sock.settimeout(remaining)
                chunk = sock.recv(1)
                if not chunk or len(response) >= 8192:
                    raise ProxyUnavailable("Provider tunnel unavailable")
                response.extend(chunk)
            status = bytes(response).split(b"\r\n", 1)[0].split()
            if (
                len(status) < 2
                or status[0] not in {b"HTTP/1.0", b"HTTP/1.1"}
                or status[1] != b"200"
            ):
                raise ProxyUnavailable("Provider tunnel refused")
            return sock
        except Exception as error:  # noqa: BLE001 - provider exceptions may contain secrets
            # Copied classification only determines typed diagnostics; it must
            # never trigger an unbudgeted automatic retry or direct fallback.
            proxy_error = is_proxy_error(error)
            if sock is not None:
                sock.close()
            raise ProxyUnavailable(
                "Provider transport unavailable" if proxy_error else "Provider tunnel unavailable"
            ) from None


@dataclass(frozen=True)
class ProxyConfiguration:
    providers: tuple[Provider, ...]
    usd_per_gb: Decimal
    max_attempts: int = 3
    max_bytes: int = 10 * 1024 * 1024

    @classmethod
    def parse(cls, value: str):
        try:
            data = json.loads(value)
            if set(data) != {"providers", "usd_per_gb", "max_attempts", "max_bytes"}:
                raise ValueError
            providers = tuple(
                Provider(row["server"], SecretStr(row["username"]), SecretStr(row["password"]))
                for row in data["providers"]
                if set(row) == {"server", "username", "password"}
            )
            if len(providers) != len(data["providers"]) or not 1 <= len(providers) <= 8:
                raise ValueError
            rate = Decimal(str(data["usd_per_gb"]))
            attempts, size = data["max_attempts"], data["max_bytes"]
            if (
                not rate.is_finite()
                or not 0 <= rate <= 1000
                or type(attempts) is not int
                or not 1 <= attempts <= 3
                or type(size) is not int
                or not 1 <= size <= 10 * 1024 * 1024
            ):
                raise ValueError
            return cls(providers, rate, attempts, size)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise ValueError("Invalid encrypted proxy configuration") from None

    def cost(self, byte_count):
        # Round upward to the shared six-decimal money precision.
        from decimal import ROUND_UP

        return (self.usd_per_gb * Decimal(byte_count) / Decimal(1_000_000_000)).quantize(
            Decimal("0.000001"), rounding=ROUND_UP
        )


class StickyProxyContext:
    """Bounded copied rotation; authenticated contexts fail closed on failure.

    Persistent control-plane callbacks validate task scope and reserve cost
    before every provider call. This class itself accepts no HTTP client IDs.
    """

    def __init__(self, configuration, *, authenticated, before, after, check):
        self.configuration = configuration
        self.authenticated = authenticated
        self.before, self.after, self.check = before, after, check
        self._lock = Lock()
        self._rotator = (
            ProxyRotator(
                [
                    {"server": p.server, "username": str(i)}
                    for i, p in enumerate(configuration.providers)
                ],
                cyclic_rotation,
            )
            if configuration
            else None
        )

    def connect(self, destination):
        # Defense in depth for trusted adapters calling the route directly.
        parsed = urlsplit(destination.url)
        try:
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or parsed.hostname != destination.hostname
                or not destination.addresses
                or destination.port != (443 if parsed.scheme == "https" else 80)
            ):
                raise ValueError
            for address in destination.addresses:
                ip = ipaddress.ip_address(address)
                if (
                    not ip.is_global
                    or ip.is_multicast
                    or ip.is_reserved
                    or getattr(ip, "ipv4_mapped", None)
                ):
                    raise ValueError
        except ValueError:
            raise EgressDenied("Task destination is outside public egress policy") from None
        with self._lock:
            timeout = self.check() or 10
            selected = self._rotator.get_proxy() if self._rotator else None
            proposed = int(selected["username"]) if selected else None
            # Durable before() returns the persisted sticky index and rejects
            # changed configuration, exhausted counters and authenticated failures.
            index, token = self.before(destination, proposed)
            try:
                sock = (
                    self.configuration.providers[index].tunnel(
                        destination, timeout=min(10, timeout)
                    )
                    if self.configuration
                    else connect_pinned(destination, timeout=min(10, timeout))
                )
            except Exception:  # noqa: BLE001 - redact provider failures after accounting
                self.after(token, 0, False)
                raise ProxyUnavailable("Task egress route unavailable") from None
            try:
                self.check()
            except Exception:
                sock.close()
                self.after(token, 0, False)
                raise
            return MeteredSocket(sock, self, token)


class MeteredSocket:
    def __init__(self, sock, route, token):
        self.sock, self.route, self.token = sock, route, token
        self.bytes = 0
        self.failed = False
        self.closed = False

    def fileno(self):
        return self.sock.fileno()

    def _charge(self, count):
        limit = (
            self.token[2]
            if isinstance(self.token, tuple) and len(self.token) == 3
            else (
                self.route.configuration.max_bytes if self.route.configuration else 10 * 1024 * 1024
            )
        )
        if self.bytes + count > limit:
            self.failed = True
            raise ProxyUnavailable("Task traffic budget exhausted")
        self.bytes += count

    def recv(self, size):
        self.route.check()
        try:
            limit = (
                self.token[2]
                if isinstance(self.token, tuple) and len(self.token) == 3
                else (
                    self.route.configuration.max_bytes
                    if self.route.configuration
                    else 10 * 1024 * 1024
                )
            )
            if self.bytes >= limit:
                self.failed = True
                raise ProxyUnavailable("Task traffic budget exhausted")
            value = self.sock.recv(min(size, 65536, limit - self.bytes))
            self._charge(len(value))
            return value
        except Exception:
            self.failed = True
            raise

    def sendall(self, value):
        self.route.check()
        self._charge(len(value))
        try:
            self.sock.sendall(value)
        except Exception:
            self.failed = True
            raise

    def __enter__(self):
        return self

    def __exit__(self, kind, *_):
        self.close(ok=kind is None)

    def close(self, *, ok=True):
        if not self.closed:
            self.closed = True
            self.sock.close()
            self.route.after(self.token, self.bytes, ok and not self.failed)


def task_route(database, store, context, *, source, proxy_connection_ref=None):
    """Build a trusted gateway route from validated scope and encrypted secrets.

    The gateway reserves monetary traffic exposure separately from the HTTP or
    browser adapter's fetch/capacity reservation. It does not retry network I/O.
    Callers still use their bounded adapter through this GuardedProxy instance.
    """
    from datetime import UTC, datetime

    import sqlalchemy as sa

    from skriller.connections.tables import proxy_routes
    from skriller.connectors.switches import is_disabled
    from skriller.db import ConversationRepository
    from skriller.db.repositories import insert_row, scope
    from skriller.db.schema import reservations
    from skriller.jobs.budget import locked_job, reconcile, reserve
    from skriller.jobs.control import permit_call

    def validated(session):
        job = locked_job(session, str(context.job_id))
        plan = ConversationRepository.get_plan(session, job["plan_id"])
        if (
            str(context.workspace_id) != scope(session)
            or context.actor_id != session.info["actor_id"]
            or job["created_by"] != context.actor_id
            or plan["revision"] != context.plan_revision
            or source not in plan["interpretation"]["sources"]
            or datetime.now(UTC) >= context.deadline
            or permit_call(session, job["id"]) <= 0
            or is_disabled(session, source, "read")
        ):
            raise EgressDenied("Task egress scope unavailable")
        if context.connection_ref is not None:
            account = store.metadata(session, context.connection_ref)
            if (
                account.state != "active"
                or account.source != source
                or "read" not in account.scopes
            ):
                raise EgressDenied("Task account connection unavailable")
        return job

    def configuration(session):
        if proxy_connection_ref is None:
            return None, "direct"
        material = store.load_for_runner(
            session,
            context.model_copy(update={"connection_ref": proxy_connection_ref}),
            "proxy_route",
        )
        raw = material.environment["SKR_PROXY_CONFIGURATION"].get_secret_value()
        return ProxyConfiguration.parse(raw), sha256(raw.encode()).hexdigest()

    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        validated(session)
        config, digest = configuration(session)
        if config is None:
            row = (
                session.execute(
                    sa.select(proxy_routes)
                    .where(
                        proxy_routes.c.workspace_id == scope(session),
                        proxy_routes.c.job_id == str(context.job_id),
                        proxy_routes.c.source == source,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            account_id = str(context.connection_ref) if context.connection_ref else None
            if row is None:
                insert_row(
                    session,
                    proxy_routes,
                    job_id=str(context.job_id),
                    source=source,
                    connection_id=None,
                    account_connection_id=account_id,
                    configuration_digest="direct",
                    provider_index=None,
                    created_by=context.actor_id,
                )
            elif row["connection_id"] is not None or row["account_connection_id"] != account_id:
                raise EgressDenied("Task route rebinding requires a new task")

    def check():
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            validated(session)
            if (
                proxy_connection_ref is not None
                and store.metadata(session, proxy_connection_ref).state != "active"
            ):
                raise EgressDenied("Task proxy credential unavailable")
            return max(0.001, min(10, (context.deadline - datetime.now(UTC)).total_seconds()))

    def before(destination, proposed):
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            job = validated(session)
            _, current_digest = configuration(session)
            if digest != current_digest:
                raise EgressDenied("Task proxy configuration changed")
            row = (
                session.execute(
                    sa.select(proxy_routes)
                    .where(
                        proxy_routes.c.workspace_id == scope(session),
                        proxy_routes.c.job_id == job["id"],
                        proxy_routes.c.source == source,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                row = insert_row(
                    session,
                    proxy_routes,
                    job_id=job["id"],
                    source=source,
                    connection_id=str(proxy_connection_ref) if proxy_connection_ref else None,
                    account_connection_id=str(context.connection_ref)
                    if context.connection_ref
                    else None,
                    configuration_digest=digest,
                    provider_index=proposed,
                    created_by=context.actor_id,
                )
            if (
                row["configuration_digest"] != digest
                or row["connection_id"]
                != (str(proxy_connection_ref) if proxy_connection_ref else None)
                or row["account_connection_id"]
                != (str(context.connection_ref) if context.connection_ref else None)
            ):
                raise EgressDenied("Task route rebinding requires a new task")
            if context.connection_ref is not None and row["failed"]:
                raise EgressDenied("Authenticated task route failed; explicit restart required")
            limit = min(context.attempt_budget, config.max_attempts if config else 3)
            if row["attempts"] >= limit:
                raise EgressDenied("Task proxy attempt budget exhausted")
            size = config.max_bytes if config else 10 * 1024 * 1024
            if row["traffic_bytes"] >= size:
                raise EgressDenied("Task proxy traffic budget exhausted")
            size -= row["traffic_bytes"]
            active = session.execute(
                sa.select(sa.func.count())
                .select_from(reservations)
                .where(
                    reservations.c.workspace_id == scope(session),
                    reservations.c.job_id == job["id"],
                    reservations.c.state == "held",
                    reservations.c.idempotency_key.startswith("proxy:"),
                )
            ).scalar_one()
            if active:
                raise EgressDenied("Task proxy route is already occupied")
            prefix = "proxy:" + sha256(destination.url.encode()).hexdigest() + ":"
            count = session.execute(
                sa.select(sa.func.count())
                .select_from(reservations)
                .where(
                    reservations.c.workspace_id == scope(session),
                    reservations.c.job_id == job["id"],
                    reservations.c.idempotency_key.startswith(prefix),
                )
            ).scalar_one()
            if count >= 3:
                raise EgressDenied("Per-URL proxy attempt budget exhausted")
            index = row["provider_index"]
            if row["failed"] and config and context.connection_ref is None:
                # Use copied rotation, starting after the durable selected route.
                rotated, _ = cyclic_rotation(list(range(len(config.providers))), index + 1)
                index = rotated
            held = config.cost(size) if config else Decimal(0)
            reservation = reserve(
                session, job["id"], prefix + str(row["attempts"]), held, {"fetch_attempts": 0}
            )
            session.execute(
                sa.update(proxy_routes)
                .where(
                    proxy_routes.c.id == row["id"], proxy_routes.c.workspace_id == scope(session)
                )
                .values(attempts=row["attempts"] + 1, provider_index=index)
            )
            return index, (row["id"], reservation["id"], size)

    def after(token, transferred, success):
        identifier, reservation_id, size = token
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            locked_job(session, str(context.job_id))
            row = (
                session.execute(
                    sa.select(proxy_routes)
                    .where(
                        proxy_routes.c.id == identifier,
                        proxy_routes.c.workspace_id == scope(session),
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            reconcile(
                session,
                str(context.job_id),
                reservation_id,
                status="confirmed" if success else "estimated",
                cost=config.cost(min(transferred, size)) if config and success else 0,
                actual_dimensions={"fetch_attempts": 0} if success else None,
            )
            session.execute(
                sa.update(proxy_routes)
                .where(
                    proxy_routes.c.id == identifier, proxy_routes.c.workspace_id == scope(session)
                )
                .values(
                    traffic_bytes=row["traffic_bytes"] + min(transferred, size),
                    failed=row["failed"] or not success
                    if context.connection_ref is not None
                    else not success,
                )
            )

    return StickyProxyContext(
        config,
        authenticated=context.connection_ref is not None,
        before=before,
        after=after,
        check=check,
    )


from contextlib import contextmanager


@contextmanager
def task_guarded_proxy(database, store, context, *, source, proxy_connection_ref=None):
    """Trusted local adapter integration; endpoint lifetime is one task operation.

    Deployment must place this gateway on its existing isolated egress network;
    an ephemeral loopback gateway is for native controlled/local execution only.
    """
    from threading import Thread

    from skriller.security.proxy import GuardedProxy

    route = task_route(
        database, store, context, source=source, proxy_connection_ref=proxy_connection_ref
    )
    from secrets import token_urlsafe

    token = token_urlsafe(32)
    server = GuardedProxy(
        ("127.0.0.1", 0), max_connections=1, upstream_route=route, client_token=token
    )
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://task:{token}@127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def configured_task_proxy(database, context, *, source, trusted_proxy_url):
    """Native collection wiring for the tenant's explicit proxy connection.

    No provider connection preserves the existing fixed guarded route. A
    configured provider on a container gateway fails closed until that gateway
    has a server-authenticated control plane; credentials never enter workers'
    destination headers or a client-controlled route selector.
    """
    from datetime import UTC, datetime
    from uuid import UUID

    import sqlalchemy as sa

    from skriller.connections.store import ConnectionStore, ConnectionUnavailable
    from skriller.connections.tables import connections, proxy_routes
    from skriller.db.repositories import scope
    from skriller.settings import Settings

    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        existing = session.execute(
            sa.select(proxy_routes.c.connection_id).where(
                proxy_routes.c.workspace_id == scope(session),
                proxy_routes.c.job_id == str(context.job_id),
                proxy_routes.c.source == source,
            )
        ).first()
        if existing:
            reference = UUID(existing[0]) if existing[0] else None
        else:
            candidates = (
                session.execute(
                    sa.select(connections.c.id).where(
                        connections.c.workspace_id == scope(session),
                        connections.c.source == "proxy",
                        connections.c.state == "active",
                        connections.c.expires_at > datetime.now(UTC),
                    )
                )
                .scalars()
                .all()
            )
            if len(candidates) > 1:
                raise EgressDenied("Configure exactly one active tenant proxy connection")
            reference = UUID(candidates[0]) if candidates else None
    if reference is None:
        # Persist the explicit no-provider choice before the first dispatch.
        # Adding a tenant provider between pages must not change this task.
        task_route(database, ConnectionStore(None), context, source=source)
        yield trusted_proxy_url
        return
    parsed = urlsplit(trusted_proxy_url)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not local:
        raise EgressDenied(
            "Configured provider requires the native task gateway; hosted gateway wiring is pending"
        )
    store = ConnectionStore.configured(Settings())
    if store.keyring is None:
        raise ConnectionUnavailable("encryption_key_missing")
    with task_guarded_proxy(
        database, store, context, source=source, proxy_connection_ref=reference
    ) as proxy:
        yield proxy


def require_unconfigured_provider(database, context, *, source):
    """Prevent an adapter with a fixed gateway from changing a configured route."""
    from datetime import UTC, datetime

    import sqlalchemy as sa

    from skriller.connections.tables import connections, proxy_routes
    from skriller.db.repositories import scope

    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        configured = session.execute(
            sa.select(connections.c.id).where(
                connections.c.workspace_id == scope(session),
                connections.c.source == "proxy",
                connections.c.state == "active",
                connections.c.expires_at > datetime.now(UTC),
            )
        ).first()
        bound = session.execute(
            sa.select(proxy_routes.c.id).where(
                proxy_routes.c.workspace_id == scope(session),
                proxy_routes.c.job_id == str(context.job_id),
                proxy_routes.c.source == source,
                proxy_routes.c.connection_id.is_not(None),
            )
        ).first()
        if configured or bound:
            raise EgressDenied(
                "This adapter requires the pending isolated provider gateway integration"
            )
