# Guarded outbound worker boundary

The proxy validates every outbound HTTP request and HTTPS CONNECT authority,
rejects non-public or mixed DNS answers, and connects directly to a vetted IP.
Browser redirects and subresources pass through the same boundary. Ports are
limited to HTTP 80 and HTTPS 443. There is no production private-IP exception.

Build/start the proxy with `docker compose -f infra/egress/compose.yaml up -d --build`.
It exposes no host port. `skriller_egress_workers` is an internal network containing
the proxy at 172.29.0.2. Browser/backend workers must join **only** this network.

Extend `Dockerfile.worker-base` with the frozen application environment and
browser assets needed by a particular read backend. Publish that image and supply
its immutable digest to `IsolatedRunner`. The base image alone is an isolation
fixture, not a working installed yt-dlp/browser product image.

Each worker starts `guarded-worker.sh` with NET_ADMIN, SETUID, SETGID and SETPCAP
only long enough to install deny-by-default IPv4/IPv6 firewall rules and drop all
capabilities. It then executes as an unprivileged UID with no-new-privileges.
The only permitted outbound connection is TCP to 172.29.0.2:8080; direct private
or public sockets, DNS, UDP, WebRTC and QUIC are denied regardless of proxy env.
Host home and credential directories are never mounted. The root filesystem is
read-only; only the task workspace and bounded temporary storage are writable.

Browser automation must use pipe transport; worker loopback TCP debugging and
WebSocket traffic are denied by design. Application database/message-broker
access belongs to the orchestration service outside this fetch worker. Residential
upstream proxy chaining and credentials are not implemented by this proxy.

Ordinary URL validation alone is insufficient. Do not execute browser fetching
on the orchestration host and assume setting HTTP_PROXY provides isolation.
Public proxy access must remain restricted to the internal worker network.

## Verification status

Real host loopback HTTP proxy tests verify public forwarding, metadata redirect
denial, internal subresource denial and private CONNECT denial. Unit tests verify
DNS rebinding prevention and private/mixed/mapped-IP rejection.

Docker Desktop recovered on 2026-10-13 without deleting or resetting any
existing images, containers or volumes. The pinned Python 3.12 production-base
metadata request remained stalled, so the actual isolation gate was run with a
separate digest-pinned Python 3.13 fixture. The product requires Python 3.12:
this fixture does not prove the product runtime is installed or compatible.

The fixture uses the same proxy code, guarded entrypoint, Docker restrictions
and internal network. Reproduce it with:

```sh
docker build --build-arg BASE_IMAGE=python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 -f infra/egress/Dockerfile.worker-base -t skriller-egress-worker-test .
docker compose -f infra/egress/compose.yaml -f infra/egress/fixture.compose.yaml up -d --build
SKRILLER_EGRESS_CONTAINER_TESTS=1 .venv/bin/pytest -q tests/security/test_egress.py tests/security/test_runner.py tests/security/test_container_boundary.py
```

The actual container gate verifies unprivileged execution, zero effective and
child-inherited capabilities, host file/environment/Docker-socket exclusion,
read-only root filesystem, direct public/private/metadata/loopback TCP denial,
UDP denial and proxy denial of metadata HTTP/HTTPS CONNECT. Test workers are
removed by their own unique names in `finally`. No host port is exposed.
The proxy fixture can be stopped with the same two compose files and `down`
(no volume deletion). It is not an installed browser or source reader.

Production digest-pinned platform/browser images, their integration with this
network, and real application-level extraction remain required release gates.

## Python 3.12 verification update

The Dockerfile defaults now pin the official Python 3.12 Bookworm index (`sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`). Both the project proxy and worker base built and executed successfully on native arm64. The real kernel and cancellation gates passed with Python 3.12.15; the earlier 3.13 fixture is historical evidence. Set `SKRILLER_EGRESS_TEST_IMAGE` to the trusted immutable local image ID when testing another administrator-built image. Base-runtime verification does not by itself prove an installed browser or platform adapter.
