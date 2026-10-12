"""Keep normal tests offline; allow explicit loopback integration fixtures only."""

import ipaddress
import os
import socket

import pytest


@pytest.fixture(autouse=True)
def contain_network(request, monkeypatch):
    live = request.node.get_closest_marker("live")
    if live:
        if os.environ.get("SKRILLER_LIVE_TESTS") != "1":
            pytest.skip("Live source tests require explicit opt-in and configured credentials")
        return
    local = request.node.get_closest_marker("local_server") or request.node.get_closest_marker(
        "integration_db"
    )
    original = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def allowed(address):
        if not local:
            return False
        host = address[0]
        if host in {"localhost", b"localhost"}:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def connect(sock, address):
        if sock.family != socket.AF_UNIX and not allowed(address):
            raise AssertionError("Unapproved direct socket connection in offline test")
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family != socket.AF_UNIX and not allowed(address):
            raise AssertionError("Unapproved direct socket connection in offline test")
        return original_connect_ex(sock, address)

    def resolve(host, *args, **kwargs):
        if local and host in {"localhost", "127.0.0.1", "::1", b"localhost", b"127.0.0.1"}:
            return original(host, *args, **kwargs)
        raise AssertionError(f"Unapproved network destination in offline test: {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
