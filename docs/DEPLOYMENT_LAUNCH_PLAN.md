# Deployment and launch checkpoint — 2026-10-18

## Actual backlog

96 tickets: 57 Done, 33 implemented pending verification, 2 in progress, 4 planned.
39 remain open; 28 are P0/core. These are not 39 new coding implementations. Deployment
packaging SKR-074 and model quality SKR-076 are in progress. Language/regional and
conditional retrieval/companion expansion stay outside current launch work.

## What must close before launch

The count of 39 open tickets is not a count of 39 coding tasks: 33 already have
local implementations and are waiting for their named acceptance evidence. For
the product scope chosen so far (prompt-led lead research with LinkedIn and Reddit),
all 28 P0 tickets are release gates for a paid, customer-facing launch. They cover
provider/data-use constraints, model quality and prompt interpretation, the full
research/export journey, source connections, isolated egress, backups, tenant and
budget controls, operational recovery, and a real pilot. A staging deployment can
be attempted earlier, but it is not launch-ready evidence.

The other 11 open tickets are not all launch blockers:

| Tickets | Release decision |
| --- | --- |
| SKR-082/083 YouTube owner analytics; SKR-084 X; SKR-085/086 Instagram/Facebook; SKR-088 Salesforce CRM | Defer unless these integrations are explicitly advertised in the first release. CSV export remains the initial handoff. |
| SKR-090 billing | Required before automated paid subscriptions. May defer only for an unpaid invite-only pilot; no paid checkout should be enabled before provider sandbox acceptance. |
| SKR-091 language; SKR-092 regional source | Explicitly deferred for launch by the user. |
| SKR-094 semantic retrieval; SKR-095 desktop companion | Conditional roadmap evaluations, not launch requirements. |

For a narrower staging-only deployment, the one concrete packaging ticket is
SKR-074, but its container build, host setup, TLS, backups, and isolation still
need real environment verification. Do not call staging or fixture success a
customer launch. Based on current gates, estimate 3–5 focused engineering days
after access is available for staging acceptance, then about 1–2 weeks for a
small pilot. Model quality is still pending and is a no-go gate for claims of
reliable qualified leads; there is no honest launch date until it passes.

There is no accurate fixed count of individual deployment checks until a host and
advertised operation set are selected. Group the outstanding acceptance into these
nine work packages rather than inventing a percentage-complete figure:

1. Application/container and isolated-worker builds, Linux dependencies/assets,
   non-root permissions and egress (027/036/040/074).
2. Hosted networking, domain/TLS, secrets, restricted DB roles, service readiness and
   operator rollout/rollback (074).
3. Private S3 storage plus encrypted off-host backup and restore rehearsal (018/073).
4. Hosted restart/cancellation/budget races, tenant isolation and bounded load (025/
   030/075/077/078).
5. Advertised source operation coverage, expiry/reconnection, quotas and commercial
   provider/storage rights (009/010/011/033/059–062 and optional source tickets).
6. Model semantics, labelled field accuracy and full evidenced prompt-to-qualified
   export (012/067/068/076/096). Model quality is explicitly user-pending; this remains
   unresolved, not waived. No heavier models on the base M4 Air.
7. Authenticated browser journeys: clarification, refinement, lists and downloads
   (052/057/067), respecting the saved browser restriction.
8. Payment-provider test checkout/webhooks/refund/dispute/entitlements and remote plan
   setup before accepting payments (090); optional CRM/owner analytics only if included
   in launch claims (088/082/083). Billing credentials/setup are user-deferred.
9. Repeated real tasks in three prospective workspaces, support and cost/value evidence
   (079). Successful fixture tests do not replace this.

## Intended stack

| Layer | Existing implementation / proposed deployment |
| --- | --- |
| Web | Next.js 16, React 19, TypeScript, Node 24; standalone non-root image |
| API | Python 3.12, FastAPI/Uvicorn, Pydantic; prepared non-root backend image |
| Durable work | Celery, RabbitMQ 4; separate API/research/retention processes |
| Database | PostgreSQL 18, SQLAlchemy, Alembic, tenant isolation and restricted app role |
| Evidence | Private S3-compatible storage; AWS S3 is the conservative initial target for the existing public-access/ownership checks |
| Scraping | Copied Scrapling/Agent-Reach/OpenCLI adapters, separate guarded HTTP/browser worker images and egress proxy |
| Model | Existing Ollama development integration; Groq adapter exists. Production quality/provider choice is unresolved |
| Login | Firebase Authentication and server-side token verification |
| Payments | Stripe USD and Razorpay INR, approved plan definitions; external sandbox acceptance pending |
| Metrics / CI | Existing Prometheus metrics and GitHub Actions checks; image registry/push/rollout wiring still to implement |
| Hosting proposal | Linux VPS + Docker Compose; Caddy for TLS/reverse proxy. Hetzner is a candidate, not provisioned or purchased |

