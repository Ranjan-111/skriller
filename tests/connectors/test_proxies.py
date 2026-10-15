"""Synthetic provider transport: no public or account-backed source calls."""

import base64
import json
import socket
from threading import Thread

import pytest

from skriller.connectors import proxies
from skriller.security import proxy as gateway
from skriller.security.urls import Destination, EgressDenied


def config(**updates):
    value = {
        "providers": [
            {
                "server": "http://provider.example",
                "username": "sticky-task-1",
                "password": "tenant-secret",
            }
        ],
        "usd_per_gb": "4",
        "max_attempts": 3,
        "max_bytes": 4096,
    }
    value.update(updates)
    return proxies.ProxyConfiguration.parse(json.dumps(value))


@pytest.mark.parametrize(
    "updates",
    [
        {"max_attempts": 4},
        {"max_attempts": True},
        {"max_bytes": 0},
        {"usd_per_gb": "NaN"},
        {
            "providers": [
                {"server": "http://u:secret@proxy.example", "username": "x", "password": "y"}
            ]
        },
        {"providers": [{"server": "http://proxy.example:8080", "username": "x", "password": "y"}]},
    ],
)
def test_configuration_limits_and_redaction(updates):
    with pytest.raises(ValueError, match="Invalid encrypted proxy configuration"):
        config(**updates)
    assert "tenant-secret" not in repr(config())
    assert "sticky-task-1" not in repr(config())


@pytest.mark.local_server
def test_numeric_tunnel_and_destination_headers(monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    captured = []

    def provider():
        with listener.accept()[0] as sock:
            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                header.extend(sock.recv(1))
            captured.append(bytes(header))
            sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            request = bytearray()
            while not request.endswith(b"\r\n\r\n"):
                request.extend(sock.recv(1))
            captured.append(bytes(request))
            sock.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nok"
            )

    thread = Thread(target=provider, daemon=True)
    thread.start()
    monkeypatch.setattr(
        proxies,
        "resolve_public_destination",
        lambda url: Destination(url, "provider.example", 80, ("93.184.216.34",)),
    )
    monkeypatch.setattr(
        proxies,
        "connect_pinned",
        lambda destination, timeout=10: socket.create_connection(listener.getsockname()),
    )
    monkeypatch.setattr(
        gateway,
        "resolve_public_destination",
        lambda url: Destination(url, "source.example", 80, ("93.184.216.35",)),
    )
    accounting = []
    route = proxies.StickyProxyContext(
        config(),
        authenticated=True,
        before=lambda d, i: (i, "token"),
        after=lambda *args: accounting.append(args),
        check=lambda: None,
    )
    server = gateway.GuardedProxy(("127.0.0.1", 0), upstream_route=route)
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        with socket.create_connection(server.server_address) as client:
            client.sendall(
                b"GET http://source.example/page HTTP/1.0\r\nProxy-Authorization: private-client-secret\r\n\r\n"
            )
            response = bytearray()
            while chunk := client.recv(4096):
                response.extend(chunk)
        assert bytes(response).endswith(b"ok")
    finally:
        server.shutdown()
        server.server_close()
        listener.close()
        thread.join(2)
    assert captured[0].startswith(b"CONNECT 93.184.216.35:80 HTTP/1.1")
    assert base64.b64encode(b"sticky-task-1:tenant-secret") in captured[0]
    assert captured[1].startswith(b"GET /page HTTP/1.1\r\nHost: source.example")
    assert b"Authorization" not in captured[1]
    assert b"tenant-secret" not in captured[1]
    assert accounting[0][1] > 2 and accounting[0][2] is True


def test_unavailable_provider_is_accounted_without_direct_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(
        proxies.Provider,
        "tunnel",
        lambda *_, **_kwargs: (_ for _ in ()).throw(OSError("connection refused secret")),
    )
    monkeypatch.setattr(proxies, "connect_pinned", lambda *_: pytest.fail("No direct fallback"))
    route = proxies.StickyProxyContext(
        config(),
        authenticated=True,
        before=lambda d, i: (i, "token"),
        after=lambda *args: calls.append(args),
        check=lambda: None,
    )
    with pytest.raises(proxies.ProxyUnavailable) as caught:
        route.connect(
            Destination("http://source.example", "source.example", 80, ("93.184.216.35",))
        )
    assert "secret" not in str(caught.value)
    assert calls == [("token", 0, False)]


