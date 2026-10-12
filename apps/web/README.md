# Skriller web

Prompt-first research workspace scaffold. Requires Node 22+ and pnpm.

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open http://localhost:3000. Configure `NEXT_PUBLIC_API_URL` (default
`http://localhost:8000`) in `.env.local`; restart Next after changing it.

```sh
pnpm test
pnpm typecheck
pnpm build
```

The app probes `/health/live` and `/health/ready`. Research uses
`POST /v1/conversations`, followed by
`POST /v1/conversations/{id}/messages`. The typed API client accepts a token
provider for Firebase Bearer authentication; sign-in UI belongs to a later ticket.
No demo credentials or fabricated leads are supplied. Unavailable job endpoints,
authentication failures and offline services produce explicit recoverable states.

Job status and result retrieval helpers follow `/v1/jobs/{id}` and
`/v1/jobs/{id}/results`; their rendering belongs to later tickets.

API types are generated from the actual backend OpenAPI document. From the
repository root after a backend contract change:

```sh
uv run python scripts/export_contracts.py --output apps/web/contracts/openapi.json
```

Then from `apps/web`:

```sh
pnpm contracts:generate
pnpm contracts:check
pnpm typecheck
```

Commit both `contracts/openapi.json` and `src/generated/api.ts`. Backend CI checks
that the exported JSON matches the actual API; frontend CI checks that generated
types match that JSON. Contract tests deliberately mutate a schema and require
the drift check to fail. Compile-time checks reject unsupported source names,
operations, failure codes and missing plan identity.

The generator workspace pins `openapi-typescript` 7.10.1 and TypeScript 5.9.3,
whose compiler AST API it needs. The application retains TypeScript 7.0.2;
generator dependencies are isolated rather than downgrading application checks.
`SearchPlan`, `Capability`, `ExecutionContext`, `Failure` and `Source` exported
from the client alias generated components. Composer request and accepted-job
state are local UI state; conversation/message transports still await their
actual backend endpoint implementation.

The client also exposes actual workspace-scoped `snapshot(identity)` and
`progressEvents(identity, options)` transports. Their identity, snapshot and
progress payload types derive from the generated API. Streams use fetch so
Firebase Bearer credentials and `Last-Event-ID` travel in headers, never query
parameters. Supply an `AbortSignal` to stop a connection. The decoder handles
chunk fragmentation/heartbeats, preserves large sequence IDs as decimal strings,
bounds frames and releases readers on exit. Automatic reconnect and progress UI
remain later frontend work.