Production web builds default to same-origin API requests. Route `/health/*` and
`/v1/*` to the API and all remaining paths to the Next.js web service; the
starter Caddy routing rule is `infra/deploy/Caddyfile`. Local development keeps
the explicit `NEXT_PUBLIC_API_URL=http://localhost:8000` override. The Caddy file
is only configuration groundwork and still needs validation with the final
service names, domain, and Compose deployment.

Prefer one small hosting footprint for an initial bounded pilot, with scraping
execution isolated from API/database authority. Do not mount a host Docker socket
into a public API container or treat ordinary Docker separation as complete egress
proof. Actual host sizing and browser concurrency must follow measurements; no
production-memory estimate is verified. A base M4 Air is a development machine, not
the production model/worker host.

Official references: [Compose production](https://docs.docker.com/compose/how-tos/production/),
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https),
[Hetzner server types](https://docs.hetzner.com/cloud/servers/overview/).
No cloud account, server, DNS change, purchase, registry push or deployment is authorized
by writing this proposal.

## Cost reality (checked 2026-10-18)

The application stack is not a zero-cost production service. Next.js, React,
FastAPI, PostgreSQL, RabbitMQ, Celery, Caddy, Docker Compose, Ollama and Prometheus
are available as software without a per-seat subscription under their applicable
licenses. Running them still requires paid compute, domain registration, storage,
backups, network transfer and operations. VPS charges apply while provisioned,
even when a server is stopped; a public IP may be an additional charge. S3 storage,
requests, retrieval and transfer are usage-priced. Stripe charges payment
processing fees despite no standard monthly or setup fee; Razorpay likewise has
transaction/platform fees (its current official pricing page lists 2% plus GST
for standard payment-gateway transactions, subject to its current terms). Firebase
Auth can fit within its no-cost allowance for supported providers and volume, but
phone SMS and other Firebase/Google Cloud products have separate usage charges.
GitHub Actions has plan quotas and private-repository overages can be billed.

So the software licenses may be free; hosting the proposed production stack and
collecting payments are not guaranteed free. Use an actual regional/volume quote
before choosing a host or promising a monthly operating budget. Official pricing:
[Hetzner cloud billing](https://www.hetzner.com/cloud/),
[AWS S3](https://aws.amazon.com/s3/pricing/),
[Firebase](https://firebase.google.com/pricing),
[Stripe](https://stripe.com/pricing),
[Razorpay](https://razorpay.com/pricing/),
[GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage).

## Rough effort, not a completion promise

After hosting/domain/storage access and deferred container checks are available,
budget roughly 3–5 focused engineering days for an initial staging deployment and
basic operational checks, assuming no image/dependency/network blockers. A limited
customer pilot needs roughly another 1–2 weeks for real workflows, source coverage
and recovery evidence. Full paid launch has no defensible date while model-quality,
provider rights and billing sandbox acceptance remain unresolved. These are rough
human effort/calendar estimates, not remaining model-runtime hours or guaranteed ETAs.

## Latest packaging work

Added `infra/deploy/compose.yaml` and its README for the application services:
API, research, retention, standalone web and Caddy. Explicit image/configuration/
domain/memory inputs are required; only ingress publishes ports. Production mode,
private S3 and disabled unaccepted planning/source operations are enforced in this
starter configuration. Static YAML/exposure/gate checks passed; no Compose engine,
image or hosted acceptance was executed. Private DB/broker, source isolation,
operator migrations and backup setup remain separate prerequisites. See
`docs/completions/PRIORITY-LAUNCH-LOCAL.md` for this batch's verified scope.

Added apps/api/Dockerfile: locked non-editable wheel installs from the three checked-in
source projects, separate non-root runtime and reusable process commands. Added its
operating limits/asset/readiness instructions. Excluded all local environment-file
variants from both web and root Docker contexts. No image was built or executed;
container verification remains user-deferred. Existing web production build success
is independent evidence and does not verify this new Linux backend image.
