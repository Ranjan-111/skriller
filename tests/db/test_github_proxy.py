"""Real HTTPS client through task gateway; fixture-only provider/origin sockets."""

import json
import socket
import ssl
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
import sqlalchemy as sa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from github_fixtures import repo_payload
from test_github_collection import PROXY, prepare

from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connections.tables import proxy_routes
from skriller.connectors import proxies
from skriller.db import JobRepository, ResearchRepository
from skriller.db.schema import reservations
from skriller.jobs.budget import current_usage
from skriller.research.collection import execute_collection
from skriller.security.urls import Destination
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db


@pytest.fixture
def tls_origin(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.github.com")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.github.com")]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "fixture.pem", tmp_path / "fixture.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            body = json.dumps(repo_payload()).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address, requests, ssl.create_default_context(cafile=str(cert_path))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("provider_fails,rate", [(False, "0"), (True, "0"), (False, "4")])
def test_github_uses_configured_task_provider_without_origin_credentials_or_fallback(
    database, monkeypatch, tmp_path, tls_origin, provider_fails, rate, caplog
):
    _, task, entity_id = prepare(database, monkeypatch)
    store = ConnectionStore(Keyring("v1", {"v1": AESGCM.generate_key(bit_length=256)}))
    raw = json.dumps(
        {
            "providers": [
                {
                    "server": "http://one.example",
                    "username": "private-user",
                    "password": "private-secret",
                }
            ],
            "usd_per_gb": rate,
            "max_attempts": 1,
            "max_bytes": 65536,
        }
    )
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        credential = store.create(
            session,
            "proxy",
            "api_key",
            SecretPayload(credentials={"api_key": raw}),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    monkeypatch.setattr(ConnectionStore, "configured", classmethod(lambda cls, settings: store))
    from skriller.security import proxy as gateway

    monkeypatch.setattr(
        gateway,
        "resolve_public_destination",
        lambda url: Destination(url, "api.github.com", 443, ("93.184.216.35",)),
    )
    endpoint, requests, verification = tls_origin
    used = []

    def tunnel(provider, destination, **_kwargs):
        used.append((provider.server, destination.hostname, destination.port))
        if provider_fails:
            raise proxies.ProxyUnavailable("private-secret")
        return socket.create_connection(endpoint)

    monkeypatch.setattr(proxies.Provider, "tunnel", tunnel)
    original_client = httpx.AsyncClient

    def client(**kwargs):
        # Fixture trust only: real hostname and TLS certificate verification stay on.
        kwargs["verify"] = verification
        assert kwargs["trust_env"] is False
        assert kwargs["proxy"].startswith("http://task:")
        return original_client(**kwargs)

    monkeypatch.setattr("skriller.connectors.github.httpx.AsyncClient", client)
    storage = EvidenceStorage(LocalBlobBackend(tmp_path / "blobs"))
    result = execute_collection(database, task, PROXY, storage=storage)
    assert result["status"] == "checkpointed"
    if rate != "0":
        # Prompt jobs have a zero-dollar cap. A priced route must never dial,
        # retry elsewhere or silently raise that persisted limit.
        assert not used and not requests
        with database.tenant(task["actor_id"], task["workspace_id"]) as session:
            entity = ResearchRepository.get_entity(session, entity_id)
            assert entity["attributes"]["collection"]["status"] == "unavailable"
            assert current_usage(session, task["job_id"])[0] == 0
            assert (
                session.execute(
                    sa.select(reservations.c.id).where(
                        reservations.c.job_id == task["job_id"],
                        reservations.c.idempotency_key.startswith("proxy:"),
                    )
                ).first()
                is None
            )
            assert not ResearchRepository.claims_for(session, entity_id)
        return
    assert used == [("http://one.example", "api.github.com", 443)]
    assert len(requests) == (0 if provider_fails else 1)
    if requests:
        assert requests[0][0] == "/repos/acme/demo"
        assert not any(
            key.lower() in {"authorization", "proxy-authorization"} for key in requests[0][1]
        )
    with database.tenant(task["actor_id"], task["workspace_id"]) as session:
        entity = ResearchRepository.get_entity(session, entity_id)
        summary = entity["attributes"]["collection"]
        assert summary["status"] == ("unavailable" if provider_fails else "read")
        assert current_usage(session, task["job_id"])[1]["fetch_attempts"] == 1
        route = (
            session.execute(sa.select(proxy_routes).where(proxy_routes.c.job_id == task["job_id"]))
            .mappings()
            .one()
        )
        assert route["connection_id"] == str(credential.id) and route["attempts"] == 1
        assert route["failed"] is provider_fails
        charged = (
            session.execute(
                sa.select(reservations).where(
                    reservations.c.job_id == task["job_id"],
                    reservations.c.idempotency_key.startswith("proxy:"),
                )
            )
            .mappings()
            .one()
        )
        assert charged["state"] == "committed"
        assert charged["reconciliation_status"] == ("estimated" if provider_fails else "confirmed")
        assert (charged["amount_usd"] if provider_fails else charged["actual_cost_usd"]) == 0
        if not provider_fails:
            assert route["traffic_bytes"] > 0
            assert len(ResearchRepository.claims_for(session, entity_id)) == 3
        else:
            assert not ResearchRepository.claims_for(session, entity_id)
        events = json.dumps(JobRepository.events_after(session, task["job_id"]), default=str)
        assert "private-secret" not in events and "private-user" not in events
    assert "private-secret" not in caplog.text
