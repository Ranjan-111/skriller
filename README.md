# Skriller

Prompt-first lead discovery and evidence-backed research. Implementation is in progress. Authenticated prompts now execute durable free-search jobs and show real, unverified source snippets with local JSON/CSV downloads. It does not yet claim complete LinkedIn/Reddit access or production readiness.

## Local setup

Use Python 3.12, uv, Node >=22.12, pnpm 12.6, and Docker. Source engines are attributed local copies under `third_party/`; `reference/` remains unchanged.

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked
docker compose up -d --wait postgres rabbitmq
```

Provision the restricted app role and schema using the explicit owner connection:

```sh
.venv/bin/python -c 'from skriller.db.core import bootstrap; from skriller.settings import Settings; bootstrap(Settings().database_url, application_password="local-development")'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn skriller.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal:

```sh
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

The app runs at localhost:3000, API at localhost:8000. Compose exposes development services on loopback only; credentials shown above are local defaults and are rejected in production mode. Configure real Firebase identity and provider connections in ignored `.env` when available. App login and target-source access are different integrations.

Existing local Ollama models can be trialled through the copied ScrapeGraph-AI engine:

```sh
.venv/bin/python scripts/probes/model_trial.py --model llama3.2:3b --include-structured-data
```

Live trial reports explicitly distinguish small synthetic-fixture checks from broader quality benchmarks.

Local Ollama remains the default structured-model provider (`SKRILLER_MODEL_PROVIDER=ollama`).
Choose either installed local model with `SKRILLER_OLLAMA_MODEL=llama3.2:3b` or
`SKRILLER_OLLAMA_MODEL=deepseek-r1:8b`; the former remains the default.
Optional Groq uses the official OpenAI-compatible client with bounded calls, no automatic
retries, and the same job budget accounting. Configure a replacement private key only in
the ignored root `.env`:

```dotenv
SKRILLER_MODEL_PROVIDER=groq
GROQ_API_KEY=your_new_private_key
SKRILLER_GROQ_FREE_TIER_CONFIRMED=true
```

The confirmation is an operator assertion about the account; it does not verify billing
through Groq's API. No paid account setup is performed. Restart the worker after changing
provider configuration. Current search jobs do not require any model key; saved extraction
and detached planning select the configured model, while production qualification remains
in progress. Gemini is not used by the default or Groq path.

## Verification

```sh
.venv/bin/python -m pytest -m 'not live and not integration_db'
.venv/bin/python -m pytest -m integration_db
python3 docs/validate_delivery_plan.py
python3 scripts/provenance.py verify scrapling
python3 scripts/provenance.py verify agent-reach
python3 scripts/provenance.py verify scrapegraph-ai
```

Ordinary tests deny external networking. Live source probes require explicit opt-in plus configured credentials. Backend/web CI definitions are included; remote CI results are not assumed.

See [PRD](docs/PRD.md), [tickets](docs/IMPLEMENTATION_TICKETS.md), [reuse map](docs/REUSE_MAP.md), and individual reports in `docs/completions/` for actual verification and limitations.

## Current native PostgreSQL test alternative

This workspace currently uses native PostgreSQL and RabbitMQ; container execution remains deferred. An isolated official PostgreSQL 18.4 runtime was built in `.runtime/postgres` and is running on loopback port 54439. It was used for the real database checks; RabbitMQ is also running natively and has passed real delivery/restart checks; full hosted collection packaging and release gates remain open. Build provenance and cluster start/stop commands are in `.runtime/postgres/NATIVE_RUNTIME.md`.

To run the database suite against this cluster:

```sh
SKRILLER_DATABASE_URL=postgresql+psycopg://skriller:local-development@127.0.0.1:54439/skriller SKRILLER_APPLICATION_DATABASE_URL=postgresql+psycopg://skriller_app:local-development@127.0.0.1:54439/skriller .venv/bin/python -m pytest -m integration_db
```

[Ticket execution status](docs/TICKET_STATUS.md) records verified completion separately from implemented work awaiting acceptance checks.

## Current running development stack

This workspace's ignored `.env` now points to the isolated native PostgreSQL54439 and RabbitMQ56739 services. Firebase browser configuration is in ignored `apps/web/.env.local`; server ID-token verification uses public signing certificates and needs no service-account JSON. The user has confirmed Google sign-in and authenticated source results. No additional Firebase setup is currently needed.

```sh
.venv/bin/python scripts/native_rabbitmq.py status
.venv/bin/uvicorn skriller.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal, run `pnpm dev` from `apps/web`. The current local app is available at http://localhost:3000 and real API readiness is at http://localhost:8000/health/ready. Use `scripts/native_rabbitmq.py start` or `stop` to control only the isolated project broker; it uses the installed Homebrew RabbitMQ, not a global startup service.

