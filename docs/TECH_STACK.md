# Skriller: technical stack and architecture

Version: 0.2 — proposed implementation baseline  
Date: 12 October 2026  
Product contract: [PRD](PRD.md)

Delivery backlog: [Implementation tickets](IMPLEMENTATION_TICKETS.md). The user's latest direction is to copy/adapt supplied feature code rather than independently rewrite it; [source reuse map](REUSE_MAP.md) identifies exact files, tests, and necessary modifications.

This is an architectural decision document, not an implemented system. Exact package versions, upstream commit pins, hosting prices, and provider/model configuration are selected and recorded during the feasibility phase. Do not invent a compatibility lockfile before resolving dependencies and running the integrations.

## 1. Recommended stack

Use a modular monolith for business logic, with separate API, task, and browser processes. One repository and shared schemas are enough for the pilot. Avoid Kubernetes, a service mesh, a separate vector database, and multiple agent orchestration frameworks initially.

| Layer | Baseline choice | Purpose and tradeoff |
| --- | --- | --- |
| Web application | Next.js App Router, React, TypeScript | Conversational UI, results, evidence panels, connection settings; requires a Node runtime for hosted app. |
| Styling and accessible primitives | Tailwind CSS, accessible component primitives selected at implementation | Consistent UI without designing a full system first. No mandatory filter form. |
| API and business logic | Python 3.12, FastAPI, Pydantic v2 | Compatible direction for Python scraping libraries and strict typed plans/results. Python 3.12 satisfies current ScrapeGraph-AI metadata. |
| Python dependency management | uv with checked-in lockfile | Reproducible environments; optional isolated connector/extractor environments if conflicts arise. |
| JavaScript package management | pnpm with checked-in lockfile | Reproducible UI dependencies; pin supported Node LTS and package manager when implementation begins. |
| Durable relational storage | PostgreSQL 18, SQLAlchemy 2, Alembic | Plans, jobs, entities, evidence metadata, costs, tenant control, migrations. Use PostgreSQL in local Compose too. |
| Background task dispatch | Celery with RabbitMQ | Mature Python worker/broker path. PostgreSQL is the canonical job-state store; Celery results are not the product database. |
| Periodic dispatch | One scheduler process using Celery Beat and database-backed due records | P0 cleanup/recovery; P1 scheduled monitoring. Prevent duplicate scheduler work through leases/idempotency. |
| Fast fetch/parser | Scrapling HTTP and selector interfaces | Reuse deterministic fetching, parsing, adaptive element logic. Avoid adding duplicate clients without a reason. |
| Browser fetching | Scrapling dynamic/stealth interfaces; Playwright-compatible automation where supported | Render JS, handle documented challenges, perform supported read-only interactions. Isolated browser processes. |
| Platform tooling | Product-owned adapters around selected Agent-Reach channels/upstream tools | Reuse useful routing and tooling with explicit capabilities, not an unrestricted install-and-run agent. |
| AI extraction | ScrapeGraph-AI adapter plus product-owned deterministic extraction | Use library where it meets evidence/budget contracts; product owns validation and routing. |
| LLM transport | Small typed provider abstraction; Gemini cloud candidate; Ollama local mode | Evaluate actual schema fidelity/cost; configure model explicitly. Groq/other providers are optional later, not required dependencies. |
| Web discovery | Brave Search API initial candidate; replaceable provider contract | Clear programmatic search interface. Verify operator behaviour, storage rights, and suitability for LinkedIn/Reddit discovery. |
| App authentication | Firebase Authentication Google sign-in; server verification with Admin SDK | App identity only. Workspace authorisation and source connections stay in the application. |
| Evidence blobs and exports | Local filesystem in development; private S3-compatible object storage in hosting | Metadata in PostgreSQL; minimal permitted evidence bodies/excerpts; signed, expiring exports. |
| Live progress | Authenticated HTTP streaming using server-sent event format | Persist event sequence; reconnect with cursor. Avoid adding a message-stream service initially. |
| Observability | Structured redacted logs, OpenTelemetry, basic metrics dashboard | Job/stage/source timing, resource use, cost, errors; traces must not capture credentials/full pages. |
| Packaging/deployment | Containers and Docker Compose-compatible configuration, reverse proxy/TLS | Repeatable local and single-host pilot; runtime/licensing choice is environment-specific. |
| Verification | pytest, Ruff, type checks, Vitest, Playwright UI tests | Test contracts, correctness/security, failure recovery, and actual user flow. |

