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

Docker now runs the reviewed guarded proxy/browser containers. An isolated official PostgreSQL 18.4 runtime was built in `.runtime/postgres` and is running on loopback port 54439. It was used for the real database checks; RabbitMQ is also running natively and has passed real delivery/restart checks; full hosted collection packaging and release gates remain open. Build provenance and cluster start/stop commands are in `.runtime/postgres/NATIVE_RUNTIME.md`.

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

After PostgreSQL/RabbitMQ are running, use one foreground terminal:

```sh
.venv/bin/python scripts/dev_stack.py
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
