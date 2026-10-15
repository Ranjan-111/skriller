"""Keep normal tests offline; allow explicit loopback integration fixtures only."""

import ipaddress
import os
import socket

import pytest
from alembic import command
from alembic.config import Config

from skriller.db import Database, bootstrap
from skriller.settings import Settings

# A developer may enable live collection in .env. Ordinary fixtures must not
# inherit those opt-ins, including modules that instantiate Settings at import.
# Explicit Settings keyword arguments and live-test flags remain available.
for test_option, test_value in {
    "SKRILLER_PUBLIC_COLLECTION_PROXY_URL": "",
    "SKRILLER_PUBLIC_BROWSER_IMAGE": "",
    "SKRILLER_PUBLIC_YOUTUBE_IMAGE": "",
    "SKRILLER_ENABLE_PAGE_EXTRACTION": "false",
    "SKRILLER_REVIEWED_PAGE_TEMPLATES_FILE": "",
    "SKRILLER_ENABLE_DYNAMIC_COLLECTION": "false",
    "SKRILLER_ENABLE_STEALTH_COLLECTION": "false",
    "SKRILLER_ENABLE_AI_PLANNING": "false",
    "SKRILLER_PUBLIC_RESPONSE_CACHE_TTL_SECONDS": "0",
    "SKRILLER_MODEL_PROVIDER": "ollama",
    "SKRILLER_OBJECT_BACKEND": "local",
}.items():
    os.environ[test_option] = test_value


@pytest.fixture(scope="session")
def database():
    """One application-role DB fixture across API, worker and imported helpers."""
    settings = Settings()
    bootstrap(settings.database_url, application_password="local-development")
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    db = Database(settings.application_database_url, pool_size=1)
    yield db
    db.dispose()


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
