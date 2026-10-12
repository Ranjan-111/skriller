import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from skriller.security import proxy, urls


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://2130706433",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal",
        "https://example.com:8443",
        "file:///etc/passwd",
        "http://user:password@example.com",
        "http://localhost",
        "http://[::1]",
    ],
)
def test_unsafe_urls_rejected_before_connection(url):
    with pytest.raises(urls.EgressDenied):
        urls.resolve_public_destination(url)


@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["93.184.216.34", "127.0.0.1"],
        ["224.0.0.1"],
        ["::ffff:127.0.0.1"],
        ["fc00::1"],
    ],
)
def test_dns_private_mixed_multicast_and_mapped_answers_fail_closed(monkeypatch, addresses):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80)) for address in addresses
        ],
    )
    with pytest.raises(urls.EgressDenied):
        urls.resolve_public_destination("http://public.example")


def test_pinned_connection_never_resolves_hostname_again(monkeypatch):
    dns_calls = []
    connections = []

    def resolve(host, port, **kwargs):
        dns_calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class Sock:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            connections.append(address)

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    destination = urls.resolve_public_destination("https://public.example")
    monkeypatch.setattr(socket, "socket", lambda *_args: Sock())
    urls.connect_pinned(destination)
    assert dns_calls == ["public.example"]
    assert connections == [("93.184.216.34", 443)]


def test_non_internet_sockaddr_answer_is_not_coerced_to_a_destination(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (123, 80))],
    )
    with pytest.raises(urls.EgressDenied):
        urls.resolve_public_destination("http://public.example")


@pytest.fixture
def local_guarded_proxy(monkeypatch):
    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"public fixture content")

        def log_message(self, *_args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    guard = proxy.GuardedProxy(("127.0.0.1", 0))
    original_dns = socket.getaddrinfo

    def resolver(host, port, *args, **kwargs):
        if host == "public.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        if host == "private.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))]
        return original_dns(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    observed = []

    def dial(destination):
        # Test-only transport injection after real production validation.
        # There is no allow-private configuration or fixture bypass in proxy.
        observed.append(destination)
        return socket.create_connection(upstream.server_address, timeout=2)

    monkeypatch.setattr(proxy, "connect_pinned", dial)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, guard)
    ]
    for thread in threads:
        thread.start()
    yield f"http://127.0.0.1:{guard.server_port}", observed
    for server in (upstream, guard):
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join(timeout=2)


@pytest.mark.local_server
def test_real_proxy_forwards_public_and_denies_private_redirect(local_guarded_proxy):
    address, observed = local_guarded_proxy
    with httpx.Client(proxy=address, trust_env=False, follow_redirects=True) as client:
        assert client.get("http://public.example/page").text == "public fixture content"
        response = client.get("http://public.example/redirect")
        assert response.status_code == 403
    assert len(observed) == 2
    assert all(destination.addresses == ("93.184.216.34",) for destination in observed)


@pytest.mark.local_server
def test_private_subresource_and_connect_are_denied_before_dial(local_guarded_proxy):
    address, observed = local_guarded_proxy
    with httpx.Client(proxy=address, trust_env=False) as client:
        assert client.get("http://10.0.0.1/internal-image").status_code == 403
        with pytest.raises(httpx.ProxyError):
            client.get("https://169.254.169.254/metadata")
        # A hostname that resolves privately must fail just like an IP literal.
        with pytest.raises(httpx.ProxyError):
            client.get("https://private.example/metadata")
        assert client.get("http://private.example/internal-image").status_code == 403
    assert observed == []
