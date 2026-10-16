"""Public HTTPS POST with pinned DNS, verified TLS, and no redirects/proxies."""

import http.client
import ssl
from urllib.parse import urlsplit

from skriller.security.urls import EgressDenied, connect_pinned, resolve_public_destination


def validate_endpoint(url: str):
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise EgressDenied("Invalid webhook endpoint")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        raise EgressDenied("Webhook requires HTTPS without query or fragment")
    return resolve_public_destination(url)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, destination):
        self.tls_context = ssl.create_default_context()
        super().__init__(destination.hostname, 443, timeout=5, context=self.tls_context)
        self.destination = destination

    def connect(self):
        raw = connect_pinned(self.destination, timeout=5)
        try:
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.destination.hostname)
        except BaseException:
            raw.close()
            raise


def post(url: str, body: bytes, headers: dict[str, str]) -> int:
    if not body or len(body) > 4096:
        raise ValueError("Bounded webhook metadata required")
    destination = validate_endpoint(url)  # repeat DNS checks immediately before every send
    connection = PinnedHTTPS(destination)
    try:
        path = urlsplit(destination.url).path or "/"
        connection.request("POST", path, body=body, headers={**headers, "Connection": "close"})
        response = connection.getresponse()
        # Never follow Location, read a response body, or log response headers.
        return response.status
    finally:
        connection.close()
