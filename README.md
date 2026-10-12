# Skriller

Prompt-first lead discovery and evidence-backed research. Implementation is in progress; the UI currently supports service checks and typed submission while the research job pipeline is being connected. It does not yet claim complete LinkedIn/Reddit access or production readiness.

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

Docker currently cannot start its daemon on this machine. An isolated official PostgreSQL 18.4 runtime was built in `.runtime/postgres` and is running on loopback port 54439. It was used for the real database checks; RabbitMQ/container checks still require Docker recovery. Build provenance and cluster start/stop commands are in `.runtime/postgres/NATIVE_RUNTIME.md`.

To run the database suite against this cluster:

```sh
SKRILLER_DATABASE_URL=postgresql+psycopg://skriller:local-development@127.0.0.1:54439/skriller SKRILLER_APPLICATION_DATABASE_URL=postgresql+psycopg://skriller_app:local-development@127.0.0.1:54439/skriller .venv/bin/python -m pytest -m integration_db
```

[Ticket execution status](docs/TICKET_STATUS.md) records verified completion separately from implemented work awaiting acceptance checks.