PostgreSQL is chosen over an initial SQLite production path to avoid rewriting multi-user storage and job coordination later. A minimal offline experiment may use fixtures/files, but that is not the hosted architecture.

RabbitMQ adds a service, but removes the need to invent a durable queue. No Redis/Valkey dependency is needed initially; small-pilot rate-limit/circuit-breaker state can be coordinated in PostgreSQL. Reconsider a dedicated shared limiter only after measured database contention.

## 2. Reuse strategy for the three projects

### Scrapling

Copy the supplied Scrapling package and supporting metadata/licences/tests into a local attributed `third_party/scrapling` tree and install it as a locked local dependency. Reuse/adapt existing HTTP, dynamic/stealth, parsing, and adaptive code; do not recreate those algorithms. Product wrappers add evidence, source rules, attempt accounting, deadlines, semantic checks, and typed errors. Benchmark before enabling aggressive concurrency. A successful HTTP response is not automatically a valid source page.

Do not run a second uncontrolled crawl loop alongside our job dispatcher. An upstream crawler can be used only if its retries, scheduling, and pause/resume semantics are mapped to our budgets and checkpoints.

### Agent-Reach

Copy the supplied Agent-Reach source into a local attributed `third_party/agent-reach` tree and preserve its supporting metadata/licences/tests. Inspect and adapt the channel registry, diagnostics, and selected platform backends. Its current design delegates many reading operations to external upstream tools, so copying Agent-Reach does not itself supply one uniform extraction API or all backend code. Acquire/pin missing implementations in the corresponding feasibility tickets.

Wrap useful CLI/MCP backends in product adapters. Pin those tools independently. Execute only enumerated read operations, never arbitrary model-chosen shell commands. Require explicit network and credential scope, bounded output, subprocess termination, and structured parsing. Prefer direct library/API integration where the upstream interface is stable.

A third-party intermediary such as a page-reader service is an external provider: content disclosure, terms, quotas, retention, and cost need recording. It is not a free local execution path merely because an upstream wrapper calls it.

### ScrapeGraph-AI

Copy the supplied ScrapeGraph-AI source and supporting metadata/licences/tests into `third_party/scrapegraph-ai`, then install the local copy in a pinned compatible environment. Adapt the existing graph/node/model/parser logic for bounded collected-content extraction instead of rewriting it. Disable external telemetry and unnecessary home writes, redact local-content logs, preserve evidence during cleanup, and bound internal calls/refetches. If an interface requires changes, patch the copied implementation with regressions and provenance.

The OSS package and the vendor's hosted API are separate choices; no hosted vendor subscription is required by this architecture. Schema validation, factual grounding, qualification, and identity resolution remain product-owned.

### Forking and vendoring rules

Keep the supplied `reference/` trees unchanged for inspection/comparison. Runtime source copies live under `third_party/`, separate from product business logic. Record upstream URL, snapshot content hashes, verified commit only when actually known, licence/notices, modifications, tests, and update process. The supplied ZIP-derived snapshots have no verified commit identity. Include third-party licence notices in distributions and review transitive tools/model licences. New code is appropriate for missing product glue, not independently replacing supplied feature implementations.

No automatic dependency upgrades inside customer jobs. A controlled upgrade must pass lockfile resolution, relevant connector/extractor contract tests, DOM fixtures, and security checks. Use a separate container/venv if dependency constraints genuinely conflict; do not remove required pins simply to make the installer succeed.

## 3. Logical execution architecture

```text
Browser UI → FastAPI → plan revision + job + budget in PostgreSQL
                         ↓ transactional outbox
                     RabbitMQ → Celery task workers
                                  ↓
                  source capability router + discovery provider
                                  ↓
                 API/feed/HTTP/browser/platform-tool adapters
                                  ↓
                  deterministic/adaptive/AI extraction
                                  ↓
                evidence + claims + entity resolution + qualification
                                  ↓
                   PostgreSQL + private object storage
                                  ↓
                 persisted events → streamed UI + exports
```