The development search provider is `SKRILLER_SEARCH_PROVIDER=exa_keyless`: no key or paid plan. Set it to `disabled` to turn it off. An opt-in live probe uses three bounded public queries:

```sh
.venv/bin/python scripts/probes/exa.py --live
```

Actual probes found company, LinkedIn and Reddit references. Free-tier limits, unsupported pagination and unverified formal dork semantics remain explicit; indexed references are not qualified leads or verified platform reads. Semantic planning, qualification and the complete accepted-lead workflow remain incomplete. The prompt-to-snippet discovery path works; optional public-page collection and source-specific extraction now run through durable checkpoints. Brave is optional and has no automatic fallback path.

## Start the complete local application

For the current passing indexed-discovery/manual source-export profile, use
`.venv/bin/python scripts/dev_stack.py --discovery-only`. It overrides experimental
planning/extraction/direct source reads in child processes without editing `.env`.
Full native PostgreSQL/RabbitMQ startup, health and browser test commands are in
[local run and manual test](docs/LOCAL_RUN_AND_MANUAL_TEST.md). The ordered future
[deployment/hosting guide](docs/DEPLOYMENT_HOSTING_GUIDE.md) separates staging from
the still-open semantic, source, recovery and hosted acceptance gates.

After PostgreSQL/RabbitMQ are running, use one foreground terminal:

```sh
.venv/bin/python scripts/dev_stack.py --discovery-only
```

This starts the API, durable research worker and web app together. Keep that terminal open. Existing processes on ports3000/8000 are left running, and Ctrl-C stops only the children started by this command. Separate worker command: `.venv/bin/python -m skriller.research.runtime`. macOS uses the local solo pool to avoid multiprocessing spawn incompatibility; Linux defaults to prefork. Application I/O deadlines remain bounded in both modes. Production process/container isolation is still a separate acceptance gate.

A live CLI/RabbitMQ/free-Exa probe returned two real references in10.695seconds; the user separately confirmed results through Firebase-authenticated UI. Evidence: `docs/completions/WORKFLOW-LIVE.json`. This is a discovery check, not a claim of verified lead qualification.

## Optional local page observations

Set `SKRILLER_PUBLIC_COLLECTION_PROXY_URL=http://127.0.0.1:18080` and `SKRILLER_ENABLE_PAGE_EXTRACTION=true` in the ignored root `.env`, then restart the local stack. `scripts/dev_stack.py` also starts that loopback GuardedProxy and stops only its own children. Keep `SKRILLER_ENABLE_AI_PLANNING=false` for this route. Ollama remains the default; no paid key is required.

Each public web candidate gets one durable collection attempt. It persists private original bytes and metadata, then prepares bounded context with the copied cleanup and graph adapters. The local directory extractor uses at most two chunks per page and ten model calls per job. Unsupported or invented drafts are rejected; retained observations include source quotes and remain unverified. A real Llama 3.2 synthetic fixture produced one supported company-name observation with one call and 1,141 tokens in 9.487 seconds; five drafts were rejected. This is not a release-quality benchmark.

JS-only pages can additionally use `SKRILLER_ENABLE_DYNAMIC_COLLECTION=true` with `SKRILLER_PUBLIC_BROWSER_IMAGE` set to a reviewed, tested immutable image ID. The existing guarded Docker network/proxy must be running. The copied browser runs in a fresh container, waits for meaningful content and has no host-browser fallback. Challenge/login pages do not trigger this route. LinkedIn, Reddit and other platform references keep their dedicated read-adapter gates; they are not collected through the generic web adapter. Production collection stays disabled pending isolated collection packaging and its hosted gates.

## Workspace allowance

The authenticated workspace panel reports trial/pilot run admissions. Owners can pause execution and lower result/source limits; settings do not reset usage. The default trial allows 25 run admissions, up to 25 results and three sources per run. Retries/replays reuse their admission. Queue dispatch and provider boundaries enforce the allowance; expired work does not consume a new slot.

A project operator may provision a finite manual pilot allowance using `scripts/provision_pilot.py --workspace <uuid> --runs <1-1000> --results <1-100> --sources <1-9> --invoice-reference <reference>`. It uses the operator database configuration, performs no payment/provider request, and preserves existing admissions. The application role cannot provision itself or refund usage.

## Evidence retention

The local stack includes `python -m skriller.retention_runtime`. It maintains one hourly cleanup schedule per registered workspace, with scoped leases, safe retries and a bounded child process. Default retention ceilings are seven days for social/feed sources, thirty days for web/GitHub/public YouTube, and one hour for export artifacts. Shorter requested expiries are preserved. Expired source quotes are hidden from current result views; expired private objects/excerpts are removed without touching retained data in another tenant.

### Offline copied cleanup image

The cleanup dependency image packages the copied ScrapeGraph HTML/markdown/chunk helpers and required tokenizer asset; it is separate from the complete hosted API/model-worker deployment. On the reviewed aarch64 local runtime:

