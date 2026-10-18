# Deployment and hosting: ordered staging-to-launch guide

Prepared 18 October 2026. This guide prepares a deployment; no server, domain,
bucket, purchase, registry upload or hosted deployment has been made.

## 1. Set the release boundary before buying hosting

Local discovery works and its automated release checks pass. Full public product
release is still blocked by the following evidence, not by missing hosting alone:

| Ticket | What still prevents full completion |
| --- | --- |
| SKR-096 | Representative correct prompt interpretation and authenticated clarification/resubmission acceptance. Both local models and the Groq diagnostic baselines are below the quality gate. |
| SKR-076 | Representative 50-prompt and 200-record labelled acceptance, broader field/contact/identity quality and actual source coverage. Five synthetic checks cannot close this. |
| SKR-067 | Real-model/source/evidence/confirmed-export acceptance and the authenticated browser journey. Indexed source downloads and reviewed synthetic-fixture exports are verified separately. |
| SKR-074 | Linux image builds, Compose execution, private roles/secrets, TLS, storage, isolated collection, resource measurement, restart/recovery, backup and hosted smoke evidence. This ticket includes deployment, so it cannot be fully Done before any deployment is tested. |

An internal staging site can be deployed while these remain open, with gated
operations disabled. Do not call that a paid customer launch. Also close provider
use/storage rights (SKR-011), private object storage (SKR-018), off-host recovery
(SKR-073), security/load gates and customer pilot evidence before public release.

## 2. Choose and budget for the actual stack

- Ubuntu Linux VPS for the initial bounded pilot; Hetzner is one possible vendor.
- Docker Engine + Compose plugin; Caddy for HTTPS/reverse proxy.
- Next.js/React web; Python/FastAPI API; separate Celery research and retention.
- PostgreSQL 18 and RabbitMQ 4 on a private internal data network, or equivalent
  private managed endpoints if you choose the managed route.
- Private AWS S3 evidence storage; separate off-host database/object recovery.
- Existing Firebase Google sign-in. Keep AI planning disabled until accepted.
- Existing Prometheus metrics and GitHub Actions as needed; payment services are a
  later deployment step after their test-mode acceptance.

Software availability does not make hosting free. Budget for VPS, domain, storage,
backup, bandwidth, optional managed services/model APIs and payment fees. Start
with staging usage limits and a provider spending budget. No heavy model needs to
run on the base M4 Air. Host RAM and service memory limits must follow measured
container load; the manifests deliberately provide no invented sizing guarantees.

## 3. Save a reproducible release and obtain a test host

The current workspace has uncommitted and untracked implementation files. Review
and save the intended code as an approved release commit before cloning it onto a
server; a clone of an older remote commit will not contain this work. Exclude local
`.env`, `.runtime`, browser profiles, private exports and reference archives from
uploads/build contexts. Keep the release commit ID for rollback. No commit/push is
performed by this guide.

Create a test VPS in the chosen region, with SSH-key access and sufficient measured
capacity. Keep a separate operator account and recoverable SSH access. Install
Docker Engine and its Compose plugin using the official Ubuntu instructions:
https://docs.docker.com/engine/install/ubuntu/

On the server, verify the chosen architecture and tools:

```sh
uname -m
docker version
docker compose version
```

Subsequent server commands assume an authorised operator/root shell, an approved
checkout at `/opt/skriller`, and private configuration under `/etc/skriller`.
They are future instructions, not commands already executed here.

## 4. Configure DNS and network access

Create an A record such as `staging.your-domain.example` pointing to the VPS. Add
AAAA only if IPv6 is configured and reachable. Permit your SSH access and public
TCP 80/443; UDP 443 is optional for HTTP/3. Do not publish PostgreSQL, RabbitMQ or
management ports. Caddy must be able to obtain certificates; the chosen domain
must resolve correctly first. Retain Caddy's `/data` and `/config` volumes.

See https://caddyserver.com/docs/automatic-https for certificate/network prerequisites.
Use a cloud firewall as well as the host's network configuration where applicable.
Docker-published ports need their own verification; a firewall command by itself
is not evidence that a container service is private.

## 5. Create private storage and an independent backup destination

