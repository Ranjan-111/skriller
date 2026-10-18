# Pilot application deployment preparation

`compose.yaml` defines the API, research worker, retention process, standalone web
and Caddy ingress. It is application packaging, not a verified running deployment.
Docker execution and hosted acceptance remain user-deferred under SKR-074.

For the optional single-host route, combine this with `compose.data.yaml`, which
adds private PostgreSQL/RabbitMQ volumes, internal data networking and an explicit
operator-only bootstrap/migration service. Neither data service publishes host
ports. Its first real image/Compose/startup/role test is still pending. The complete
ordered procedure is in `docs/DEPLOYMENT_HOSTING_GUIDE.md`; do not infer deployment
acceptance from these static definitions.

Before starting it, provide private PostgreSQL/RabbitMQ endpoints, a private S3
bucket, Firebase configuration and a domain. Supply the application DB role only
to these processes. Run bootstrap/migrations separately with operator credentials;
do not use the root development Compose file or its development passwords for a
public deployment. No database/broker/management ports are published here.

Set these non-secret interpolation values in a protected operator shell:

- `SKRILLER_API_IMAGE`, `SKRILLER_WEB_IMAGE`, `SKRILLER_CADDY_IMAGE`: reviewed image
  references pinned to the target architecture's approved immutable digest.
- `SKRILLER_RUNTIME_ENV_FILE`: absolute path to a mode-0600 runtime environment
  file outside the checkout containing application-role DB/broker URLs, Firebase
  project ID and private S3 configuration/credentials. Do not commit or print it.
- `SKRILLER_DOMAIN`: DNS hostname resolving to the deployment host.
- `SKRILLER_API_MEMORY_LIMIT`, `SKRILLER_RESEARCH_MEMORY_LIMIT`,
  `SKRILLER_RETENTION_MEMORY_LIMIT`, `SKRILLER_WEB_MEMORY_LIMIT`, and
  `SKRILLER_CADDY_MEMORY_LIMIT`: measured per-service memory budgets in Compose
  units, sized to fit the host. No unmeasured production defaults are supplied.

Build the web image with the public Firebase web configuration as build arguments;
keep `NEXT_PUBLIC_API_URL` empty for same-origin routing. Public Firebase web
configuration is distinct from server credentials. Runtime env-file changes cannot
replace public values already compiled into browser assets.

The manifest enforces production mode, disables demo auth, and keeps AI planning
and direct source/extraction workers disabled until their quality/isolation gates
pass. S3 is required. Production Settings still reject an unconfirmed Exa provider;
use `SKRILLER_SEARCH_PROVIDER=disabled` for maintenance/staging if commercial-use
acceptance is outstanding. This does not create a working customer research pilot.
Enable supported operations only after the corresponding source/provider acceptance.

Only Caddy publishes host ports. The web service has no outbound network. Backend
processes need outbound connections to configured DB/broker, Firebase and storage;
the outbound network is **not** a firewall or proof of source-worker egress
isolation. No Docker socket, platform session, browser or model is mounted. Source
execution controllers and optional encryption-key/asset mounts require a separate
reviewed configuration before those operations can be enabled.

At the future deployment check, use `docker compose -f infra/deploy/compose.yaml
config --quiet` to validate interpolation without displaying runtime secrets.
Build/run images, validate Caddy, run operator migrations, and test TLS, readiness,
worker heartbeat, persistent state, cancellation/restart, backup restore, resource
limits and rollback on the actual host. API liveness alone is insufficient; the
image's API health check is deliberately disabled on non-HTTP workers.

No cloud resources or registry pushes are created by these files. YAML parsing and
source review do not establish Linux dependency closure or deployment acceptance.
