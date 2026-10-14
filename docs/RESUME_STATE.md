# Active Sol Medium implementation checkpoint

The user selected GPT-6.1 Sol Medium on 2026-10-14. Continue eligible Sol integration tickets; preserve the original allocation and completed component evidence.

Current canonical board: **29 done, 35 implemented_pending_verification, 32 planned**. Only fully accepted and verified scope is marked done in `tickets.json` and `TICKET_STATUS.md`.


## Sol integration checkpoint — 2026-10-14

The user switched to GPT-6.1 Sol Medium and authorized continued backlog execution. **SKR-037, SKR-038 and SKR-046 are now done** against their declared component scopes. See `docs/completions/PIPELINE-INTEGRATION.md` for 164 passing combined backend checks, 84 web checks, actual Chromium HTTP-to-JS collecting-stage escalation, and the real Llama known-fact trial (one call/1,141 tokens/9.487s; five other drafts rejected). The database fixture moved to root `tests/conftest.py` to fix mixed-folder fixture lookup.

New `research/collection.py` schedules per-candidate collecting attempts after discovery when configured; `research/page_extraction.py` schedules source-specific unverified directory observations from private integrity-checked evidence. Runtime handles discovering/collecting/extracting separately; task replay, tenant, deadline, budget, source-disable and cancellation controls are retained. `Settings` rejects production public collection; local public reads require a trusted loopback GuardedProxy, optional extraction disables AI planning, and optional dynamic collection requires the reviewed immutable image. Generic web reads refuse platform routes; LinkedIn/Reddit indexed references remain supported and their direct-read gates stay open. The UI displays collection status, source quotes, rejected drafts and incomplete coverage safely.

No Groq request was made. The live local trial initially found untyped draft and oversized schema-grammar failures, retained in separate JSON reports. Compact transport instructions and a strict nested draft schema with a 512-character model quote limit fixed the known-fact trial. Full original quotes remain preserved. This does not establish release model accuracy or accepted lead qualification. The current running API/worker have not yet been restarted for these flags. Local flags remain off until configured; `scripts/dev_stack.py` now manages a configured local GuardedProxy.

Next eligible Sol work: SKR-069 entitlements/abuse caps, then trusted identity/qualification orchestration, retention/deletion and registered source readers. Hosted collection/tokenizer packaging remains open. Preserve the dirty worktree and original copied/reference trees.

## Prior Luna work completed this batch

- **SKR-008 done:** CI gates/report paths and offline/live opt-out contracts verified. Six workflow contract tests passed. Web tests/build/contracts and backend provenance runs passed in this batch. GitHub-hosted actions themselves have not run from this workspace.
- **SKR-032 done:** authenticated per-operation readiness UI now accompanies existing tenant diagnostics/owner switches. It distinguishes public indexed references from direct source adapters and does not claim credential verification. Existing PostgreSQL/workflow tests and 77 frontend tests passed.
- **SKR-058 implemented_pending_verification:** paused runs can request workspace-scoped API resume using a fresh idempotency key; UI verifies queued response and reloads state. Partial results and actual counts remain visible. A workspace-scoped usage endpoint and UI now separate confirmed, estimated and reserved amounts and show remaining budget. Source-specific reconnect actions and qualified/near-match evidence panels remain blocked on their source credential and qualification integrations.
- **SKR-063 implemented_pending_verification:** read-only public GitHub repository/profile metadata adapter has eight async safety/contract tests and a two-request live public API smoke test; no credentials, private access, or writes. Collection integration and persisted qualification evidence remain open.
- **SKR-065 implemented_pending_verification:** public metadata and timestamped WebVTT parsers pass five fixtures; no live video call, auth, bypass, audio download, or synthetic transcript. Caption retrieval/runtime and production integration remain open.
- **SKR-066 implemented_pending_verification:** six directory page presets use the copied saved-content graph and shared PostgreSQL model ledger. Four unit/DB tests pass; results stay source-specific and unverified until guarded fetch, persisted evidence, identity and qualification stages are wired.
- **SKR-064 implemented_pending_verification:** bounded RSS/Atom parser reuses declared feedparser dependency and copied URL validation. Four fixtures cover IDs, duplicates, feed dates, relative/private links and size limits. Collection orchestration, tenant persistence and shared budgets remain open.
- **SKR-054 done:** authenticated private evidence-backed CSV/JSON/JSONL exports restrict values to trusted accepted or selected near-match data and recheck tenant scope, expiry and integrity at download. Twelve real PostgreSQL/private-disk export tests, Ruff and MyPy passed. UI selection and production pipeline wiring remain separate work.
- **SKR-053 implemented_pending_verification:** search provenance is now visible per result with safe links and explicit search-reference limitations; 79 frontend tests, typecheck, contract check, build and UI detector pass. Claim-level evidence and classifications remain open.
- **SKR-052 implemented_pending_verification:** run view now fetches and displays the workspace-scoped saved interpretation, criteria groups, unsupported criteria, clarification and selected sources. Clarification resubmission/plan revision remains open. 78 frontend tests, typecheck, contract check, production build and UI detector passed.
- **SKR-070 implemented_pending_verification:** worker persists allowlisted stage outcome, I/O duration, accepted count and confirmed/estimated cost observations, including failed zero-result calls. Job usage now aggregates bounded stage/source success, failure, results, I/O, and cost metrics; the results UI displays them and flags malformed/truncated data. Seven worker DB tests, two usage API DB tests, 81 web tests, typecheck, contract checks, build, Ruff/MyPy, and UI detector passed. Separate parser/network/browser/queue/LLM timing, request/trace correlation, blocked-response categories/denominators, and broader integration/security acceptance remain open.