def test_metered_socket_byte_budget_and_stop(monkeypatch):
    class FakeSocket:
        def sendall(self, value):
            pass

        def close(self):
            pass

    calls = []
    route = proxies.StickyProxyContext(
        config(),
        authenticated=False,
        before=lambda *_: None,
        after=lambda *args: calls.append(args),
        check=lambda: None,
    )
    with (
        pytest.raises(proxies.ProxyUnavailable, match="traffic budget"),
        proxies.MeteredSocket(FakeSocket(), route, ("route", "reservation", 2)) as sock,
    ):
        sock.sendall(b"abc")
    assert calls == [(("route", "reservation", 2), 0, False)]
    route.check = lambda: (_ for _ in ()).throw(EgressDenied("Stopped"))
    with (
        pytest.raises(EgressDenied, match="Stopped"),
        proxies.MeteredSocket(FakeSocket(), route, "token") as sock,
    ):
        sock.sendall(b"a")
    assert calls[-1] == ("token", 0, False)


@pytest.mark.local_server
def test_gateway_requires_opaque_server_token_before_destination_resolution(monkeypatch):
    import httpx

    monkeypatch.setattr(
        gateway,
        "resolve_public_destination",
        lambda *_: pytest.fail("Unauthorized route must not resolve"),
    )
    server = gateway.GuardedProxy(
        ("127.0.0.1", 0), client_token="server-issued-unpredictable-token"
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            proxy=f"http://127.0.0.1:{server.server_port}", trust_env=False
        ) as client:
            response = client.get(
                "http://source.example/page",
                headers={"X-Workspace-Id": "forged", "X-Job-Id": "forged"},
            )
        assert response.status_code == 407
    finally:
        server.shutdown()
        server.server_close()


def test_trusted_route_still_rejects_private_numeric_destination():
    route = proxies.StickyProxyContext(
        config(),
        authenticated=False,
        before=lambda *_: pytest.fail("Private target must never reserve or dial"),
        after=lambda *_: None,
        check=lambda: None,
    )
    with pytest.raises(EgressDenied, match="public egress"):
        route.connect(
            Destination("http://source.example/private", "source.example", 80, ("127.0.0.1",))
        )


def test_async_startup_cancellation_waits_for_gateway_cleanup():
    import asyncio
    from threading import Event

    from skriller.connectors.fetch import HTTPFetcher

    entered, finish, cleaned = Event(), Event(), Event()

    class Manager:
        def __enter__(self):
            entered.set()
            assert finish.wait(2)
            return "http://127.0.0.1:8080"

        def __exit__(self, *_):
            cleaned.set()

    async def scenario():
        fetcher = HTTPFetcher(
            None,
            trusted_proxy_url="http://127.0.0.1:8080",
            proxy_route_factory=lambda *_: Manager(),
        )

        async def operation():
            async with fetcher.proxy_for(None, "web"):
                pytest.fail("Cancelled startup must not dispatch")

        task = asyncio.create_task(operation())
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_async_cleanup_cancellation_waits_for_owned_gateway():
    import asyncio
    from threading import Event

    from skriller.connectors.fetch import HTTPFetcher

    exiting, finish, cleaned = Event(), Event(), Event()

    class Manager:
        def __enter__(self):
            return "http://127.0.0.1:8080"

        def __exit__(self, *_):
            exiting.set()
            assert finish.wait(2)
            cleaned.set()

    async def scenario():
        fetcher = HTTPFetcher(
            None,
            trusted_proxy_url="http://127.0.0.1:8080",
            proxy_route_factory=lambda *_: Manager(),
        )

        async def operation():
            async with fetcher.proxy_for(None, "web"):
                pass

        task = asyncio.create_task(operation())
        assert await asyncio.to_thread(exiting.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())
