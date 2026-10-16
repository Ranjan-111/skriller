# Local operations, source support, and pilot runbook

This runbook describes the current local pilot stack. It is not a production hosting procedure. Hosted deployment, private off-host backups, direct LinkedIn/Reddit account reads, and customer pilot evidence remain open release gates.

## What is supported today

Use `/health/live` to check whether the API process responds and `/health/ready` to check database and broker readiness. Readiness does not prove a worker is consuming, a source account is connected, or a source is returning useful results. Check the worker process and its redacted logs separately. `scripts/dev_stack.py` starts the API, research worker, retention worker, web app, and the configured local collection proxy in one foreground process. PostgreSQL and RabbitMQ must already be running. Ctrl-C stops only children started by that command. If a port is occupied, the script exits without stopping the process that owns it.

Workspace source status is available to an authenticated member at `GET /v1/workspaces/{workspace_id}/sources`. It reports operation readiness and configured state, not a promise of source coverage. Owners can pause one workspace operation through `PUT /v1/workspaces/{workspace_id}/sources/{source}/{operation}` with `{"disabled":true}`. Supported operation names are `discover`, `read`, and `analytics`. This switch prevents new external I/O for that workspace operation; previously saved results remain available. Re-enable with `{"disabled":false}` only after the cause is understood. Keep Firebase bearer tokens in a private shell variable or authenticated client; never put them in a ticket, report, or log.

The local discovery path uses keyless Exa search when `SKRILLER_SEARCH_PROVIDER=exa_keyless`; it needs no API key and is subject to provider limits and unverified commercial terms. Set the provider to `disabled` to stop discovery globally, then restart the API. Public web collection is separately opt-in with `SKRILLER_ENABLE_PAGE_EXTRACTION=true` and a guarded `SKRILLER_PUBLIC_COLLECTION_PROXY_URL`. Dynamic browser collection has its own opt-in and reviewed image requirement. Leave both collection paths disabled when source access is not approved or their readiness checks are unclear. Ollama remains the default model provider; local search does not require a model key. Restart the worker after changing provider/model configuration. Do not use Gemini or Groq fallback without an explicit reviewed pilot decision.

Current source support statements must match the operation status: indexed LinkedIn and Reddit references are search results, not direct account-backed reads or verified identities. GitHub public metadata/profile reads, RSS, public web collection, and public YouTube caption reads have operation-specific local evidence; each has its own stated bounds and remaining hosted or coverage checks. LinkedIn and Reddit acquired-reader integration and account tests remain deferred. Never advertise authenticated platform access, complete platform coverage, anti-bot success, or verified lead identity based on indexed references or fixtures.

## Triage an incident

1. Record the affected workspace, job ID, time range, source operation, user-visible status, and whether useful results were already saved. Do not copy source cookies, bearer tokens, raw page bodies, private excerpts, or unredacted logs into the incident record.
2. Check `/health/live`, `/health/ready`, API/worker process state, and redacted worker diagnostics. Separate database/broker failure, worker delay, source denial/rate limit, expired connection, budget exhaustion, and extraction/review failure. A successful liveness response alone is insufficient.
3. For a source-specific outage or unexpected response, use the workspace owner switch above to disable only that source operation. For a global keyless search outage, set `SKRILLER_SEARCH_PROVIDER=disabled` in ignored configuration and restart the API. Preserve completed results and tell users that new work is paused or partial; do not replay repeatedly against a denial or rate limit.
4. For API or worker code/configuration regression, stop the local stack with Ctrl-C if it owns those children. Restore the last reviewed source/configuration revision and known-good immutable image reference, then restart the stack. Do not overwrite a database or downgrade schema as an improvised rollback. Database schema rollback needs a reviewed migration-specific recovery plan.
5. Confirm readiness, worker consumption, and one bounded synthetic/local workflow before reopening the operation. Re-enable only the affected switch after the source status and job outcome are understood. Record the result and remaining uncertainty.

## Reconnect an account-backed source

Paused result responses include an advisory `resume_status`. Only `available` is eligible for a resume attempt; the mutation repeats all checks under the job lock. `requires_reconciliation` means an unfinished call or result needs operator investigation. `deadline_expired` needs a new run, `new_prompt_required` needs a corrected objective, and `budget_exhausted` cannot be bypassed by resume. If saving a reply fails, prior results remain available and the call's known usage or conservative estimate stays recorded. Investigate the `checkpoint_failed` event without repeating the call automatically. An interrupted process may leave an unknown reply and an estimated charge; never claim that reply was recovered.

No production LinkedIn or Reddit direct-read reconnect procedure is currently supported. When an acquired connection flow becomes available, reconnect from the source's approved account flow, never by pasting a cookie into support. An expired or revoked connection should pause that source operation; confirm the exact workspace and requested read scope, reconnect through the supported flow, then resume from a persisted checkpoint. Do not reuse an old job's credential generation or claim that a new session proves historical reads. Until that operation is implemented and account-tested, report direct account reads as unavailable and continue only with separately enabled indexed discovery.

## Local data recovery

Use [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md) for the encrypted local backup and isolated restore rehearsal. It requires a separate backup key and owner database access. The utility has bounded local-pilot limits and does not provide hosted off-host custody or scheduling. Never restore into a live database or connect a restored database to the old broker before offline validation. Recover the database/source-credential keyring separately. A backup present only on the same machine is not a disaster-recovery copy; hosted restore claims require off-host storage and a deployed rehearsal.

## Cost and pricing assumptions

Do not quote a selling price from local fixture timings. For each pilot workflow, record actual admitted runs, source/provider request counts where observable, model calls and returned token usage, browser/container time, storage bytes and retention window, operator review minutes, and any provider invoice data. Missing usage or billing reports stay unknown. Estimate unit cost only from observed billable inputs and the actual vendor rate card selected for that pilot, and report the uncertainty range. Include fixed hosting, backups, support, and expected failed/partial work separately. Free-tier quotas are a development constraint, not production capacity or unit-economics evidence. No pricing or willingness-to-pay conclusion is established yet.

## Pilot worksheet

Before each real pilot workflow, capture a pseudonymous workspace label, user objective, approved source operations, expected fields, and success definition. Afterward record completion/partial/failure, source-access failures separately from extraction/qualification errors, supported-field precision and unknowns against reviewed labels, user review time, retries, observed cost inputs, limitations, and the user's value/willingness-to-pay response. Repeat tasks across at least three prospective workspaces and preserve failed runs. Do not enter fabricated results. Mark the pilot gate complete only after repeated real workflows demonstrate value and the advertised operations match observed support.

## Local benchmark

Run the bounded offline fixture diagnostic with:

```sh
uv run python scripts/probes/local_job_benchmark.py --repetitions 5
```

It reuses the existing copied classifier and cleanup pipeline, excludes one warmup, limits repetitions to 20, and writes scalar timing/resource evidence to `docs/completions/SKR-075-LOCAL.json`. Source fixture outcomes are not real source availability; model, network, browser, concurrency, and multi-workspace timing are not measured. `tracemalloc` reports Python allocation peak. Process RSS is cumulative and cannot be attributed to the benchmark. These small local percentiles do not establish PRD targets or an SLA. A release benchmark still needs a declared hosted hardware profile, real bounded job-stage observations, source/model/network separation, and concurrent browser-heavy work across two workspaces.
