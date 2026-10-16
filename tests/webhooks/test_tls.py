"""Actual loopback TLS socket through the production pinned HTTPS client."""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from skriller.security.urls import Destination
from skriller.webhooks import transport

pytestmark = pytest.mark.local_server


def test_real_tls_post_checks_certificate_for_original_hostname(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "receiver.example")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=10))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("receiver.example")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.rfile.read(int(self.headers["Content-Length"])),
                    self.headers["Host"],
                )
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda: original(cafile=str(cert_path)))
    destination = Destination(
        "https://receiver.example/hook", "receiver.example", 443, ("93.184.216.34",)
    )
    monkeypatch.setattr(transport, "resolve_public_destination", lambda _: destination)

    def connect(actual, timeout):
        assert actual is destination
        return socket.create_connection(server.server_address, timeout=timeout)

    monkeypatch.setattr(transport, "connect_pinned", connect)
    try:
        assert (
            transport.post(
                destination.url, b'{"event_id":"fixture"}', {"Content-Type": "application/json"}
            )
            == 204
        )
        assert received == [("/hook", b'{"event_id":"fixture"}', "receiver.example")]
        # The same trusted certificate does not authorize a different hostname.
        other = Destination("https://other.example/hook", "other.example", 443, ("93.184.216.34",))
        monkeypatch.setattr(transport, "resolve_public_destination", lambda _: other)
        monkeypatch.setattr(
            transport,
            "connect_pinned",
            lambda actual, timeout: socket.create_connection(
                server.server_address, timeout=timeout
            ),
        )
        with pytest.raises(ssl.SSLCertVerificationError):
            transport.post(other.url, b"{}", {})
        assert len(received) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