An adapter is selected by source and operation before the generic fallback path. A known API/feed can skip browser fetching. A generic page may use HTTP → rendered browser → configured stealth strategy. Upstream stealth engines already incorporate browser tooling; do not retry the same underlying engine under different labels.

The planner chooses only registered typed operations. It cannot invent new tools, access arbitrary secrets, change source capabilities, raise budgets, or execute downloaded instructions. No heavy agent framework is needed for a bounded workflow. Reconsider LangGraph/another framework only when a concrete requirement is not met by the explicit state machine.

## 4. Internal contracts

Contracts must be Python/Pydantic types and versioned JSON schemas exposed through OpenAPI. Frontend types are generated rather than separately handwritten.

```text
SearchPlan:
  workspace_id, conversation_id, revision, entity_type
  must_have[], preferences[], exclusions[], requested_fields[]
  source_preferences[], freshness_policy, limits, currency_cap

ConnectorCapability:
  source, operation, engineering_status, operational_status
  access_route, allowed_fields, auth_kind, constraints, version

Connector:
  capabilities(context) → capability list
  health(context) → status and actionable reason
  discover(query, context) → candidates and cursor
  read(candidate, context) → collected content or typed failure

ExecutionContext:
  workspace_id, job_id, plan_revision, connection_ref
  deadline, attempt_budget, cost_reservation, cancellation_token

ExtractedField:
  name, typed_value, evidence_ids[], observed_or_inferred
  extraction_method, field_status, schema_version

ResearchClaim:
  statement, evidence_ids[], observed_or_inferred, freshness_status
```

`Connector` operations are optional based on capability flags; an unsupported operation returns an explicit typed outcome. Output cursors are provider-scoped. `ExecutionContext` contains secret references, not credentials in queued messages or prompt text.

Standard failures: `auth_required`, `auth_expired`, `access_denied`, `challenge_detected`, `rate_limited`, `quota_exhausted`, `not_found`, `unsupported_operation`, `source_unavailable`, `schema_invalid`, `evidence_missing`, `ambiguous_match`, `deadline_exceeded`, `budget_exhausted`, `cancelled`.

## 5. Reliable jobs and distributed coordination

Create plan/job/outbox records in one database transaction. A dispatcher publishes outbox tasks to RabbitMQ. Publication may occur more than once; workers must tolerate duplicates. Database task claims, attempt records, unique constraints, and leases make writes idempotent. Do not claim exactly-once network calls or provider billing.

Use short stage tasks, not one worker task that performs a 20-minute uncontrolled crawl. A source-read stage can do bounded async I/O, but Celery concurrency, batch concurrency, browser capacity, source limits, and total host resources must have coordinated caps.

Cancellation and budget state are checked before every provider call and after bounded stages. Timeout handling closes browser contexts/subprocesses and releases capacity. Source rate-limit state is shared across workers and hosts; process-local semaphores alone are insufficient. PostgreSQL-backed leases/reservations enforce pilot-wide host/source/workspace limits. Include an expiry/recovery mechanism for abandoned capacity leases.

A transaction reserves conservative maximum cost for a bounded call. After response or timeout, reconcile known usage. Keep uncertain provider charges as estimated entries. Model calls can make hidden internal retries; configure or wrap them so the parent budget remains enforceable. A duplicate logical task must not duplicate a result, but an interrupted external request may still be billed.

Persist monotonically ordered job events. The frontend reads snapshots plus events and can reconnect from its last sequence. Use streaming `fetch` with an authorisation header or secure same-origin session; do not put Firebase tokens in URLs. Expired app tokens reconnect through the normal authentication flow.

## 6. Fetching, adaptive recovery, and caching

Normalise candidate URLs conservatively: preserve meaningful path/query identifiers, remove known tracking parameters, and record original/final URL. Validate destinations and redirects. Classify status plus page content; challenge pages sometimes return HTTP 200.

Prefer embedded structured data and source-native identifiers. Use deterministic selectors for known templates. Adaptive matching must pass semantic checks. LLM repair returns a candidate mapping/evidence, not arbitrary executable code. Promote a repaired template only after fixture validation or explicit operator review; support rollback.