```sh
uv run python scripts/provision_cleanup_assets.py --download
# Later builds can verify staged wheels without --download.
docker build --build-context cleanup_wheels=.runtime/cleanup-build -f infra/egress/Dockerfile.cleanup -t skriller-egress-cleanup .
# Set this to the installed immutable image ID reported by docker image inspect.
SKRILLER_CLEANUP_TEST_IMAGE=sha256:ef73de989393c311d729546b0d3cb3177f1753614cde683f6236cdbeea7c31d5 uv run pytest -q tests/extraction/test_cleanup_container.py
```

Eight wheel artifacts are checked against uv.lock before staging and during the image build. The tokenizer data has a pinned SHA-256 checksum. Runtime boot tests disable all container networking and verify unprivileged/read-only execution, copied cleanup output, preserved JSON-LD and typed failure when assets are unavailable. Build-time public dependency retrieval needs no API key. See [encrypted recovery runbook](docs/RECOVERY_RUNBOOK.md) for the separate database/object backup utility and its outstanding off-host deployment gates.

Native workers also require the pinned tokenizer asset. Run `uv run python scripts/provision_tokenizer.py --download` once during local setup; later `uv run python scripts/provision_tokenizer.py` verifies it without a download. The persistent default is `.runtime/tiktoken-cache`, which survives a restart. `TIKTOKEN_CACHE_DIR` can select an operator-managed cache instead. Missing or tampered assets fail closed before the copied tokenizer runs; research execution does not download tokenizer data.

Public static-page cache replay can be enabled locally with SKRILLER_PUBLIC_RESPONSE_CACHE_TTL_SECONDS=300 (default0, maximum300). It is tenant-scoped, preserves original collection times and avoids a fetch charge while fresh. Redirects, dynamic browser pages and account-backed sources are excluded. Expired content is fetched normally; HTTP304 renewal is still pending. Owner identity review is available through /v1/workspaces/{workspace_id}/identity-reviews and its approve/reverse actions; approval still requires corroborated facts and cannot force a same-name merge.


Reviewed adaptive mappings are optional server configuration through `SKRILLER_REVIEWED_PAGE_TEMPLATES_FILE`. The bounded registry schema lives in `src/skriller/research/adaptive_templates.py`; `tests/db/test_adaptive_pipeline.py` demonstrates a workspace and exact-URL registration. Runtime only reuses reviewed fingerprints and retains unverified observations; publication remains a separate review operation. Native identity facts use the product representation `kind:opaque_id` (for example `person:known-id`) in platform-specific claim fields. Trusted source adapters/reviewers must establish that object kind; URLs and handles are not identity proof.


The results acceptance harness uses a fresh Chromium profile and a synthetic tenant API, with all page requests confined to loopback. Run `uv run pytest -q tests/db/test_results_browser.py` after installing the locked Python and web dependencies. It uses installed macOS Chrome in an isolated profile, or Playwright Chromium elsewhere; `SKRILLER_TEST_CHROME_EXECUTABLE` can select a test browser. CI installs Chromium explicitly. It does not use your Firebase browser session, source cookies, cloud models or API keys. Saved-list values now preserve original claim/source-entity IDs so reviewed identity reversals remain traceable in immutable snapshots.

## Private object backend

Local evidence remains the default (`SKRILLER_OBJECT_BACKEND=local`). The API, collection/extraction workers and retention all use the same configured backend. To select S3-compatible storage, set `SKRILLER_OBJECT_BACKEND=s3`, `SKRILLER_S3_BUCKET`, optional `SKRILLER_S3_REGION` and HTTPS `SKRILLER_S3_ENDPOINT_URL`. Use a configured workload role or a complete `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` pair (and optional `AWS_SESSION_TOKEN`) in ignored configuration. Startup refuses unverified public-access blocking, unknown bucket ownership or ACL grants to other accounts. SDK calls have bounded connect/read timeouts and no automatic retries. Live bucket policy/provider compatibility remain a deployment verification gate.

Switching the backend does not copy objects. Migrate immutable bytes under their existing workspace keys before switching; references and SHA256 checks remain stable. Local backup/rehearsal refuses a remote backend until remote object recovery is implemented and verified.

Owners can publish reviewed adaptive mappings through `POST /v1/workspaces/{workspace_id}/page-templates` with a `template` matching `ReviewedTemplate` and the current `expected_version` (null for the first version). `GET` lists active mappings; `POST /{template_id}/rollback` selects an earlier immutable version using `target_version` and `expected_version`. PostgreSQL enforces tenant isolation and append-only version/audit history. Active database mappings supersede the matching legacy file template; ambiguous fields or changed source identity are rejected. Publication supplies selectors and expected literal relationships, not source evidence or identity acceptance. Runtime still validates the current saved page, quotes, retention and semantic anchors before retaining an unverified source observation.
