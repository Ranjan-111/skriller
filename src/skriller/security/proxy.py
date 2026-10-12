"""Bounded forward proxy: every HTTP request/CONNECT uses vetted numeric IPs."""

from __future__ import annotations

import select
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .urls import EgressDenied, connect_pinned, resolve_public_destination


class GuardedProxy(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(
        self,
        address=("127.0.0.1", 8080),
        *,
        max_connections=32,
        max_bytes=10 * 1024 * 1024,
        max_seconds=60,
    ):
        self.slots = threading.BoundedSemaphore(max_connections)
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        super().__init__(address, ProxyHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *_args):
        # URLs, query strings, headers and browser credentials are never logged.
        pass

    def _relay(self, upstream):
        deadline = time.monotonic() + self.server.max_seconds
        transferred = 0
        sockets = [self.connection, upstream]
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                sockets, [], [], min(1, max(0, deadline - time.monotonic()))
            )
            for current in ready:
                data = current.recv(min(65536, self.server.max_bytes - transferred + 1))
                if not data:
                    return
                transferred += len(data)
                if transferred > self.server.max_bytes:
                    return
                other = upstream if current is self.connection else self.connection
                other.sendall(data)

    def do_CONNECT(self):
        try:
            parsed = urlsplit("https://" + self.path)
            if parsed.path or parsed.query or parsed.fragment or parsed.port != 443:
                raise EgressDenied("Invalid CONNECT authority")
            destination = resolve_public_destination("https://" + self.path)
            with connect_pinned(destination) as upstream:
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.wfile.flush()
                self._relay(upstream)
        except (ValueError, OSError):
            self.send_error(403, "Public egress denied")
        finally:
            self.close_connection = True

    def _http(self):
        try:
            destination = resolve_public_destination(self.path)
            parsed = urlsplit(destination.url)
            if parsed.scheme != "http":
                raise EgressDenied("HTTPS requires CONNECT")
            if self.headers.get("Transfer-Encoding"):
                raise EgressDenied("Chunked request bodies are not permitted")
            body_size = int(self.headers.get("Content-Length", "0"))
            if body_size < 0 or body_size > 1024 * 1024:
                raise EgressDenied("Request body exceeds budget")
            body = self.rfile.read(body_size)
            if len(body) != body_size:
                raise EgressDenied("Incomplete request body")
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            drop = {
                "host",
                "connection",
                "proxy-connection",
                "proxy-authorization",
                "keep-alive",
                "te",
                "trailer",
                "upgrade",
            }
            drop.update(
                value.strip().lower() for value in self.headers.get("Connection", "").split(",")
            )
            host = (
                f"[{destination.hostname}]" if ":" in destination.hostname else destination.hostname
            )
            headers = [f"{self.command} {target} HTTP/1.1", f"Host: {host}", "Connection: close"]
            for name, value in self.headers.items():
                if name.lower() not in drop:
                    if "\r" in value or "\n" in value:
                        raise EgressDenied("Malformed header")
                    headers.append(f"{name}: {value}")
            request = ("\r\n".join(headers) + "\r\n\r\n").encode("latin-1") + body
            with connect_pinned(destination) as upstream:
                upstream.sendall(request)
                self._relay(upstream)
        except (ValueError, OSError, UnicodeError):
            self.send_error(403, "Public egress denied")
        finally:
            self.close_connection = True

    do_GET = _http
    do_HEAD = _http
    do_POST = _http
    do_OPTIONS = _http