Create an S3 bucket for evidence in the chosen region. Keep all Block Public Access
settings enabled, bucket-owner-enforced ownership and ACLs disabled. Do not use a
public bucket or website-hosting mode. Supply a scoped workload role or restricted
server-side key pair, never browser credentials. The application verifies bucket
ownership/access at startup.

The current adapter needs bucket policy/public-access and ACL-read inspection plus
object Get/Put/Delete permissions. Confirm the exact IAM permissions against
`src/skriller/storage/__init__.py`; do not give the app account-wide administrator
permissions just to make startup pass. Test object write/read/hash/delete privately.

Official controls: https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html
and https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html

Create an independent off-host backup destination and separately protected recovery
keys. An S3 evidence bucket is not a PostgreSQL backup. **The existing local backup
CLI refuses S3 mode**: remote database/object backup coordination and a real restore
rehearsal must be completed before customer launch. Do not copy the local backup
command into production and assume it covers remote objects. Follow
`RECOVERY_RUNBOOK.md`, deletion-journal requirements and SKR-073's remaining gates.

## 6. Prepare protected configuration files

```sh
install -d -m 0700 /etc/skriller
cd /opt/skriller
```

Create the following files with an editor, mode 0600, on the server. Never commit
or paste their values into chat. Use distinct randomly generated database-owner,
application-role and broker passwords; URL-encode credentials in connection URLs.

1. `/etc/skriller/postgres.password`: database-owner password only, no variable name.
2. `/etc/skriller/rabbit.env`: `RABBITMQ_DEFAULT_PASS=<broker password>`.
3. `/etc/skriller/operator.env`: owner-only bootstrap/migration configuration:

```dotenv
SKRILLER_ENVIRONMENT=development
SKRILLER_DATABASE_URL=postgresql+psycopg://skriller:OWNER_PASSWORD@postgres:5432/skriller
SKRILLER_APPLICATION_PASSWORD=APPLICATION_ROLE_PASSWORD
```

The operator process is a one-shot private migration task, not a development-mode
public API. It creates the fixed restricted `skriller_app` role. Never give this
owner env-file to API/research/retention.

4. `/etc/skriller/runtime.env`: application-role runtime configuration:

```dotenv
SKRILLER_DATABASE_URL=postgresql+psycopg://skriller_app:APPLICATION_ROLE_PASSWORD@postgres:5432/skriller
SKRILLER_APPLICATION_DATABASE_URL=postgresql+psycopg://skriller_app:APPLICATION_ROLE_PASSWORD@postgres:5432/skriller
SKRILLER_BROKER_URL=amqp://skriller:BROKER_PASSWORD@rabbitmq:5672//
SKRILLER_FIREBASE_PROJECT_ID=YOUR_FIREBASE_PROJECT_ID
SKRILLER_CORS_ORIGINS=["https://staging.your-domain.example"]
SKRILLER_OBJECT_BACKEND=s3
SKRILLER_S3_BUCKET=YOUR_PRIVATE_BUCKET
SKRILLER_S3_REGION=YOUR_REGION
# Omit static keys when using a verified workload identity.
AWS_ACCESS_KEY_ID=SERVER_SIDE_KEY_IF_REQUIRED
AWS_SECRET_ACCESS_KEY=SERVER_SIDE_SECRET_IF_REQUIRED
SKRILLER_MODEL_PROVIDER=ollama
SKRILLER_SEARCH_PROVIDER=disabled
SKRILLER_SEARCH_COMMERCIAL_TERMS_CONFIRMED=false
```

Both DB URLs intentionally use the restricted role for the public application;
only the separate operator file has owner credentials. Production mode and disabled
unaccepted planning/source operations are enforced by the application manifest.
Search stays disabled in maintenance staging until commercial-use/storage acceptance
is actually confirmed. Do not change that flag merely to bypass the startup gate.
The disabled planner does not need a running Ollama service on this staging host.

5. `/etc/skriller/deploy.env`: non-secret orchestration values, populated after
image builds and memory measurements:

```dotenv
SKRILLER_DOMAIN=staging.your-domain.example
SKRILLER_RUNTIME_ENV_FILE=/etc/skriller/runtime.env
SKRILLER_OPERATOR_ENV_FILE=/etc/skriller/operator.env
SKRILLER_RABBIT_ENV_FILE=/etc/skriller/rabbit.env
SKRILLER_POSTGRES_PASSWORD_FILE=/etc/skriller/postgres.password
SKRILLER_API_IMAGE=REVIEWED_BACKEND_IMAGE_REFERENCE
SKRILLER_WEB_IMAGE=REVIEWED_WEB_IMAGE_REFERENCE
SKRILLER_CADDY_IMAGE=REVIEWED_CADDY_IMAGE_DIGEST
SKRILLER_POSTGRES_IMAGE=REVIEWED_POSTGRES_18_IMAGE_DIGEST
SKRILLER_RABBIT_IMAGE=REVIEWED_RABBITMQ_4_IMAGE_DIGEST
SKRILLER_API_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_RESEARCH_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_RETENTION_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_WEB_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_CADDY_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_POSTGRES_MEMORY_LIMIT=MEASURED_BUDGET
SKRILLER_RABBIT_MEMORY_LIMIT=MEASURED_BUDGET
```

Replace every placeholder. Compose memory values need valid units, not that literal
text. Sum service budgets plus host overhead before choosing limits. Do not copy
the development Compose passwords or this Mac's loopback DB URLs onto the server.

## 7. Build and inspect immutable images for the server architecture

Run from the approved release checkout on the target architecture:

```sh
docker build -f apps/api/Dockerfile -t skriller-api:staging .
```

Provide the four public Firebase web values as shell variables in the operator
session: `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`,
`NEXT_PUBLIC_FIREBASE_PROJECT_ID`, `NEXT_PUBLIC_FIREBASE_APP_ID`. These are browser
configuration, not a service-account key. Then:

```sh
docker build -f apps/web/Dockerfile -t skriller-web:staging \
  --build-arg NEXT_PUBLIC_API_URL= \
  --build-arg NEXT_PUBLIC_FIREBASE_API_KEY \
  --build-arg NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN \
  --build-arg NEXT_PUBLIC_FIREBASE_PROJECT_ID \
  --build-arg NEXT_PUBLIC_FIREBASE_APP_ID \
  apps/web
docker image inspect skriller-api:staging --format '{{.Id}}'
docker image inspect skriller-web:staging --format '{{.Id}}'
```

Save the resulting immutable local image IDs or approved registry digest references
in deploy.env. Select reviewed Caddy 2, PostgreSQL 18 and RabbitMQ 4 image digests
for the same architecture; verify their availability and manifests rather than
copying an unverified digest from a tutorial. No paid registry is required if you
build and retain images on the host, but off-host reproducibility/rollback is still
needed. These Docker builds have **not** yet been executed for this release.

## 8. Validate the combined configuration without printing secrets

For the single-host private PostgreSQL/RabbitMQ option, define this shell helper:

```sh
dc() {
  docker compose --env-file /etc/skriller/deploy.env \
    -f infra/deploy/compose.yaml \
    -f infra/deploy/compose.data.yaml "$@"
}
dc config --quiet
```

Use `--quiet`: ordinary `config` output can expand runtime secrets. Inspect image
users, memory limits, read-only filesystems and network membership before starting.
The data overlay adds no host DB/broker ports and requires separate operator config.

For private managed data services, omit the data overlay, supply the actual private
DNS/TLS URLs and run migrations separately through a reviewed operator connection.
Do not use the overlay's `postgres`/`rabbitmq` DNS names for a managed service.

## 9. Start data services, migrate, then start the application

```sh
dc up -d --wait postgres rabbitmq
dc --profile operator run --rm migrate
dc up -d api research retention web caddy
dc ps
```

Do not proceed if bootstrap/migration exits nonzero. Verify migrations reach head
and the app role is not superuser and cannot bypass row-level security. Protect
the data volumes; never use `down --volumes` as a routine restart or rollback.
The migration service is not part of normal startup and must not run automatically
with owner credentials in the public API container.

## 10. Verify HTTPS and real identity

