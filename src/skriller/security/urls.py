"""Extend copied Agent-Reach validation with DNS and port enforcement."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from agent_reach.utils.url import normalize_public_http_url


class EgressDenied(ValueError):
    """A requested destination is outside the public HTTP(S) boundary."""


@dataclass(frozen=True)
class Destination:
    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def resolve_public_destination(url: str) -> Destination:
    """Reject mixed/private DNS answers and return IPs to dial directly.

    This is not a browser sandbox: the enforcing proxy must dial these IPs,
    and workers must have no alternative outbound network route.
    """
    try:
        normalized = normalize_public_http_url(url)
        parsed = urlsplit(normalized)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port != (443 if parsed.scheme == "https" else 80):
            raise EgressDenied("Only standard public HTTP(S) ports are permitted")
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        resolved: list[str] = []
        for answer in answers:
            address = answer[4][0]
            # TCP internet answers must contain textual numeric addresses. Do
            # not coerce other sockaddr variants into a destination hostname.
            if not isinstance(address, str):
                raise EgressDenied("Invalid destination address")
            resolved.append(address)
        addresses = tuple(dict.fromkeys(resolved))
        if not addresses:
            raise EgressDenied("No destination addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            mapped = isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None
            if not ip.is_global or ip.is_multicast or ip.is_reserved or mapped:
                raise EgressDenied("Non-public destination address")
        return Destination(normalized, hostname, port, addresses)
    except (ValueError, OSError, UnicodeError) as exc:
        raise EgressDenied("Destination denied by public egress policy") from exc


def connect_pinned(destination: Destination, timeout: float = 10) -> socket.socket:
    """Use numeric resolved addresses; never resolve the hostname a second time."""
    failure = None
    for address in destination.addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((address, destination.port))
            return sock
        except OSError as exc:
            sock.close()
            failure = exc
    raise OSError("Vetted destination could not be reached") from failure