Cache keys include tenant, source/access context, source operation, extraction/schema version, and normalised input. Shared public caches are permitted only after isolation and usage-right requirements are satisfied; default to tenant-scoped caching. Never reuse an authenticated/private page for another workspace. Conditional requests and content hashes reduce repeated work where supported.

Initial freshness policy: search snippets expire after 24 hours; claims about current role, hiring, or active demand need evidence collected within 7 days unless the prompt asks for a stricter interval; relatively stable company descriptions may use 30 days. These are product defaults, not proof of source currency. Source publication time and actual observation are tracked separately. A fresh fetch of an old post does not make the post recent.

## 7. Search and AI provider decisions

### Search

The user cannot activate a paid search plan. The development provider is therefore **Exa keyless MCP**, selected after actual company, LinkedIn and Reddit reference probes. Use the official MCP Python SDK with a fixed search-only endpoint, no credentials, bounded requests and no automatic paid fallback. Agent-Reach already references Exa; its channel supplies setup diagnostics, while the real operation now uses the hosted provider. [Official Exa authentication/tools documentation](https://exa.ai/docs/get-started/exa-mcp).

Keyless access is free but rate-limited; it is a prototype route, not a promise of unlimited production search. Current tool input supports query/objective/result count and no pagination. Domain filtering is enforced on returned reference URLs; exact Google-style operators and exclusion semantics are not advertised as provider guarantees. Query, original rank, URL, snippet and observation time remain metadata, with snippets explicitly labelled as search evidence rather than fetched-page facts.

Brave remains an optional explicit feasibility probe if the user later chooses it. No Brave key or activation is required for the chosen local prototype. Production quality, data storage/use and capacity decisions retain their release gates.

### AI

Use one cloud provider/model for the initial hosted evaluation and an Ollama option for local use. Gemini is the candidate, with paid-tier data handling and rate limits checked for the intended workload. Select the exact model from schema/evidence benchmarks rather than popularity. Do not silently fall back to a provider with different data terms.

The provider contract supports structured JSON, explicit token limits, timeout, usage accounting, redacted tracing, and typed failures. Keep planning, extraction, and report generation as separate prompts; all reference bounded inputs. Extract only relevant segments after preserving useful structured data. A valid JSON response is still checked against evidence.

Local inference uses available hardware and the chosen model's commercial licence. It is not zero compute cost and has separate latency/quality measurements. No model training or fine-tuning is required in P0. Free cloud quotas may support experiments; they do not determine hosted capacity. Google's pricing page lists different free/paid data-use treatment. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Ollama API](https://docs.ollama.com/api/introduction)

## 8. Platform implementation policy

Implement LinkedIn and Reddit capability probes first. Identify the exact discovery/read routes and their operation-level restrictions. A user session, upstream marketing claim, or successful single read is not evidence of stable commercial capacity. Record tested coverage, account/session requirements, limits, rights, and failure rate before advertising an operation.

YouTube public discovery and owner analytics are separate adapters. The public adapter uses suitable Data API/metadata/transcript routes; analytics uses owner OAuth and report scopes. Do not call public counters “YouTube analytics” without qualification.

GitHub/RSS use their suitable APIs/feed parsers. X/Instagram/Facebook and regional sources get the same contract and independent feasibility gates. Each can have multiple backends, but a route change cannot silently alter data meaning, credentials, cost, or data disclosure.

Source authentication is not implemented through Firebase app login. Provider OAuth tokens and approved browser session contexts are separate connections. Session-based integrations use a dedicated isolated browser context with encryption, rotation/reconnect, revocation, and no shared account pool. P0 does not include a browser extension or local desktop companion; add one only through a recorded decision if the validated source route requires it.

## 9. Security and tenancy implementation

Map the verified Firebase identity to workspace memberships in PostgreSQL. Verify tokens server-side; neither client claims nor workspace IDs supplied in URLs grant access. Use membership checks plus PostgreSQL row-level security as defence in depth. Set transaction-scoped tenant context with a non-owner application role; test connection-pool reuse and privileged maintenance paths explicitly.

Secrets use envelope encryption and separate key access. Do not store raw credentials in task payloads, model context, job events, URLs, or logs. Workers load only the connection needed for the task. Keep browser/tool execution isolated from DB administration and unrelated provider keys.

Control egress at both application and network layers. Validate URL schemes, DNS resolution, redirects, ports, decoded payload sizes, and browser subresource destinations. Reject internal network/metadata targets and revalidate after redirects. Network-layer controls prevent a connector from bypassing Python URL checks. Browser downloads and executable content are disabled for P0.

Use TLS, secure cookies where applicable, explicit CORS/CSRF handling, parameterised SQL, bounded request bodies, and workspace request/usage limits. Private object keys require tenant authorisation before signed links are issued. Cloud buckets are private by default. CSV exports escape formula-leading content without corrupting the raw JSON representation.

## 10. Deployment and resource budget

Local development: web, API, PostgreSQL, RabbitMQ, worker, and scheduler through Compose-compatible configuration; object storage via local volume; optional Ollama outside the baseline services. Developers can use recorded fixtures to avoid live source spend.

Hosted pilot: one API/web host and a bounded worker host, or one small host initially if measured capacity permits; persistent database/broker volumes, private object storage, TLS, and off-host encrypted backups. A 4-vCPU/8-GiB worker host is the PRD benchmark assumption, not a proven production sizing requirement. Browser memory and local-model memory must be measured; do not inherit optimistic per-tab RAM figures from the brainstorm.

The web/API service can respond while browsers are saturated. Start with two browser pages per worker host; CPU and memory limits plus a watchdog recycle leaking browser processes. Host-wide browser capacity is shared across job workers. Containers/workers restart without losing canonical state. Do not place long-lived browsers in short-timeout serverless request functions.

Scale when queue wait, memory pressure, or source limits justify it: split browser workers, increase supported HTTP capacity, and move database/broker to resilient managed instances. More hosts do not override per-source limits. High availability is a later measured architecture decision; a single-host pilot cannot honestly promise it.

## 11. API outline and repository layout

Suggested endpoints, all workspace-authorised:

| Endpoint | Behaviour |
| --- | --- |
| `POST /v1/conversations` | Create conversation. |
| `POST /v1/conversations/{id}/messages` | Add prompt/refinement; create plan or clarification. |
| `GET /v1/plans/{id}` | Return versioned interpretation and limits. |
| `POST /v1/plans/{id}/runs` | Idempotently dispatch a validated plan within entitlement/budget. |
| `GET /v1/jobs/{id}` | State, stage, counts, errors, actual/estimated usage. |
| `GET /v1/jobs/{id}/events` | Authorised event stream with sequence cursor. |
| `POST /v1/jobs/{id}/cancel` | Persist cancellation request. |
| `POST /v1/jobs/{id}/resume` | Recheck connection/budget and resume checkpoints. |
| `GET /v1/jobs/{id}/results` | Cursor-paginated results, match groups, and evidence status. |
| `GET /v1/entities/{id}` | Claims, sources, conflicts, freshness, link history. |
| `POST /v1/exports` | Generate versioned, scope-checked CSV/JSON/JSONL. |
| `GET /v1/connectors` | Capability-level readiness and connection requirements. |
| `POST /v1/connections/{source}/connect` | Begin appropriate source connection flow. |
| `DELETE /v1/connections/{id}` | Disconnect/revoke and stop queued reuse. |
| `GET /v1/workspaces/{id}/usage` | Limits, ledger, and remaining budget. |

Chat submission can internally call the run dispatcher after plan validation; the user does not have to manually press a second “run” button for every unambiguous request.

```text
apps/web/                    # conversational UI
services/api/                # FastAPI, auth, orchestration endpoints
services/worker/             # stage tasks, recovery, scheduling
packages/core/               # plans, claims, qualification, cost rules
packages/connectors/         # capability registry and platform wrappers
packages/fetching/           # Scrapling/browser integration
packages/extraction/         # deterministic/adaptive/ScrapeGraph implementations
packages/providers/          # search, models, optional proxy transports
packages/contracts/          # schema source and generated client types
migrations/                  # Alembic
tests/fixtures/              # labelled static/JS/changed/adversarial examples
tests/contracts/             # connectors/providers
tests/integration/           # database, queue, tenancy, recovery
tests/e2e/                   # prompt-to-export UI
infra/                       # local/hosted configuration
docs/                        # requirements, decisions, runbooks
reference/                   # supplied original snapshots; comparison only
third_party/                 # attributed source copies and adapted upstream tests
```

Python package directories share a workspace lock where compatible. The layout is a starting boundary, not a requirement to create empty packages before a complete working slice.

## 12. Verification and implementation sequence

1. Resolve Python 3.12 compatibility and pin Scrapling/ScrapeGraph/browser dependencies; identify Agent-Reach tools used. Record licences and upstream commits.
2. Test LinkedIn and Reddit operation-level routes, search provider coverage/operators/rights, and one model's schema/evidence quality. Record unsuccessful probes too.
3. Build one real prompt → typed plan → discovery → company/source read → evidence → qualification → streamed result → export slice.
4. Add selected launch-platform adapters, dynamic/stealth fetching, adaptive repair, identity tests, and conversational research.
5. Implement/verify tenant isolation, external-tool egress, ledger reservations, duplicate delivery, worker recovery, expiry/reconnection, deletion, and backup restore before a hosted customer pilot.
6. Measure PRD quality/latency/cost gates under the declared profile. Publish source limitations and operator runbooks. Add P1 only after P0 gates.

Use unit tests for semantic qualification/identity/cost logic, contract tests for external interfaces, and integration tests for transaction/queue/session behaviour. Browser fixtures verify DOM changes and malicious content. Live source probes run at low volume outside routine CI and record configuration/cost. Mocked success is not a source-access validation.

## 13. Architecture decisions and alternatives

| ID | Decision | Alternative and reason to defer |
| --- | --- | --- |
| A-01 | Next.js + FastAPI | Streamlit is useful for experiments but would not be the baseline conversational hosted UI. |
| A-02 | PostgreSQL locally and hosted | SQLite is simpler locally but complicates shared state/tenancy migration. |
| A-03 | Celery + RabbitMQ with DB state/outbox | Custom DB queue avoids a broker but increases correctness work; Temporal adds initial operational complexity. |
| A-04 | Explicit typed stages | Unrestricted autonomous agent loops make spend, safety, and replay harder to control. |
| A-05 | Scrapling as fetching foundation | Separate HTTP/stealth stacks duplicate work unless a measured source need justifies them. |
| A-06 | Selected Agent-Reach reuse | Running the entire setup/orchestration flow per user gives excessive tool/configuration scope. |
| A-07 | ScrapeGraph behind extractor contract | Making its graph the entire product would couple job/evidence/tenant logic to one library. |
| A-08 | PostgreSQL full-text/indexed queries first | Separate vector search is unnecessary until relevance benchmarks require it. |
| A-09 | One evaluated cloud model plus Ollama option | Multiple default providers increase quality/data-term variability. |
| A-10 | Local fixtures, hosted bounded pilot | Desktop app/extension and large managed SaaS are separate delivery choices, deferred. |

## 14. Technical reference sources

Checked on 12 October 2026; proposals above are our decisions, not endorsements or performance guarantees from these projects.

- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/).
- [Celery supported brokers](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html).
- [SQLAlchemy 2 documentation](https://docs.sqlalchemy.org/en/20/) and [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
- [Firebase server token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).
- [Scrapling](https://github.com/D4Vinci/Scrapling) and [stealth fetching](https://scrapling.readthedocs.io/en/latest/fetching/stealthy.html).
- [Agent-Reach upstream](https://github.com/Panniantong/Agent-Reach).
- [ScrapeGraph-AI](https://github.com/ScrapeGraphAI/Scrapegraph-ai) and [Python requirement metadata](https://raw.githubusercontent.com/ScrapeGraphAI/Scrapegraph-ai/main/pyproject.toml).
- [LinkedIn Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api), [LinkedIn agreement](https://www.linkedin.com/legal/user-agreement), and [Reddit Data API Terms](https://redditinc.com/policies/data-api-terms).
- [YouTube public search](https://developers.google.com/youtube/v3/docs/search/list) and [owner analytics reports](https://developers.google.com/youtube/analytics/reference/reports/query).
- [Brave API pricing](https://brave.com/search/api/) and [query options](https://api-dashboard.search.brave.com/app/documentation/web-search/query).
- [Gemini pricing/data-use distinction](https://ai.google.dev/gemini-api/docs/pricing) and [Ollama API](https://docs.ollama.com/api/introduction).

