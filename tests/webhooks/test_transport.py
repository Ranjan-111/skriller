"""No outbound calls: pinned destination, HTTPS-only and no redirect behavior."""

from types import SimpleNamespace

import pytest

from skriller.security.urls import Destination, EgressDenied
from skriller.webhooks import transport


@pytest.mark.parametrize(
    "url",
    [
        "http://receiver.example/hook",
        "https://receiver.example/hook?secret=abc",
        "https://receiver.example/#fragment",
        "https://user:password@receiver.example/hook",
    ],
)
def test_endpoint_denies_insecure_or_credential_bearing_url(url):
    with pytest.raises(EgressDenied):
        transport.validate_endpoint(url)


def test_redirect_to_internal_address_is_not_followed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        transport,
        "resolve_public_destination",
        lambda url: Destination(url, "receiver.example", 443, ("93.184.216.34",)),
    )

    class Receiver:
        def __init__(self, destination):
            calls.append(destination)

        def request(self, method, path, **kwargs):
            assert method == "POST" and path == "/hook"
            assert kwargs["headers"]["Connection"] == "close"

        def getresponse(self):
            return SimpleNamespace(status=302, headers={"Location": "http://127.0.0.1/private"})

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(transport, "PinnedHTTPS", Receiver)
    assert transport.post("https://receiver.example/hook", b"{}", {}) == 302
    assert len(calls) == 2 and calls[-1] == "closed"


def test_tls_uses_pinned_socket_and_original_sni(monkeypatch):
    destination = Destination(
        "https://receiver.example/hook", "receiver.example", 443, ("93.184.216.34",)
    )
    raw = object()
    monkeypatch.setattr(
        transport,
        "connect_pinned",
        lambda actual, timeout: raw if actual is destination else pytest.fail("unpinned"),
    )
    connection = transport.PinnedHTTPS(destination)

    class Context:
        def wrap_socket(self, sock, server_hostname):
            assert sock is raw and server_hostname == "receiver.example"
            return "verified-socket"

    connection.tls_context = Context()
    connection.connect()
    assert connection.sock == "verified-socket"


def test_delivery_process_has_fixed_deadline_and_only_ids_in_payload(monkeypatch):
    from uuid import uuid4

    from skriller.webhooks import runtime

    task = {name: str(uuid4()) for name in ("delivery_id", "endpoint_id", "lease_token")}

    def child(argv, **kwargs):
        assert argv[1:3] == ["-m", "skriller.webhooks.runtime"]
        assert kwargs["timeout"] == 20 and kwargs["max_output"] == 4096
        assert "--delivery-id" in argv and "--lease-token" in argv
        return SimpleNamespace(status="timeout", returncode=None, stdout="", stderr="SECRET")

    monkeypatch.setattr(runtime, "bounded_process", child)
    assert runtime.run_delivery_child("fixture-owner", str(uuid4()), task) == "uncertain"
