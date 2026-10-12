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

Both attempted Docker image builds failed in Docker Desktop's storage layer:
`/var/lib/docker/buildkit/containerd-overlayfs/metadata_v2.db: input/output error`.
No existing images/volumes/containers were deleted or restarted. Consequently,
kernel firewall behaviour and container filesystem isolation are **not yet
operationally verified** on this host; SKR-027/028 remain partial until that gate
and browser-worker integration pass. Restoring Docker storage is an external
prerequisite, not a reason to disable the security boundary.