Verification: **77 frontend tests passed across nine files**, TypeScript and API contract drift checks passed, Next production build passed, UI detector had no findings. RSS parser: **4 tests passed**, Ruff/MyPy and `uv lock --check` passed. All three copied repository provenance checks passed.

## Sol stabilization evidence retained

Durable opt-in planning bootstrap, authenticated lists API, extractive report component, scoped resume API, job-plan view, job-scoped reservation migration 0018 and cancellation boundaries are implemented. Semantic model quality remains inconclusive; AI planning stays disabled by default. Standalone isolated Chromium reads public pages and JS fixtures through the guarded proxy, and active browser cancellation/removal passed. The production HTTP-to-browser escalation and connection-aware resume are still open. Actual Python 3.12 browser-image kernel/security suite passed 36 checks; browser component/container suite passed 22. The final Sol backend regression before the Luna edits passed114 tests.

Fresh free keyless search completed with two unverified references in8.633s. The user separately confirmed Google sign-in and results. Do not inspect the user's localhost browser or auth session; earlier browser access was declined. No Brave paid key or new API key is required for current search. Groq remains optional; do not use or repeat the key exposed earlier in chat. Ollama remains the default with the user's two installed models.

Native PostgreSQL 54439 and RabbitMQ 56739 are available. API was restarted under PID26824 after the plan-view changes; worker PID10319. Preserve the user-edited reference chat file and copied upstream trees.

## SKR-069 closure and running services

SKR-069 is done: migration 0019, immutable quota admission, forced RLS/column permissions, scoped owner settings/API/UI and operator manual pilot provisioning. Eleven entitlement DB cases and 193 combined backend checks passed; 88 web tests/build/typecheck/contracts passed. API PID 74870, worker PID 74871 and native GuardedProxy PID 74869 are running; private process journal/logs are in `.runtime/sol-services.json` and `.runtime/sol-*.log`. `health/ready` returned 200. Ignored root `.env` now enables local public collection, saved-page extraction and reviewed isolated JS escalation; AI planning remains off, model provider Ollama, no Groq call. The tests root overrides optional .env feature flags in test processes only, preventing ordinary tests from inheriting live opt-ins.

Next work: SKR-071 retention/cleanup, then SKR-072 erasure/suppression and remaining source/identity/qualification gates. Do not stop simply for another model change. User browser/auth session remains off limits; no private credentials printed.

## SKR-071 closure

SKR-071 done: source TTL ceilings/backfill, stale result-citation filtering, scoped repeat-safe blob/excerpt cleanup, durable schedules/recovery leases and actual 45-second bounded child execution. Six retention DB cases and 83 related regressions passed; web 88 tests/build/typecheck/contracts and detector passed. API PID11460, worker PID11461, retention PID11462; proxy PID74869. Process journal `.runtime/sol-services.json` is authoritative. Cleanup daemon is running; pause only that known project process while tests deliberately manipulate cleanup schedules, then restart it after the batch, to prevent global due-claim races with test fixtures.

Next: SKR-072 erasure/suppression and backup deletion replay; preserve separate hosted/source/identity/qualification gates. No new API key/model switch needed for current local work.
