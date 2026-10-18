# Run locally and perform the manual prompt-to-export check

Checked 18 October 2026 on this Mac. Project location:
`/Users/priyanshuranjankumar/Desktop/untitled folder/scraler`.

The current automated local release check passes. This is the indexed-discovery
profile: prompt -> durable worker job -> source results -> source CSV/JSON.
Confirmed-lead export has separate evidence/quality requirements and must not be
claimed from successful source downloads.

## 1. Open a terminal in the project

```sh
cd '/Users/priyanshuranjankumar/Desktop/untitled folder/scraler'
```

Dependencies and Firebase configuration are already installed here. Do not
overwrite `.env` or `apps/web/.env.local` with the example files.

If the app is already open and `/health/ready` returns ready, go to step 5.
The launcher intentionally refuses to take over occupied ports. Stop the previous
launcher with Ctrl-C in its own terminal before starting another one.

## 2. Ensure the existing project PostgreSQL cluster is running

```sh
if ! .runtime/postgres/bin/pg_ctl -D "$PWD/.runtime/postgres-data" status >/dev/null 2>&1; then
  .runtime/postgres/bin/pg_ctl \
    -D "$PWD/.runtime/postgres-data" \
    -l "$PWD/.runtime/postgres/server.log" \
    -o "-h 127.0.0.1 -p 54439 -k '$PWD/.runtime/postgres/socket' -c max_connections=30 -c shared_buffers=32MB" \
    -t 20 -w start
fi
.runtime/postgres/bin/pg_isready -h 127.0.0.1 -p 54439
```

Expected: `accepting connections`. This starts the existing isolated cluster;
do not run initdb or delete `.runtime/postgres-data`.

## 3. Ensure the existing project RabbitMQ is running and check migrations

```sh
if ! .venv/bin/python scripts/native_rabbitmq.py status; then
  .venv/bin/python scripts/native_rabbitmq.py start
fi
.venv/bin/python scripts/native_rabbitmq.py status
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

RabbitMQ uses port 56739; this PostgreSQL cluster uses 54439. The development
Docker Compose alternative uses different ports; do not mix the two configurations.
The existing restricted app role is provisioned. The current migration head is 0056.
If the broker is still starting, wait briefly and repeat its status command.

## 4. Start API, worker, retention and frontend together

```sh
.venv/bin/python scripts/dev_stack.py --discovery-only
```

Keep this terminal open. Ctrl-C stops its API, research worker, retention process
and Next.js child processes. PostgreSQL/RabbitMQ stay available for the next start.
This command uses the installed Node/Next tool directly; no global pnpm upgrade
is required just to run the app.

The explicit profile overrides experimental AI planning, page/dynamic extraction
and direct platform execution in child processes. It does not edit your `.env`,
use a model key or remove LinkedIn/Reddit indexed search options. Running without
`--discovery-only` restores the existing experimental configuration, which is not
the passing manual acceptance profile.

## 5. Check health in another terminal

```sh
cd '/Users/priyanshuranjankumar/Desktop/untitled folder/scraler'
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health/live
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health/ready
curl --fail --silent --show-error --max-time 20 -o /dev/null -w 'Frontend HTTP %{http_code}\n' http://127.0.0.1:3000/
```

Expected: API status `ok`; readiness status `ready` with database/broker/worker
all true; frontend HTTP 200. API liveness alone does not prove worker availability.

## 6. Run the browser prompt-to-source-export test

1. Open http://localhost:3000 and refresh the page after a restart.
2. Sign in with Google using the account you already tested.
3. Start a new research request. Select Research assistant if desired.
4. Open the sources selector and keep Web selected for the first check. Set
   Results to 10, the smallest current UI option.
5. Enter `OpenAI company official website` and click **Start research**.
6. Wait for completed or clearly labelled partial results. Check that returned
   titles/URLs appear and the UI does not claim indexed snippets are verified leads.
7. Click **Download sources as CSV**, then **Download sources as JSON**.
8. Open both files. Confirm their URLs/titles match the displayed sources and the
   JSON/CSV preserve the unverified/source-reference status.
9. Optionally repeat with LinkedIn and/or Reddit selected. These are indexed
   references in this profile, not a test of direct account-backed reads.

Pass criteria: your real Firebase login can submit a prompt, the running worker
finishes it, results appear, and both source files download with matching content.
No Brave, Gemini, Groq or payment API key is needed for this test. Search-provider
availability/rate limits still apply.

**Download confirmed CSV/JSON** is a different feature: it requires records with
accepted evidence and current confirmed qualification. Zero confirmed records is
an expected result for unverified indexed snippets. Do not mark leads confirmed
just to make that download available. The automated copied-extraction -> explicit
owner-review -> confirmed private-export test passes; real model/source/browser
acceptance of that full route is still open.

## 7. Record your manual result

Record: date, Google login success, prompt, selected sources, completion/partial
status, result count, CSV success and JSON success. Record any visible error text.
Do not include tokens, cookies, private keys or downloaded personal data in a report.
This human result is still needed; automated fixtures do not use your Google session.

If readiness is unavailable, inspect the launcher terminal and repeat the broker
and PostgreSQL status commands. If planning pauses unexpectedly, confirm the
launcher was started with `--discovery-only`. If ports are occupied, reuse the
running app or stop its owning launcher; do not kill arbitrary listeners.

## 8. Stop services when finished

Ctrl-C in the launcher terminal stops the app processes. Only if you also want
to stop the isolated local data services:

```sh
.venv/bin/python scripts/native_rabbitmq.py stop
.runtime/postgres/bin/pg_ctl -D "$PWD/.runtime/postgres-data" -m fast -t 20 -w stop
```

The saved evidence is in `completions/LOCAL-RELEASE-READINESS.json`,
`completions/LOCAL-RELEASE-WORKFLOW.json` and `completions/LOCAL-RELEASE-CHECK.md`.