```sh
curl --fail --silent --show-error --max-time 15 https://YOUR_STAGING_DOMAIN/health/live
curl --fail --silent --show-error --max-time 15 https://YOUR_STAGING_DOMAIN/health/ready
curl --fail --silent --show-error --max-time 20 -o /dev/null -w 'Web HTTP %{http_code}\n' https://YOUR_STAGING_DOMAIN/
```

Replace the hostname. Confirm all three readiness dependencies are true, the web
page is served over trusted HTTPS, no browser request goes to `localhost:8000`, and
unauthenticated private endpoints deny access. Confirm externally that DB/broker
ports are closed. Validate worker consumption and a bounded actual job; a consumer
count alone is insufficient end-to-end evidence.

In Firebase Authentication settings, add the staging hostname to Authorized domains.
Keep the existing Firebase auth domain unless you deliberately configure custom
Firebase auth-domain hosting/redirects. Test Google sign-in on the new domain in
the browser. See https://firebase.google.com/docs/auth/web/google-signin.

Search will intentionally remain disabled until its provider rights/operation gate
is satisfied. Once approved, enable the selected supported provider, restart API
and research together, then perform the manual prompt/source-export test from
`LOCAL_RUN_AND_MANUAL_TEST.md` on HTTPS. Do not enable AI qualification based only
on this search check.

## 11. Close source, model, recovery and load gates

Complete representative planner/extraction/qualification labels and accuracy gates
before enabling AI planning. Review real direct LinkedIn/Reddit operation, account
refresh/revoke/expiry and provider limits before advertising those direct reads.
The generic browser route is not a replacement for a denied platform route.

Provision and verify tokenizer/cleanup/browser assets and the isolated source
controller before enabling page/dynamic/platform workers. The current production
Settings explicitly reject the public collection proxy pending its deployment gate.
Removing that check is not a deployment setup step. Container separation alone
does not prove egress policy. Verify the reviewed worker/proxy/controller design.

Run a measured two-workspace job/concurrency check on the host. Restart API, worker
and broker separately during a bounded test job; confirm no duplicate result,
replayed charge, lost durable state or cross-workspace disclosure. Test cancellation,
deadline, recovery and all actual advertised source operations. Measure logs/memory
and tune the explicit limits from evidence.

Finish daily off-host database/object backup, current deletion-journal custody,
independent recovery keys and an isolated restore rehearsal. Verify the specified
24-hour RPO/4-hour RTO at pilot scale. Do not launch customer workloads with an
untested single copy of the database volume.

## 12. Test rollback before inviting the pilot

Retain the previous approved image references/configuration. To roll back application
code, replace image references with that verified release and run `dc up -d` again.
Do not run Alembic downgrade blindly: schema compatibility and data migration are
separate decisions. Take/verify the approved backup first where needed. Confirm
readiness and the bounded prompt/export flow after rollback. Do not delete volumes.

Invite the small agreed pilot only after the supported product scope's checks pass.
Record real task accuracy, review time, coverage, cost and failure/recovery evidence
before general launch. Update each ticket with that evidence; do not mark a ticket
Done merely because its containers start.

## 13. Enable paid checkout and optional integrations afterward

For a paid launch, create the approved Stripe/Razorpay **test-mode** plans, complete
sandbox checkout/webhook/entitlement/refund/dispute tests, and deploy the separate
billing worker/gateway before enabling checkout. The base application manifest
does not deploy that separate billing service. Razorpay's approved pilot term is
12 monthly cycles. Keep paid billing disabled until its live rollout is deliberately
approved. Remote keys/plan creation are still deferred.

Salesforce, X, YouTube owner analytics, Instagram/Facebook, additional languages,
regional connectors, vector search and a desktop companion can remain outside the
initial release claims. Enable each only after its own acceptance evidence.

## Deployment evidence to preserve

Record release commit, image digests/platforms, migration revision, validated service
limits, HTTPS/readiness, real identity journey, supported-source results/exports,
restart/cancel/recovery tests, private storage checks, restore timings and pilot
results. Keep secrets and private customer data out of evidence reports. Update
`TICKET_STATUS.md` through `scripts/ticket_status.py`; unresolved required gates
must remain visible.
