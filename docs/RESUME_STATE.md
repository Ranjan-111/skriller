## Final local release check and manual handoff — 2026-10-18

139 backend/integration checks passed, 1 optional model skipped; 176 focused web
checks, typecheck, generated-client contract check and production build passed.
Cleanly restarted verified project app processes with scripts/dev_stack.py
--discovery-only (exec session 43400). App is running at localhost:3000 / API 8000;
root .env remains unchanged (its experimental flags are still enabled, so use the
explicit profile). Native PostgreSQL 54439 and RabbitMQ 56739 remain running.
Actual worker/free-search probe completed: 2 unverified results in 7.884s.
Readiness dependencies all true, migration 0056 at head; actual app DB role is
not superuser and cannot bypass RLS. Human Firebase/current source-export browser
check is still pending and no user browser/session was accessed.

Added docs/LOCAL_RUN_AND_MANUAL_TEST.md and docs/DEPLOYMENT_HOSTING_GUIDE.md.
Optional private data Compose overlay and operator migration task prepared; full
combined Compose config --quiet validates using synthetic temporary files. No
containers/images/remote resources were run or purchased. Four priority statuses
remain open: quality failures and actual source/browser/host acceptance are not
closed by local fixture success. Board 57 done /33 pending /2 in_progress /4 planned.
Evidence docs/completions/LOCAL-RELEASE-CHECK.md and its JSON reports. No coding-model
switch or additional key needed for the manual discovery/source-export test.

## Priority launch batch — 2026-10-18

SKR-096 numeric bounds now bind to their own comparison words; four reproduced
baseline failures are fixed. Real database bootstrap confirms no successor/search
dispatch or duplicate model call after rejected swapped bounds. SKR-067 combined
copied extraction -> explicit owner review -> private export now passes with saved
evidence, while the unconfirmed Reddit discussion is rejected. SKR-074 application
Compose definitions and operating instructions added; only YAML/static review ran,
not Docker or hosted verification. 100 focused local tests passed, 1 optional model skip;
Ruff/format and three-module MyPy passed. Separate authorized Groq diagnostics failed semantic quality. Report:
docs/completions/PRIORITY-LAUNCH-LOCAL.md. Four ticket statuses/counts unchanged.
User approved Groq comparison. Across 23 synthetic calls, 20B and 120B baseline
diagnostics each scored 2/5. Prompt experiments were reverted; final experiment
hit HTTP 429 and remote calls stopped. All reports retained separately. Ollama
remains the configured application provider; optional Groq model allowlist added
without changing defaults. No Codex coding-model switch is required and no heavy
local download occurred. Model/provider quality and hosted gates remain open.

# Deployment packaging and launch estimate — 2026-10-18

SKR-074 moved planned -> in_progress: added apps/api/Dockerfile and operating notes
for a locked non-editable backend image with non-root API/worker/retention runtime.
The three checked-in reused projects are built into installed distributions; no
reference ZIP, .env, browser or heavy model is copied. Worker HTTP-health overrides,
read-only extraction assets and the separate isolated browser-controller boundary
are explicit. Root and web build contexts now exclude local .env variants.

Static review/diff check only: user deferred image builds/container acceptance. No
Docker daemon, source account, hosted service or local running app was touched.
Prepared packaging is not a built/verified image and does not close deployment.

Board: 57 done /33 implemented_pending_verification /2 in_progress /4 planned; 39
open including 28 P0. Nine launch acceptance work packages and the actual/proposed
stack, scope and conditional effort estimate are in DEPLOYMENT_LAUNCH_PLAN.md.
Initial staging estimate 3–5 focused engineering days once deferred hosting/container
prerequisites exist; real pilot roughly another 1–2 weeks. Full paid launch has no
reliable date with model-quality/provider/billing acceptance unresolved.
No coding-model switch required. Keep quality and all other saved deferrals pending.

---

# Local launch tooling — 2026-10-18

User keeps model quality pending on base M4 Air. Do not download heavier models or
continue repeated local-model experiments; this does not close the quality gate.
Continue independent local work without requiring a Codex coding-model change.

Fixed scripts/dev_stack.py to launch installed project Next with installed Node,
removing the global pnpm version dependency. Missing dependencies fail before local
configuration loading. Owned-process cleanup now tolerates exits between poll and
kill, ensuring other children still stop. Two focused offline fixtures and Ruff/format
pass. No real service was started/restarted and no local .env read by these checks.
SKR-079 report/status evidence updated; hosted/customer-pilot acceptance remains open.

Board counts unchanged. No full build, broad regression suite, live source request,
model call or download needed for this batch. All prior deployment/account/expansion
acceptance deferrals remain in force.

---

# Planner reliability batch — 2026-10-18

Implemented omission guards for explicit industry and maximum employee constraints,
and additional already-supported minimum employee wording. Missing criteria pause
for clarification; no weaker plan or inferred criterion is executed. Seven added
cases cover missing values and preservation of correctly grounded industry/maximum
criteria. Final sequential planner/schema suite: 50 passed, 1 optional model test
skipped; Ruff/format/MyPy pass. No UI/build changes in this batch.

Four bounded actual-local-Llama schema/prompt experiments failed to improve the
unchanged 5-case diagnostic (1/5,1/5,2/5,1/5). All changes from those experiments were
reverted and all reports preserved. Canonical PLANNER-QUALITY-LOCAL.json remains the
historical 2/5 baseline with its original code hashes; it does not benchmark the new
guard-only change. Do not pool scores or close representative semantic quality.
No cloud/source/account call or production configuration changed. Initial concurrent
fixture failures are not counted as passes; final regression suite ran sequentially.

User question pending: stronger local Ollama runtime (download/RAM decision) versus
keeping model-quality acceptance pending while local core work continues. This is
not a Codex coding-model switch; Sol remains appropriate and no API key is required.
Board unchanged: 57 done /33 pending verification /1 in_progress /5 planned. Language
and regional expansion plus prior external acceptance remain deferred.

---

# Qualified-export core batch — 2026-10-18

SKR-067 gained a confirmed-record CSV/JSON action wired to the existing private export
backend. It rechecks qualification server-side, excludes implicit near/unverified
selection, validates confirmation/files, bounds streaming and discards canceled or
stale scope responses. Source-list exports remain separate.

58 focused client/results checks pass; one new real-PostgreSQL checkpointed
qualification -> private CSV API check passes, including exact selection and stale
excluded denial. Types/formatting and mechanical UI detection pass. Reviewed fixture
facts do not close full actual-model acceptance. See QUALIFIED_EXPORT_RUNBOOK.md.

No source/cloud/account access, new credentials or model switch required. SKR-067
remains pending full actual-model prompt-to-qualified-export and authenticated browser
acceptance; SKR-076 quality remains failing. Board counts unchanged. SKR-091/092 and
external/container/deployment acceptance remain deferred as recorded.

---

# Core launch batch — 2026-10-18

User explicitly deferred SKR-091 and SKR-092 for launch. They stay planned with
launch_scope=deferred_by_user; do not spend launch work on language/regional expansion.

SKR-041 hardened: private cache metadata binds the credential generation and access
requires its initiating owner. Old generations/legacy private entries miss; rotation
during staging fails closed. Public-cache dates, TTL and conditional reads unchanged.
15 targeted real-database cache/collection checks, Ruff/format and MyPy pass.
Authenticated workers still make fresh reads; optional private replay integration and
hosted/private-storage acceptance are not claimed complete.

SKR-033 stale stage-wiring blocker corrected after three targeted database workflow
checks passed; provider-use/egress gates stay open. **Production Next.js standalone
build passed** using the installed toolchain; no Docker build/deployment/live account
or cloud-model request. No model switch or API key needed for this batch.

Board remains 57 done /33 implemented_pending_verification /1 in_progress /5 planned.
A code improvement does not close an outstanding acceptance gate. Core release
blockers are explicit in CORE_LAUNCH_READINESS.md, especially failing semantic quality
and the incomplete prompt-to-qualified-export gate. Do not call this launch-ready.

---

# Latest implementation batch — 2026-10-18

SKR-085/086 now **implemented_pending_verification**. Actual copied OpenCLI read
functions feed generated static scripts, isolated scoped workers, durable native
discovery and profile collection, budgets/cancellation/generation fences, private
evidence, retention/erasure, typed API/client, optional source controls and bounded
result views. No host browser/account/daemon or live source call was used. Routes
remain default-off until explicit pinned-image and owner-session configuration.
See SOCIAL_BACKEND_REVIEW.md and completions/SKR-085.md / SKR-086.md.

The client distinguishes missing counts from zero, preserves Facebook display text,
and makes unknown identity/visibility and partial coverage explicit. Raw social
profile bodies remain excluded from source exports. A newly covered CSV defect with
absent optional metadata is fixed. Async plan refresh follows job-state changes so
planning failures cannot remain stuck at the initial planning snapshot.

Checks: **170 focused web tests passed** (API, results, exports, workbench), TypeScript
and formatting pass; mechanical UI detector reports no findings. Related backend
checks: **228 distinct passes across the initial run plus one recovered RabbitMQ
handshake retry**; final overlapping **57** source/worker/hash tests pass, MyPy passes
18 changed Python modules, and OpenAPI/generated client drift checks pass. No broad
production build or container run was repeated. Browser visual/live acceptance is
unverified under the saved restriction. Docker verification is user-deferred until
final deployment; do not ask for Docker again during local implementation.

SKR-076 remains in progress: Llama examples experiment 2/5 was reverted; installed
DeepSeek independently scored 2/5. Canonical baseline/code hashes restored and all
failures retained. Neither synthetic result closes representative semantic quality.
No cloud call, new API key or provider change was needed.

Board: **57 done /33 implemented_pending_verification /1 in_progress /5 planned**.
No whole-ticket Done claims were added. Required acceptance remains on each ticket;
DONE_TICKET_FOLLOWUPS.md needs no new entry. Local completion is not deployment
readiness. A model switch is not required for the code in this batch.

Remaining planned work: hosted pilot SKR-074 is user-deferred; SKR-091 requires a
selected language; SKR-092 requires a selected regional source and live acceptance.
SKR-094 needs labelled retrieval tasks before comparative infrastructure evaluation;
SKR-095 is conditional on evidence that selected source routes require a companion.
Do not add speculative databases or a desktop app just to move status counts.

---

# Latest Luna batch — 2026-10-17

Completed the SKR-052 rejected-planning recovery UI in the existing interpretation
panel. It distinguishes invalid interpretation, model unavailability, limits and
interrupted planning, states that source search did not begin, and does not retry or
submit automatically. The original prompt remains in the composer with an explicit
edit action. Old rejected-plan API responses receive a neutral explanation without
assuming whether search started. Saved results remain visible.

Verification: **50 results component tests passed**, including all four categories,
explicit edit, no automatic submission and legacy metadata absence. Web TypeScript,
Prettier and the Impeccable detector passed. SKR-052 stays
**implemented_pending_verification** because authenticated browser acceptance is still
pending under the saved localhost browser restriction. No API key or account setup is
needed for this local work. Board **57 done /31 pending verification /3 in_progress /5
planned**.

**Next model: GPT-6.1 Sol Medium** for the existing SKR-076 planner quality/evaluation
work, with SKR-085/086 social backend integration remaining in progress. Preserve the
2/5 local quality result and all historical failures; no model/cloud key or platform
account is needed for independent local work.

# Latest Sol batch — 2026-10-17

Reviewed and fixed SKR-068 owner-review recovery: blank choices never map to index
zero; selection locks while pending; scope/candidate/unmount fences abort or ignore
late responses; every failed approval discards its hash/confirmations, with result
refresh for network/conflict failures and preservation on 403. Decision projections
must include both selected claims with unique IDs. 124 API/results tests pass.

SKR-076's generation schema now declares the quote bounds already enforced by
parsing. One actual local Llama rerun remains **2/5**: company/numeric outputs pass
empty-string schema constraints but fail unchanged literal grounding. Previous run
retained as PLANNER-QUALITY-PRE-BOUNDS-FAILURE.json. No semantic/release gate closed,
no prompt/guard assertion weakened, no ignored settings changed.

Rejected planning now exposes fixed optional PlanningFailureView on the existing
plan endpoint: invalid interpretation/model availability/budget/interruption, fixed
recovery choice, source_search_started=false and automatic_retry_allowed=false.
No raw provider/model text. Generated contracts and strict transport are ready.
See PLANNING_FAILURE_RUNBOOK.md for the next Luna UI subtask.

Started SKR-085/SKR-086 by acquiring the actual OpenCLI source at pinned commit
e6174a952c763a836a9bb0dd2f097d2962b3876b: 2,343 unchanged files, Apache license,
archive/per-file hashes. Source review identifies reusable read modules, business/
private/group and missing-counter limitations; no install script, daemon, profile
discovery, account or source operation ran. Three integrity/routing/metadata checks
pass. See SOCIAL_BACKEND_REVIEW.md. Copied-code execution/isolation and durable worker
integration still remain Sol work; acquisition does not activate either platform.

Verification: **102 related backend checks passed across the initial run plus one
broker retry; 1 optional model skip**. The initial real RabbitMQ task-delivery test
timed out; native broker was running without alarms and normal connectivity recovered;
that single test then passed. No service restart/config edit. Docker Desktop socket
is unavailable, a future container-test prerequisite. **124 web tests**, TypeScript,
contracts, Ruff and three-module checked-body MyPy pass. Actual model quality failures
are separate. Board **57 done /31 pending verification /3 in_progress /5 planned**.

**Next model: GPT-6 Luna Medium** for SKR-052 rejected-planning recovery rendering.
Use generated optional metadata and the runbook, retain prompts/results and explicit
new submission; never automatic retries or cloud/key fallback. No key/source account
or user browser test is needed locally. Preserve all deferred hosted/account/payment
gates, denied localhost browser access, and SKR-076 representative quality failures.

# Latest Luna checkpoint — 2026-10-17

Implemented the SKR-068 owner role-review UI and strict API client in the existing
candidate results. Owners can explicitly choose previously extracted role/date
claims tied to the same saved LinkedIn profile, preview the server's exact cited
roles/dates/excerpts, and separately confirm same subject and original person when
required. Requests bind the workspace, entity, claim/date/evidence IDs and both source
URLs to the selected canonical LinkedIn profile. A 403 leaves current results intact;
a 409 or unclear approval refreshes results and drops the stale preview/hash instead
of replaying it. Successful review refreshes fit data. It creates no claims and
doesn't verify source identity or infer Reddit linkage.

Verification: **114 focused API/results UI tests passed**, TypeScript noEmit and
Prettier passed, and the Impeccable detector returned no findings for changed UI
targets. The pnpm wrapper refused its declared-version check (installed 11.1.1,
required 12.6.0), so existing local binaries ran tests/typecheck/format. SKR-068 is
now **implemented_pending_verification**; board **57 done /31 pending verification /
1 in_progress /7 planned**. Account-backed LinkedIn/Reddit operations, hosted pilot,
source-rights and operation-limit acceptance remain open/user-deferred.

The earlier Impeccable flat-type findings on `tests/fixtures/research/company.html`
and `changed.html` were scoped as false positives: these are parser input fixtures
whose third-party typography is not product UI. Narrow per-file `flat-type-hierarchy=*`
ignores were added. The changed results UI detector reported no findings.

**Next model: GPT-6.1 Sol Medium**, continue the SKR-076 local planner-quality and
representative evaluation work. The final installed Llama diagnostic remains 2/5;
preserve all historical failures and denominators. Do not call small synthetic
fixtures representative release evidence or invent human labels. No API key or
account test is needed for independent local fixes.

# Latest Sol checkpoint — 2026-10-17

Completed the local SKR-068 reviewed-founder backend path. Native profile candidates
can now reach explicit owner role review without silently promoting source identity.
The candidate's exact saved LinkedIn profile, literal dated titles, source/provider,
excerpt and observed time must agree; a separate person confirmation is required
before an `other` record becomes `person`. Approval is audited and atomic. Model
drafts remain unverified until owner review, and Reddit context stays separate.

The production planner's role criteria now compare current reviewed job-title/role
evidence, with historical/conflicting/undated observations fenced out. Only the
supported founder/engineer plural forms normalize. Model guesses cannot resolve
ambiguous person/company geography; exact subsequent user clarification works.

Three actual adapter/database/API scenarios cover both platforms, outage isolation,
and the grounded founder plan through copied extraction, owner preview/approval,
current fit, a cited report and immutable refinement. Final backend selection:
**138 passed, 2 optional checks skipped**. Also **111 web regressions**, TypeScript,
generated contracts, Ruff and checked-body MyPy across five changed modules pass.

SKR-076 now has complete failure evidence for the five-case actual local Llama
diagnostic: **2 checks passed, 3 failed**, five model calls and zero source calls.
Prompt alternatives regressed or stayed unreliable; their separate reports remain,
and original instructions were restored. No release-quality gate is closed. A direct
Settings check found AI planning enabled in the existing local configuration; the
earlier commentary claiming it was disabled was incorrect. No ignored settings were
changed. Bad responses retain the existing server rejection behavior.

**Next model: GPT-6 Luna Medium**, implement the explicit owner-review results UI
and strict client using generated role-review DTOs and OWNER_ROLE_REVIEW_RUNBOOK.md.
No API key, source account or browser access is needed. SKR-068 remains in_progress
for this UI and deferred acceptance; SKR-076 remains in_progress for model/representative
quality. Board unchanged: **57 done /30 pending verification /2 in_progress /7 planned**.
No ticket was falsely marked done. Keep hosted, account, payment sandbox and X live
work user-deferred. Preserve the denied localhost user-browser restriction.

# Prior rebind UI checkpoint — 2026-10-17

SKR-025/SKR-030 now have local owner-confirmation UI for checkpoint rebinding. The
owner explicitly loads choices, selects a pending LinkedIn/Reddit source and active
replacement, then confirms before submission. The client validates metadata-only,
workspace-scoped connection records; a lost response retries with the same exact
payload and idempotency key, while a 409 requires refreshing choices and confirming
again. Existing ordinary resume does not change credentials implicitly. Results
remain visible on errors.

Sol's local backend remains in place: known stale native LinkedIn/Reddit bindings
pause before reservation or I/O; explicit initiating-owner selection atomically
binds the current new generation and resumes pending reads. Plan/deadline/usage and
route spend stay intact. Scope, expiry, cancellation, uncertain-work and replay
barriers pass.

SKR-068 now has two passing actual adapter/database/API scenarios for mixed-source
reads, outage isolation, replay, unverified evidence and immutable refinement. It
remains in progress for accepted founder/cited-report and representative live work.
Sol also corrected LinkedIn client URL-kind/canonicality and timezone validation.

Verification this batch: **111 focused web tests passed**; TypeScript, generated
contract check, production build, Prettier and Impeccable detector pass. Backend
evidence below remains valid. No source/model call, user browser, API key or ignored
environment edit was used. Latest board: **57 done /30 pending verification /2
in_progress /7 planned**. No ticket was promoted to done; account-backed and hosted
acceptance remain deferred.

**Next model: GPT-6.1 Sol Medium** for SKR-068 founder/cited-report local acceptance
and SKR-076 quality evaluation as scoped in model_ticket_allocation.json. No new key
or manual test is needed.
Native/account, hosted, billing sandbox and X live gates remain user-deferred.
The localhost browser restriction remains active. Earlier checkpoints below are
historical; docs/tickets.json and TICKET_STATUS.md are authoritative.

# Active Sol implementation checkpoint — 2026-10-17

Completed the SKR-061 Reddit OAuth backend and bound pagination batch. New migrations0055/0056 provide owner-encrypted grants, co-owner runner fences and single-use job/actor/request/credential-bound source cursors. The durable discovery workflow pages within a reserved call cap, honors source cadence, retains partial pages and does not replay uncertain source requests. Configured User-Agent reaches the isolated worker. Actual backup restore revokes grants and clears seeded cursor rows. X lifecycle behavior remains compatible.

Verification: **113 backend/database/container tests, 192 web tests**, TypeScript, actual generated contracts, Ruff/format and13-module checked-body MyPy pass. Actual worker image: sha256:20770c2c718f1d3a954ea42e0638cad2f598755e76600391442c5eec825f40f1. No live source/model/payment call, account session or ignored environment setting was used.

Board: **57 done /26 implemented_pending_verification /3 in_progress /10 planned**. SKR-061 remains in progress for owner consent/callback/refresh/disconnect UI plus user-deferred real source/hosted acceptance. Next model: **GPT-6 Luna Medium**, implement the full optional Reddit OAuth UI using the X patterns and generated Reddit DTOs. Fixed Reddit authorization endpoint, read-only scope, duration=permanent and no PKCE. Complete/refresh return ConnectionMetadata.id. Preserve indexed Reddit source availability without an account. Saved localhost browser restriction remains; no API key is needed. Automatic renewal/checkpoint rebinding remain Sol-owned lifecycle limitations.

# Active Luna implementation checkpoint — 2026-10-17

The user selected GPT-6 Luna Medium. The combined SKR-061/084 result UI/export batch is complete: native public-post excerpts are distinguished from indexed references, and JSON/CSV exports preserve provider, evidence kind and query provenance. **192 web tests passed**, TypeScript and generated contract checks passed, Prettier and Impeccable detection are clean. No source account/browser session was used.

Canonical board: **57 done, 26 implemented_pending_verification, 3 in_progress, 10 planned**. SKR-084 local implementation moved to implemented_pending_verification; X developer-app/live-search and hosted acceptance are user-deferred. SKR-061 remains in_progress for tenant/connection-bound cursor continuation and Reddit OAuth onboarding/refresh.

Next model handoff: **GPT-6.1 Sol Medium**, continue SKR-061 backend lifecycle/cursor work. No API key or account setup is needed for the local implementation. Live Reddit relevance/coverage and hosted acceptance remain user-deferred.

# Active Sol Medium implementation checkpoint

The user selected GPT-6.1 Sol Medium on 2026-10-14. Continue eligible Sol integration tickets; preserve the original allocation and completed component evidence.

Current canonical board: **55 done, 21 implemented_pending_verification, 3 in_progress, 17 planned**. Only fully accepted and verified scope is marked done in `tickets.json` and `TICKET_STATUS.md`.


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

## Sol continuation — 2026-10-14

SKR-072 done: owner-only API, minimal forced-RLS journal, history delete guards, job/privacy write fences, derivative invalidation, suppression and actual restore replay after synthetic source-database loss. SKR-073 implemented_pending_verification: encrypted snapshot/database/blob utility and independent current journal receipts, expiry pruning and isolated clean PostgreSQL restore pass; off-host daily custody and actual pilot RPO/RTO remain. Reports/runbook: completions/SKR-072.md, completions/SKR-073.md, completions/LOCAL-BACKUP-RESTORE.json, RECOVERY_RUNBOOK.md. Final related regression107 passed, two explicitly opt-in live/container cases skipped; web88 tests/contracts/typecheck pass. No Groq/new key used; no user data erased. Managed API83412/worker83413/retention83414 restarted gracefully; current PIDs in .runtime/sol-services.json. Preserve separate source/quality/hosted gates.

Additional erasure seam hardening: private export/list-refresh/identity writers share privacy locking; claim repository rejects tombstones; linked group reloaded under fence. Actual concurrent export/delete test passes (36 related checks); 63 contact/extraction/recovery checks pass, one live model skip. Active services need one more API/worker graceful restart for these final guards. Next work begun: copied cleanup/tokenizer offline packaging in infra/egress/Dockerfile.cleanup; container build/probe pending, do not mark SKR-044 done yet.

SKR-044 final offline gate passed: image sha256:ef73de989393c311d729546b0d3cb3177f1753614cde683f6236cdbeea7c31d5, two actual network-none cold container cases and20 helper checks. Eight uv.lock wheels staged by scripts/provision_cleanup_assets.py; image installs offline after exact SHA checks. Initial truncated minify wheel rejected; locked hashes retained. SKR-044 done; board31 done/35 pending/30 planned. Hosting/off-host storage clarification was asked asynchronously; continue independent local work while pending. Final privacy guard derivative regression27 pass. API/worker gracefully restarted again; PIDs in .runtime/sol-services.json.

## Public source integration checkpoint — 2026-10-14

User explicitly chose keep hosted work pending and continue locally on Sol Medium. SKR-063 done: public GitHub collecting via registered API binding, one call/ledger/shared capacity/proxy, typed source facts and private evidence, no automatic company/person identity. Two real guarded live repo/profile jobs pass. New migration0023 preserves minimal native-ID hashes through erasure/alias suppression/restore. Source namespace separation and newly indexed renamed aliases are covered. SKR-064 done: copied guarded HTTP/feedparser ingestion with20-entry bound, separate original pub/update dates (no compatibility aliases), duplicate/unsafe/omitted markers, no link following or model/lead promotion, private bytes, expiry/erasure, typed API and safe native-details UI. One actual public Python RSS job passes. Final101 backend regressions pass, five opt-in model/container/live cases skipped and separately covered where noted; web92/typecheck/contracts/build and detector pass. 33done/33pending/30planned. Models remainOllama; no Groq request. Current managed process PIDs are in .runtime/sol-services.json; API/worker/retention gracefully restarted for new sources/schema. LinkedIn/Reddit account-backed configuration question asked asynchronously; indexed main-source search remains available.

## Local cache and identity API continuation — 2026-10-14

User deferred direct LinkedIn/Reddit account reads and hosting. Indexed discovery remains available; direct session expiry needs reconnect. Continue Sol Medium without a model switch. SKR-041 public collector cache integration now verified: original dates/zero-charge reuse, expiry, tenant isolation, source disable, serialization cancellation and replay erasure. 48 regressions pass, two live opt-ins skipped; HTTP304/account/hosted gates remain. SKR-049 owner review API reuses the existing resolver: canonical pair/repeat approval/reversal/same-name refusal/owner/member/tenant tests pass in38 related cases. Candidate/native-semantic/UI gates remain. Counts33 done/33 pending/30 planned; partial work is not mislabeled done. No cloud call/account session/user browser read. Current services remain tracked in .runtime/sol-services.json.

Final local checkpoint: cache TTL300 enabled in ignored .env; ordinary tests override to0. Cache job admission takes job locks before the privacy fence, matching erasure lock order. Final31 focused DB regressions pass with one opt-in skip; prior48/38 scoped regressions and contract/typecheck checks passed. Identity responses use private,no-store. Canonical board now records user-deferred account/hosted gates without marking them done. API/worker restarted for final code; readiness HTTP200 and web HTTP200. Process journal remains authoritative. Next eligible local work: saved-list and identity review UI, conservative qualification orchestration, planning clarification/refinement quality; do not mislabel partial API/cache seams as completed tickets.

## Sol qualification/candidate handoff — 2026-10-14

SKR-035 done: copied public URL guards plus conservative native resource identity for LinkedIn activity/UGC posts and Reddit posts/comments; unknown vanity names/query contexts keep URL identity. Actual discovery/erasure/native-alias suppression passes. Counts34 done/32 implemented_pending_verification/30 planned. SKR-050 backend atomic qualifying checkpoint, current fit reevaluation/status-first ranking, explicit ID groups and scoped citation API verified. Existing raw references remain unverified. Citation read denies foreign/unrelated/expired IDs and account-backed sources awaiting scope integration; no raw replay/body access. SKR-096 whole-token/numeric intent grounding corrected with explicit supported plurals; AI planning remains off and Ollama default. 165 backend cases pass with five live skips; additional citation batch26 pass with three live skips.

Disk-full errors affected pytest temp creation, MyPy SQLite cache and TypeScript build-info. Only regenerable project type/lint caches removed; owned .runtime/verify-* temp root used; MyPy --cache-dir=/dev/null avoids large cache writes. User freed space; measured6GiB free. Python .venv was restored by uv to3.12.11 after resume; check/report build and restart owned services before handoff. No private .env/source key contents printed; no account, cloud-model or user-browser operation. Next assigned Luna UI batch:SKR-053 current fit groups/explanations/citation detail and SKR-058 partial/unknown result UX. Sol resumes later semantic/identity/adaptive/security evaluation after visible UI integration; source accounts/hosting remain user-deferred.

Final web verification after user freed disk:100 frontend tests pass; generated API drift, TypeScript (no incremental write) and production Next build pass. Citation backend26 pass/three live skips, full pre-citation backend165 pass/five live skips, seven changed source modules pass cache-disabled MyPy. No new UI component/CSS changed in this batch. Native API/worker must be gracefully restarted for the qualifying/citation changes; keep source/hosted gates deferred. Ready for Luna SKR-053/SKR-058 UI dependency handoff after service readiness.

API/worker gracefully restarted for final qualification/citation code; readiness and web bothHTTP200. Current PIDs in .runtime/sol-services.json; no forced shutdown. Next model handoff is ready for Luna Medium SKR-053/SKR-058.


## Luna results-view checkpoint — 2026-10-14

The user selected GPT-6 Luna Medium. Results UI now renders current confirmed/near-match/excluded/unverified groups, each criterion outcome/reason, scoped saved citations, dates/truncation, unverified hash metadata, unknown criteria and limitations. Preference matches are ordering-only. Citation fetch aborts when switching runs; 404/unavailable evidence is explained. 103 frontend tests pass across 10 files; generated contracts, TS, Next production build, Impeccable detector [] and `git diff --check` pass. SKR-053 remains pending for reviewed-subject identity, conflicting-source and anonymous discussion workflows. SKR-058 remains pending for source reconnect and hosted authenticated-source e2e. Counts34 done/32 pending/30 planned. Next model switch required: GPT-6.1 Sol Medium for SKR-043/SKR-049 integration. Account reads, hosted deployments, cloud-model calls and browser auth checks remain deferred/unused.


## Sol adaptive/identity checkpoint — 2026-10-14

User selected Sol Medium. SKR-043 saved-page runtime now reads optional operator-reviewed exact workspace/URL templates via SKRILLER_REVIEWED_PAGE_TEMPLATES_FILE. It reuses copied validate_field with learn=False; current reviewed fingerprints stay unchanged, version publication remains separate. Retained observations stay unverified. Config/selector/connection mismatch fails closed; private diagnostics are masked from API output. Tests/adaptive now inherits the shared root DB fixture instead of referencing the removed tests/db/conftest.py.

SKR-049 typed native tokens kind:opaque_id refuse bare and wrong-object IDs. All identity support must remain retained/current; active projections recheck links/nonadjacent conflicts, while erasure and suppression use historical approved aliases. Qualifying checkpoint creates bounded idempotent owner suggestions via existing resolver; no auto merge and member jobs keep working. Original claims/history remain intact. Fixtures now use explicit person tokens; no real data backfill or platform ID inference.127 regressions pass with two opt-in skips;47 final checks pass; nine-module cache-disabled MyPy, Ruff, Scrapling provenance and diff pass. API/worker restarted gracefully, journal authoritative; readiness and website HTTP200. Counts34 done/32 pending/30 planned. Next model needed: Luna Medium for owner review controls/conflict display (UI portions049/053). Source object assignment/subject attribution and template publication/deployment remain later Sol/deferred gates. No cloud/account/browser access or new key request.


## Luna identity-review and conflict UI checkpoint — 2026-10-14

Owner review queue wired to the scoped identity review endpoints with loading/empty/error states; approve/reverse UI waits for API confirmation and reports owner-only authorization. Conflicting observations now display all field values and saved excerpts grouped together, with no selected winner. No identity is inferred from candidate IDs. 107 frontend tests passed; contracts, TS, production build and diff passed; Impeccable detector returned []. Updated ticket board keeps SKR-049/SKR-053 pending: decisions still need subject/source context, conflict citations need source/date, anonymous discussions remain open. Next model switch needed: GPT-6.1 Sol Medium for trusted source-object routing and backend evidence context. Direct LinkedIn/Reddit reads and hosting remain user-deferred.


## Sol acceptance closure — 2026-10-14

User selectedSolMedium and requested actual ticket completions. Implemented current identity detail API/source proof/owner permissions, connected queue approval/reversal to result reevaluation, retained exact original claim/source-entity IDs in saved-list payloads and DTOs, routed saved-page persistence through the existing strict validator, added current evidence IDs to observations and source/date citation controls, added LinkedIn/Reddit indexed discussion views with null handle/unknown author, and removed stale current-stage text on completed runs. No matcher/parser/engine rewritten; source-object acquisition stays separate from reviewed proof.

Real isolated Chromium harness builds the shipped component/API client through pinned Vite and uses actual PostgreSQL/FastAPI with a synthetic actor. It confines page requests to loopback, uses a fresh profile, verifies anonymous LinkedIn reference/conflict citations/identity approval and reversal/mobile overflow, and captures desktop/mobile fixture screenshots. No user login session, source account, cloud model or key used. CI now provisions web deps and Chromium for this test; CI itself was not run.

146 backend checks pass with one optional local-model live skip;109 frontend tests, TS, contracts, Next production build, Ruff/cache-disabled MyPy, detector[], diff and service readiness pass. Added snapshot DTO provenance separately passes26 list/API checks and contract/type verification. SKR-047/049/050/053 markeddone after scope/acceptance reconciliation. Counts38done/28pending/30planned. Owned API/worker were gracefully restarted; .runtime/sol-services.json remains authoritative. Latest model handoff is Luna Medium for the SKR-055 ordinary UI/client slice: saving persisted run entities/plan, frozen/latest inspection, expected_revision refresh of current reviewed facts, scoped evidence/omissions/errors. Existing list backend is src/skriller/lists_router.py; generated DTOs include claim_ids/source_entity_ids. External source refresh scheduling belongs080, source account/hosting gates remain user-deferred. Sol remains backend/security owner.


## Luna saved-list closure — 2026-10-14

SKR-055 was completed on Luna. The results view now saves selected run entity IDs and plan IDs into workspace lists, shows latest/frozen immutable revisions, saved values with safely validated source links, and suppressed omissions. Creation uses the API-generated revision 1; refresh submits the visible expected revision and reports persisted-facts-only behavior. Owner/member and stale revision errors remain explicit. No direct platform credentials or hosted source was used. Verification passed:114 frontend tests including new API/UI tests,26 PostgreSQL saved-list/API tests, generated contract check, TypeScript, and Next production build. Status totals are **39 done,27 implemented_pending_verification,30 planned**. Next model switch is needed: **GPT-6.1 Sol Medium** for SKR-056 evidence-grounded follow-ups. Hosted/account-backed source gates remain user-deferred.

## Sol follow-up and refinement checkpoint — 2026-10-14

SKR-056 is done: real queued one-call cited follow-ups, scoped API and result UI, fresh qualification evidence checks on every report read, expiry/erasure redaction, and explicit new bounded research expansion. Focused verification:28 PostgreSQL tests,120 frontend tests, contracts, TypeScript, Next production build, Ruff/MyPy and diff. No cloud or direct platform call. SKR-034 was reconciled as done after45 query/planner/real PostgreSQL workflow tests confirmed capability-aware bounded queries and visible unsupported operators. SKR-057 is in progress: a conservative prompt parser supports explicit company-type exclusions and exact existing must-have relaxation, yielding immutable child revisions with unchanged spend caps; six DB and122 frontend tests pass, including registered discovery on the new revision. Broader model-backed interpretation, clarification exchange and saved-list browser acceptance remain. Canonical board: **41 done,25 implemented_pending_verification,1 in_progress,29 planned**. API/worker restarted for the new endpoints; readiness HTTP200. Luna closed SKR-058. SKR-052 now has a tested authenticated clarification route, worker round trip and UI, but remains pending a real local-model/browser acceptance pass because AI planning is disabled in `.env`. Next switch: Sol Medium for SKR-057 model-backed refinement semantics and evidence reuse. No key is required. User-deferred account-backed reads and hosting stay pending.


## Luna clarification checkpoint — 2026-10-14

SKR-052 remains implemented_pending_verification. The planner now relies on Ollama's constrained JSON schema instead of repeating its 2.2 KB parser instructions, bringing the synthetic ambiguity request inside the 4,096-token budget. Real configured `llama3.2:3b` test passed and returned the person/company location clarification. Related PostgreSQL suite: 28 passed, one optional live-source test skipped; frontend:124 passed; Ruff/MyPy and prior contract/TypeScript/Next build checks pass. Local `.env` enables AI planning with the existing guarded collection proxy; local API/worker readiness is green. Browser localhost access was rejected by a saved user permission, so authenticated visual round-trip remains pending and was not retried through another surface. SKR-058 is done; SKR-057 remains in progress. Board:42 done,24 implemented_pending_verification,1 in_progress,29 planned. Next model switch: GPT-6.1 Sol Medium for SKR-057.

## Sol continuation — 2026-10-15

SKR-039 completed and verified (network-none copied Patchright solver, shared 3-second deadline, persistent challenge rejection, cleanup; actual dynamic collector regression uses reviewed image sha256:9451b865e1acdb9167af41924251384ca0c72c79ef5cd5142b1af7e406bd3d3b). Board43done/25pending/28planned. Root .env reviewed image updated; optional stealth remainsfalse. Native PostgreSQL54439 and RabbitMQ56739 restored after restart; Docker running. Persistent tokenizer asset now under .runtime/tiktoken-cache with pinned digest; missing/tampered asset fails closed offline.

SKR-057 model delta/reuse/clarification backend verified; authenticated browser gate remains blocked by saved localhost permission. Do not bypass via alternate browser/HTTP/Playwright. Current proxy_rotation_finish agent owns SKR-040 proxy files/migration0025/connection schema integration and related tests; root owns ticket/status/allocation docs and planner. Runtime per-task upstream proxy integration is still under test. No model switch/key needed. API8000/web3000/worker/proxy18080 require restart after agent code stable; stale PIDs in .runtime/sol-services.json must not be blindly killed.

Root added opt-in five-case actual local planner semantic corpus; Llama1/5 and best experimental DeepSeek3/5, then1/5. Unproven prompt edits reverted. Server omission guard pauses known missing explicit material constraints and retains private-field warnings.39planner/refinement regressions passed; broad semantic acceptance remains pending. Avoid concurrent model tests: shared capacity correctly admits one local model call; parallel planner regression during live benchmark failed capacity and sequential rerun passed. Hosted and account-backed reads remain user-deferred.

### Final verified Sol batch / next assigned handoff

SKR-040 native HTTP/RSS per-task configured provider path, encrypted proxy-purpose connection, migration0025, sticky authenticated continuity, durable direct binding, numeric public CONNECT, traffic/cost accounting and cancellation-safe gateway cleanup are implemented. Agent final80relatedchecks/Ruff/seven-moduleMyPy/contracts/typecheck pass. Ticket remainspending isolated browser/hosted provider plane, GitHub metadata transport and live provider/account acceptance. Counts43done/26pending/27planned. SKR-048 two actual bounded Llama repair proposals passed; full orchestration/quality remainspending. Tokenizer provisioning25checks, planner/refinement39checks, bootstrap/view/resume19checks passed.

Migration applied; native proxy18080/API8000/web3000/worker/retention restored. Backend /health/ready200: database/broker/workertrue. Journal .runtime/sol-services.json now contains owned new PID references; web child PID differs from parent Next launcher. No localhost browser acceptance attempted under saved restriction. No new key/modelcloudcalls. Next existing allocated batch is LunaMedium SKR-070 stage/cost instrumentation; allocation docs synchronized. Sol remaining scope is not declared finished. Avoid retention expiry-fixture races and concurrent model-capacity tests.


## 2026-10-15 continuation — SKR-070 evidence refresh

Latest SKR-070 code adds typed source failure outcomes, per-attempt UUID correlation, worker queue-wait samples, separately timed LLM observations, and visible per-result network/parser/browser timings. Collection challenge feedback is recorded against its actual typed failure. Tests: 19 backend worker/usage/planning checks passed (1 RabbitMQ case excluded from that run); the actual RabbitMQ checkpoint case separately passed; challenge integration passed; all 124 web tests passed; TypeScript, Ruff, nine-module MyPy, OpenAPI/generated-client checks and diff check passed. Local API readiness: database/broker/worker all healthy. SKR-070 remains pending because unified source-level network/parser/browser aggregation, request/trace IDs beyond attempt correlation, source-health/security verification remain open. User has now selected Sol Medium; next work resumes from Sol-owned P0 pending tickets.


## Sol continuation — 2026-10-15 native GitHub route and adapter closure

SKR-040 native GitHub collection now enters `HTTPFetcher.proxy_for`, the same cancellation-safe configured task gateway as web/RSS. GitHubPublicReader accepts only opaque task credentials on loopback gateways in addition to fixed unauthenticated guarded endpoints; HTTPX TLS verification, fixed API, no redirects/retries/environment proxies remain. Real local HTTPS fixture tests verify provider use, no destination auth leakage, provider failure/no fallback, paid-route refusal under a zero-dollar job cap and reconciled/estimated traffic. 66 source/proxy/fetch regressions pass, 2 live tests skip; Ruff, 3-module MyPy, copied Scrapling provenance and diff check pass. SKR-040 still awaits isolated/hosted control-plane and deferred live-account/provider acceptance.

SKR-045 marked done after reconciling adapter scope against copied graph/pipeline integration already verified and prior actual local Llama fixture. New hostile-page copied-graph + real official SDK transport test confirms synthetic server key only in provider auth header, not model content, results, logs or persisted events; no tools/fallback and one billed call. 47 model/Groq/graph/control tests pass. No real cloud key/model/source calls. Canonical totals44done/25pending/27planned.

Next model switch: Luna Medium for assigned070 unified source-level collection timings, measurement samples and redacted request/attempt correlation/source-health diagnostics using existing event/usage contracts. Sol remaining P0 repair/template publication, semantic end-to-end and security/recovery scopes stay explicit. Do not retry saved-denied localhost browser access through alternate surfaces. Hosted/account gates remain user-deferred.


## 2026-10-15 Luna source-metrics and local benchmark handoff

SKR-070 is done. Unified usage now aggregates collection network/parser/browser durations by source, with explicit sample counts and preserves zero versus missing. Existing source outcomes, attempt correlation, queue wait and separate LLM observations remain; results UI shows denominators and unavailable timings. Security verification injected private HTML and a synthetic secret into stored event details and confirmed the usage response excludes both. Tests: backend usage/collection/GitHub/RSS suites 26 passed, 4 skipped; worker+usage 11 passed; web 124 passed; TypeScript/OpenAPI, Ruff, six-module MyPy, Impeccable detector and diff passed. Detector findings in company.html and changed.html were classified as false positives for scraper HTML fixtures and narrowly suppressed by exact file.

SKR-012 remains implemented_pending_verification. A new reusable copied-ScrapeGraph synthetic benchmark and contract tests were added; local llama3.2:3b scored 4/5 (80%) over five labelled records, missing an explicit Kochi city; median 1.580s and mean 3.881s, with a cold-start outlier. No hosted model/API call was made. Token usage/cost are unavailable; hosted model selection and representative evaluation remain. Local API/worker restarted (new owned PIDs in `.runtime/sol-services.json`); localhost browser/API verification was not attempted under the saved browser restriction. Board:45 done/24 pending/27 planned. User-selected Luna batch has ended; next dependency-ready ticket requires GPT-6.1 Sol Medium for SKR-018 storage/security scope.


## Sol current continuation — 2026-10-15

Active user model Sol Medium. Implemented shared runtime local/S3 storage factory, owner-only S3 ACL grants, safe endpoint/credential settings, bounded SDK timeout/no-retry and client closure, local backup refusal for remote objects, nonblocking regular-file-only local reads and typed naive-expiry refusal. Storage/API/collector/extractor/retention 56 pass/2 skip, S3 SDK plus PostgreSQL reference swap 12 pass, controls/storage integration45pass/1skip. Fixed resume to check current stage configuration/counters: search disabled/exhausted quota no longer blocks saved collection; fetch cap still enforced. Nine-module MyPy/check-untyped-defs and Ruff passed. No real S3/cloud/account call. Tickets018/025 remain pending their deferred live gates. Continuing Sol043 durable reviewed active-template publication; do not request a model switch yet. Services need graceful restart after final code, using owned PIDs in runtime journal.


## Sol completed batch and Luna handoff — 2026-10-15

SKR-043 done after migration0026, owner-only immutable reviewed-template publication, expected-version/concurrent selection, append-only audit, rollback and actual saved-page runtime consumption. Active database mappings supersede the same template ID from a legacy file; unknown source/scope or competing fields fail closed. Versions/audit deny SQL update/delete and member insert under actual RLS. API endpoints /v1/workspaces/{workspace_id}/page-templates (GET/POST) and /{template_id}/rollback (POST) are private/no-store. No model proposal auto-publishes; SKR-048 orchestration/quality remains open.

Latest integrated verification95passed/2optional skips covers template registry/API, adaptive, saved-page, collection, resume, storage/config/S3 SDK, retention and API bootstrap. Twelve-module MyPy --check-untyped-defs, Ruff, TypeScript/OpenAPI generated contract and diff checks passed. Frozen migration compiled for PostgreSQL. API, worker and retention were gracefully restarted with verified owned PIDs and remain running; runtime journal updated. No denied localhost browser/user-page HTTP check or live S3/cloud/account call was made.

Board46done/23pending/27planned. Next model switch requested: Luna Medium for assigned SKR-066 small page-specific presets through verified interfaces. Reuse existing copied extractor and observation/evidence validator; preserve unknown/current-contact/subject semantics. SKR-018 remains pending real private S3 deployment, SKR-025 remains pending direct-account rebinding/hosted acceptance. Those gates remain user-deferred and require no key for the next local preset work. Sol still has remaining ownership/review/repair and security tasks; it is not declared globally finished.


## Luna completed batch and Sol handoff — 2026-10-15

SKR-066 is done. Added deterministic public URL-path routing to the existing company/team/careers/services/contact/directory presets and literal `job_posted_date` support. The saved-page workflow remains on shared model budgets, scoped evidence, exact quote validation and unverified claim states. Integration tests cover company, team and careers pages, including date extraction and rejection of unsupported fields; the changed-markup reviewed-template recovery path remains tested. Verification: 35 passed, 1 skipped (optional live Ollama), Ruff and MyPy passed; `git diff --check` passed. Board is 47 done / 22 implemented_pending_verification / 27 planned. Next assigned task requires GPT-6.1 Sol Medium: SKR-096 planner integration. Luna tickets SKR-011, SKR-012, SKR-052 and SKR-065 still require provider/hosted model/browser permission/isolated runner evidence respectively; no API key is needed for SKR-096.


## Sol platform-reference batch and Luna handoff — 2026-10-15

SKR-096 now pauses omitted explicit platform selection and rejects mismatched/unmarked numeric comparison operators. Eleven parameter cases and actual PG bootstrap replay prove no discovery after dropped LinkedIn intent, one metered model call, immutable paused plans. Model quality/browser gates remain open; not done.

SKR-059/061 moved planned -> in_progress: new connectors/platform_references.py directly calls copied Agent-Reach LinkedIn/Reddit can_handle plus existing native_reference. Results derive a typed PlatformReference with source/resource_kind, exa_keyless, indexed_reference_only, direct_read_status=not_attempted and subject_identity=unknown. No source credential/account read or public-to-private access inference. OpenAPI/client regenerated. 83 tests pass/2 optional skip; actual RabbitMQ delivery separately1pass; runtime retries2pass (fixed missing dispatch isolation in those tests). Four-module MyPy, Ruff, TypeScript/contracts and diff checks pass. Combined broker timeout did not recur isolated; native broker ping passes.

API/worker gracefully restarted using verified owned journal PIDs (proxy/web/retention untouched). No denied browser/user-page access, cloud model, API key or direct source read. Board47done/22pending/25planned/2in_progress. Next Luna Medium SKR-059/061 UI slice: results currently receive platform_reference but must visibly show access/resource/identity distinctions with focused web tests. Keep full tickets in progress; acquired backend filter/cursor/account/live acceptance remains deferred and requires Sol review when resumed. Read apps/web/AGENTS.md and apply Impeccable for UI work. No user API key/manual testing needed.


## Luna completed indexed-reference UX handoff — 2026-10-15

Added accessible result callouts for LinkedIn/Reddit indexed profile, company, post, comment and community references. Copy clearly says direct read not attempted and identity unverified; posts/comments also say the author is unknown. Discussion notice does not duplicate the platform-reference notice. Runtime results API validation enforces the exact source/resource/access/direct-read/identity contract. Tests: 127 frontend/API tests across15 files; TypeScript/contracts/Prettier/diff passed, detector no findings. No browser session loaded.

SKR-059/061 remain in_progress: direct source backend/filter/cursor integration and live coverage remain. Board47done/22pending/25planned/2in_progress. Next Sol batch SKR-096 semantic acceptance and unfinished SKR-059/061 backend work. No API key/manual browser test is required to continue local engineering; user-deferred account/live validation remains explicit.


## Sol copied source discovery contracts and Luna benchmark handoff — 2026-10-15

Added `connectors/reddit_discovery.py` and `linkedin_discovery.py` with strict bounded request/result models. Reused pinned source code in `src/skriller/_vendor`: Reddit models/parser exact bytes; LinkedIn reference normalizer exact and URL grammar one relative exception-import adaptation plus exact exception class. Provenance, modification logs, source hash tests and LinkedIn LICENSE/NOTICE retained. Reddit upstream has declared Apache-2.0 but no separate license file in acquired snapshot; recorded without inventing one. Vendored source excluded from first-party Ruff/MyPy paths, retained full external snapshots unchanged.

Reddit requests preserve query/subreddit/sort/time/cursor/limit; response validates Listing/t3/native ID/permalink/community before copied parsing; missing/future dates stay unknown, deleted content unavailable, handle identity unknown, duplicates/omissions explicit. LinkedIn grammar validates numeric company/network and operation-specific filters, posts cap1page; returned URL must preserve query/filter; copied normalized references remain unaligned, no person-post relation inferred; errors expose section names only. Both existing explicit opt-in probes now use runtime contracts. Ignored filters/malformed references prevent verified readiness. Tests52passed/2account-live skipped; Ruff/four-module MyPy/diff pass. No real source/account/cloud call, credential import, production job/budget change or browser access. Services need no restart: new adapters/probe code is not yet connected to running worker stages. SKR-059/061 remain in_progress with tenant-owned isolated execution/credential rebinding/budget/evidence and live verification remaining; board47done/22pending/25planned/2in_progress.

Next Luna Medium SKR-012 measurement-only batch: existing `scripts/probes/model_trial.py` creates local ChatOllama+copied SmartScraperGraph and reports quality/time but not tokens; model_benchmark.py assumes calls=corpus size and usage/cost=null. Add callback capture of actual provider starts/ends and reported usage, preserve null where not reported, aggregate independent counters without token guessing; keep current fixture quality checks/private-contact failure. Use local synthetic Ollama only (authorized), no hosted/Groq/Gemini API call and no model prompt tuning. SKR-012 remains pending hosted-pilot selection/representative quality even after measurement improvements. No key or manual testing needed for that batch.

## Luna local benchmark instrumentation and Sol handoff — 2026-10-15

SKR-012 instrumentation implemented. `TrialUsageCallback` attached to local ChatOllama records observed model starts/ends/errors and only valid token usage returned by callbacks; no text-based token estimate is used. Aggregate benchmark counts reflect callback facts rather than record count, and token-usage coverage reports missing/unknown observations. Refreshed synthetic five-record `llama3.2:3b` benchmark: 4/5 factual records (80%), 5 calls observed, 3,067 input + 222 output = 3,289 tokens, 1.606s mean / 1.608s median. Tests: 7 passed; Ruff and format checks pass; no API calls. Ticket remains implemented_pending_verification for hosted pilot selection/data terms and representative-scale evaluation. Next ticket SKR-065 crosses isolated worker image/runtime and result persistence boundaries; next model switch needed is GPT-6.1 Sol Medium. User's previously deferred hosted deployment and direct LI/Reddit account tests remain pending; no keys needed for the next local review.

## Sol installed YouTube worker/job integration and Luna handoff — 2026-10-15

SKR-065 local backend implementation is now present: hash-checked lockfile wheels, immutable `Dockerfile.youtube` over the existing pinned browser base, yt-dlp 2026.8.19 plus its default closure, and reuse of Playwright's Node v24.21.0. `scripts.provision_youtube_assets` reuses the cleanup wheel provisioner with universal/stable-ABI support. `youtube_worker.py` uses the installed upstream extractor and provided English VTT only, redacts signed caption URLs, preserves metadata on caption failure, caps 12 HTTP attempts including redirects using the pinned urllib handler, and runs through `ConcreteYouTubeExecutor` and the existing guarded runner. No audio/transcription/cloud model/session credentials. The copied Agent-Reach doctor is actually called in the image fixture and returns warn (it looks for a config file, while this worker passes Node options explicitly).

`youtube_collection.py` is routed by optional trusted `youtube_reader` through `collection.py`; `research/runtime.py` constructs it only when `SKRILLER_PUBLIC_YOUTUBE_IMAGE` is configured. Settings requires a guarded proxy and immutable image; `.env.example` documents it and tests clear the environment opt-in. The real local `.env` remains unset for YouTube. Stage reserves 12 attempts before dispatch, reconciles observed transport attempts, charges unknown failures as estimated through the shared worker, and handles source switch/cancellation/replay/privacy. It stores scoped metadata/caption citations (max 20 previews, omissions explicit), uses timestamped source links, rejects creator identity/lead promotion for video resources, and hides expired previews. Router and generated OpenAPI/TS schema expose `youtube` metadata/caption fields; manual API client and results UI are the next Luna task.

Verification: combined YouTube/provisioning/real PostgreSQL YT+GitHub+RSS+web selection 54 passed, 4 opt-in browser/live checks skipped; new settings guard 1 passed; actual installed-image fixture 1 passed under network none, non-root/zero caps, exact caption/source timing, copied runtime check, cleanup confirmed. Ruff, MyPy (12 modules), schema drift and TypeScript pass. Image `sha256:63f4ec7c6a1585eb51ddaa853edb426da20395c042328e7130e57df955e1cc21`. One final-image public video attempt returned backend failure after 6.044s, so live metadata/captions remain unverified. Evidence: docs/completions/SKR-065.md and YOUTUBE-WORKER-LOCAL.json. Keep SKR-065 implemented_pending_verification; remaining UI and representative live source gates. Board 47 done / 22 pending / 2 in progress / 25 planned.

Next Luna Medium SKR-065: optional YouTube checkbox in existing source chooser; API candidate runtime/type validation for optional/null youtube view; results metadata counters marked public, caption states accurate (English VTT only, no generated replacement), unknown creator identity and video-resource status; scoped citation fetch for segments with cue times and timestamp links; expiry hides data. Use existing design, read apps/web/AGENTS.md and Impeccable, fixture/DOM tests only under saved browser restriction. No key/manual user test. Backend/source budget changes return to Sol. This handoff does not declare all Sol tickets complete. User-deferred hosted and LI/Reddit direct-account gates persist.

## Luna SKR-065 UI completion — 2026-10-16

Added optional YouTube source selection, strict runtime validation for the optional typed `youtube` result, and a source-specific result view for public counters, observed/published dates, caption state/origin/language, timestamped cue links and scoped evidence citations. Expired metadata and caption text are hidden; caption previews are never presented as generated by Skriller. Legacy results without a `youtube` property remain accepted.

Verification: web suite 134 passed; TypeScript and generated-contract checks passed; Impeccable detector returned no findings. SKR-065 stays implemented_pending_verification because the final immutable worker image returned a backend failure on its representative public-video read. No key or user test is required for the UI work. Next switch: Sol to diagnose the worker read and complete source acceptance.

Local service recovery during this batch: Docker Desktop had stopped, leaving the existing RabbitMQ container down. Docker and only the project's RabbitMQ/guarded-proxy services were restored; the native PostgreSQL process and unrelated containers were not changed. RabbitMQ diagnostics ping passed. API and worker were gracefully restarted only after exact owned-command checks; current PIDs are in `.runtime/sol-services.json` (API 21420, worker updated after broker readiness). API port 8000 and the existing guarded proxy remain available. No user-authenticated browser/API page was accessed.

## Sol installed-source and runner acceptance — 2026-10-16

Closed SKR-065 and SKR-028. Board:49 done /20 pending verification /2 in progress /25 planned. The old BaW_jenozKc sample was actually unavailable, confirmed by a redacted diagnostic; no transport bypass or retry policy change was needed. The same immutable image read public jNQXAC9IVRw with six provided English cues and four HTTP attempts. A new opt-in PostgreSQL job acceptance test verifies storage, counters, source timestamp and scoped citation, retaining unknown creator identity and excluded person-lead fit. Scalar proof: docs/completions/YOUTUBE-COLLECTION-LIVE.json. The ignored root .env now enables SKRILLER_PUBLIC_YOUTUBE_IMAGE with sha256:63f4ec7c6a1585eb51ddaa853edb426da20395c042328e7130e57df955e1cc21. Docker project proxy/broker were restored without starting compose Postgres or touching unrelated containers. Owned API/worker were restarted; current PIDs are in .runtime/sol-services.json.

Added configured/unconfigured public YouTube diagnostics (experimental/unavailable), without promoting this sample to another tenant's live verification or invoking Docker during diagnostics. Fixed the API client's rejection of retrieved-caption history when all preview cues expire or are omitted; two regressions pass. Full web suite136, TypeScript and generated OpenAPI/client drift pass. Related diagnostics/worker/PostgreSQL suite28 passed/1 optional live skip; actual public job separately passed. Shared installed-image security/browser/YouTube selection38 passed with two CLI-message-case test false negatives; corrected case-insensitive missing-object assertions, then both actual cancellation tests passed. Only test assertion casing changed, no cleanup policy weakened. Ruff/checked-body MyPy and diff checks pass.

SKR-028 fixed-command/environment/filesystem/process scope is now complete with actual installed runtimes, including public Chromium, JS/private-XHR interception, host-file/socket exclusion, zero capabilities and timed descendant removal/capacity release. Account credential delivery remains029/030 and full hosted/all-collector egress remains027/036/074. No claim that these other tickets are done. Prior fixture design question needs no user action: existing narrow flat-type ignores already identify company.html/changed.html as intentional extraction fixtures; no fixture redesign or new suppression was made.

Next Luna Medium SKR-011: measurement-only harness over existing ExaKeylessSearch, fixed public/synthetic corpus and controlled tests. Capture actual search method call counts (not invented network counts), latency, accepted/rejected/truncated hits, exact canonical known-public-URL matches and actual pagination support (currently false). Bound optional public live trial to at most four queries and five results each; no source account, paid service, cloud model, raw snippet retention, model/prompt tuning, provider/budget changes or localhost app access. Domain filtering is output post-filtering, not operator-semantics proof. Existing commercial SaaS/storage rights remain unknown until explicit provider evidence; SKR-011 stays pending while that gate is open. Next model ownership change is Luna; Sol's remaining source/security work is not declared globally complete.


## 2026-10-16 Luna handoff

SKR-011: added `scripts/probes/search_coverage.py`, tests in `tests/probes/test_search_coverage.py`, and scalar live evidence `docs/completions/EXA-COVERAGE.json`. Three public queries made 3 logical adapter calls in 14.624s, returning 15 accepted/0 rejected hits with one truncation. Operator semantics/pagination remain unknown; duplicate rate cannot be observed after adapter deduplication; expected URL labels are absent; commercial storage/use rights remain unverified. Status is still `implemented_pending_verification`. Local test set passed 17, Ruff/MyPy passed. The next eligible model handoff is **GPT-6.1 Sol, Medium**, for SKR-018 private evidence storage. SKR-012 remains pending hosted/representative benchmark evidence; SKR-052 remains pending its saved-browser localhost acceptance gate.


## Grouped Sol completion — 2026-10-16

SKR-029 and SKR-051 now **done**. Canonical board51done/18implemented_pending_verification/2in_progress/25planned. SKR-018 was audited: only user-deferred live private S3 deployment remains; no new source work was invented. Credential implementation: RunnerSecrets.credential_ref identifies the exact encrypted generation; ConnectionStore.runner_current polls authority without redecrypting/audit spam; run_connected fences before/during/after trusted runner execution. Revoke/reconnect/expiry rejects late output. IsolatedRunner delivers only matching allowlisted material via a 0600 file in a 0700 temp directory, readonly fixed-path mount, no argv/env values, log-driver none, redacted stdout and no raw backend stderr. Actual installed image sha256:63f4ec7c6a1585eb51ddaa853edb426da20395c042328e7130e57df955e1cc21 passed 2 credential delivery/revocation/cleanup cases. Fixed fixture command only, no actual LinkedIn/Reddit operation or account. Existing production operation allowlisting is unchanged; source adapters still own budgets/capacity/evidence persistence. Reddit cookie and OAuth fields now remain explicitly distinct. SKR-030 active invalidation seam is closed; checkpoint rebind/account acceptance remains pending.

Role review: new owner-only POST /v1/workspaces/{workspace_id}/role-refreshes/preview and /role-refreshes. Saved original person role/date/evidence IDs only; no replacement values accepted. Preview hash and explicit same-subject confirmation required; current literal/date/source/expiry checks repeat under privacy/entity locks. Migration0027 adds immutable audit review_hash. Old claims remain, approval is idempotent. Third unresolved role conflict now prevents any current-role projection; expiry remains unknown. Full native-source production/refresh remains in060/062/074/080. Final regressions66passed + separate exports/list/evidence34passed + installed credential2passed; broader earlier storage/control/role/erasure120passed. Ruff/6-module checked-body MyPy/generated OpenAPI and client drift/TypeScript/diff passed. No user app/browser/auth token, real source key, paid service or model was used. API/worker exact owned commands were restarted; current PID file .runtime/sol-services.json (API76103,worker76238).

Next switch **GPT-6 Luna Medium**, group SKR-075/SKR-079 local preparatory work before another model handoff. Prepare a bounded fixture benchmark using copied parsers/collection paths and existing scalar stage measurements. Record actual p50/p95 with sample counts, observed call/attempt/byte counts, elapsed time and available memory measurements with hardware/cache state; missing metrics stay unknown. Never turn parser speed into a product SLA or substitute fixture full-job timing for hosted acceptance. No provider/model calls, user localhost browser, source credentials, concurrency changes or broad repeat suites. Add deterministic measurement/aggregation tests. Prepare operator runbook based on actual current commands/configurations, privacy cleanup/backup/health/reconnect boundaries and explicit user-deferred hosted/account/pilot gates. Both full075 and079 remain pending their own unfulfilled hosted/pilot dependencies; do not manufacture successful customer trials. Larger grouped batch is requested to reduce model switching.


## Luna grouped SKR-075/SKR-079 checkpoint — 2026-10-16

Implemented and verified local work for both tickets in one batch. SKR-075 adds `scripts/probes/local_job_benchmark.py`, reusing copied Scrapling/Agent-Reach classification and Skriller cleanup over five fixtures. Five repetitions recorded 25 cases: classification p50/p95 0.187/0.273 ms; cleanup 4.653/7.435 ms over 10 readable samples; fixture-case time 0.328/7.145 ms; 7,870 bytes read; Python traced allocation peak 8,566,578 bytes. Process peak RSS is cumulative, not attributable. All classifier outcomes are explicitly labeled; empty/challenge/JS-shell fixtures are not called live access failures. No network/model/browser calls or concurrency changes. `tests/probes/test_local_job_benchmark.py`: 5 passed; Ruff, format, MyPy, diff checks passed. Evidence: `docs/completions/SKR-075-LOCAL.json` and `docs/completions/SKR-075.md`. SKR-079 adds `docs/SUPPORT_AND_PILOT_RUNBOOK.md` verified against actual routes, startup code, switches, and recovery docs. It makes no customer pilot claims; hosted, direct LI/Reddit account reads and repeated three-workspace value evidence remain pending. Both statuses are `implemented_pending_verification`; canonical board is 51 done /20 pending /2 in progress /23 planned. Next selected model: **GPT-6.1 Sol Medium**, grouped local acceptance work SKR-077/SKR-078. No key or user testing is needed for this next local review.


## Grouped Sol SKR-077/SKR-078 local acceptance — 2026-10-16

Canonical board:51 done/22 implemented_pending_verification/2 in_progress/21 planned. Both077/078 have local fixes and evidence; hosted/external-account gates remain pending. Worker finalization now catches post-provider checkpoint errors after rollback, preserves confirmed actual usage (or estimated ceiling for malformed accounting), marks owned attempts failed, pauses without leaking source errors, emits checkpoint_failed plus zero-result schema_invalid stage metric, and refuses blind replay. If commit succeeded but acknowledgment was lost, only the matching generation/lease owner existing checkpoint is returned. tests/db/test_release_recovery.py covers writer error, SQL abort, foreign tenant entity, malformed usage, duplicate+cancel race, actual child kill in an open DB result transaction and commit-ack ambiguity. Old uncommitted reply is unavailable; first-call estimate plus new-call confirmed usage remain distinct. Model data boundary rejects AIMessage tool_calls/invalid_tool_calls and legacy additional_kwargs function/tool requests before parsing facts, retaining known token usage. tests/db/test_release_security.py sends these attacks through copied saved-content node, no autonomous fetch/tool/secret capture. Removed an existing duplicate unreachable model exception branch.

Shared resume preflight now returns advisory resume_status from jobs/control.py; results API exposes default-compatible enum available/new_prompt_required/deadline_expired/requires_reconciliation/budget_exhausted/not_paused. Resume recomputes same preflight under job lock. Results include a safe checkpoint_failed limitation; no new action permissions. Generated apps/web/contracts/openapi.json and generated/api.ts updated; manual client/UI intentionally awaits Luna. Groups overlap:52 initial passed;148 grouped tenant/storage/export/controls/egress/recovery passed; final15 resume+fault passed. Source-orchestration selection80 passed/3 opt-in skipped with one new test fixture dimension error corrected and verified in final15. Ruff/format7files, checked-body MyPy4sourcefiles, TypeScript, generated contracts pass. Direct database/broker/worker_consumer true. Owned exact-command API/worker restarted; .runtime/sol-services.json now api7152,worker7153. Other services/env/images unchanged. No user app/browser/token, actual source account/model call or hosted operations. Reports docs/completions/SKR-077.md and SKR-078.md;025 evidence updated without changing its pending status.

Luna's focused SKR-078 frontend recovery subtask is complete (see the latest checkpoint below). Backend/security ownership returns to Sol; the ticket remains pending for hosted/account-backed acceptance.


## Luna SKR-078 resume-state UI — 2026-10-16

`apps/web/src/lib/api.ts` accepts legacy results without `resume_status`, validates the supported enum when present, and rejects unknown values. `apps/web/src/components/research-results.tsx` explains reconciliation, expired deadline, exhausted budget, corrected prompt and unknown readiness. Only explicit `available` shows Resume; all states preserve saved results and expose Check run again. A stale backend 409 continues through the existing visible error/retry behavior. No source/model calls or user browser/auth session were used.

Verification: `corepack pnpm exec vitest run tests/api.test.ts tests/results.test.tsx` passed 85 tests; `corepack pnpm typecheck` passed; `corepack pnpm contracts:check` passed; Impeccable detector returned no findings. SKR-078 remains implemented_pending_verification because account-backed SKR-068 and hosted SKR-074 acceptance remain deferred. Board remains 51 done / 22 pending / 2 in progress / 21 planned. Next selected model: **GPT-6.1 Sol, Medium**.


## Grouped Sol cache/repair/evaluation checkpoint — 2026-10-16

Implemented two backend gaps in one batch. SKR-041: guarded public HTTP conditional fetch in the second half of the original fresh TTL, scoped validators/body identity, unchanged200body reuse after304, separate validation timestamp, original collection date/expiry, normal fetch accounting and fail-closed wrong/unbound/late304. Copied fetch/cache engines unchanged. Authenticated-source cache policy and user-deferred hosted/privateS3 acceptance remain open.

SKR-048: migration0028 adds dedicated template_repair job purpose. Existing ID-only outbox/scheduler and bounded checkpoint worker now route owner-requested repairs over saved exact-source public-web evidence. One localmodelcall,1field,currentHTML<=2048bytes,<=8regressions of2MiB,8192tokens/120seconds. Actual copied answer node/parser/selector/fingerprints remain in use. Proposal storage is separate from candidate results/exports. OwnerAPI under /v1/workspaces/{workspace_id}/page-templates creates/retrieves requests and explicitly approves a reviewed proposal after source/hash/expiry/active-version rechecks; existing publication audit/rollback applies. No model or page content can activate a template. Runtime dispatch, duplicate delivery, accounting, owner scope, private responses, unsafe/wrong-neighbor/expired/deleted/tampered source, cancellation and stale approval tests pass. Source/body-expiry preservation test also passes. Generated API contracts updated; no frontend UI changed.

Verification groups overlap: initial HTTP/cache/collector45passed/1live skip; repair-related75passed/2opt-in skipped; final changed-code54passed/1opt-in skipped; final worker/cache26passed before report-format-only updates. Ruff/format17files, nine-module checked-body MyPy, TypeScript and generated contract drift pass. Do not repeat broad passing suites without a changed concern. Normal tests use controlled models/loopback only. User browser/app/auth session were not inspected.

Added fixed tests/fixtures/repair/quality.json:20changed pages and4adversarial. Actual local Ollama llama3.2:3b benchmark initially14/20targets,4missing,2strict target mismatches,4/4adversarial rejections; one bounded stable-selector prompt clarification produced14/20,5missing,1strict target mismatch,4/4adversarial rejections,24metered calls/9559tokens/27.589seconds. Both opt-in benchmark invocations FAILED their90%gate; preserve that fact. Exact labelled nodepath+literal metric conservatively counts equivalent nested nodes as target mismatches, not fabricated lead fields. Both scalar reports retained. No external source/cloud/key was used. Do not silently change labels or thresholds or rerun until a material quality change justifies it.

SKR-076 is now in_progress for this first labelled evaluation implementation. Board51done/22pending/3in_progress/20planned. SKR-041/048 remain pending; no unverified Done increment. Reports docs/completions/SKR-041.md, SKR-048.md, SKR-076.md and REPAIR-QUALITY-LOCAL{,-INITIAL}.json. Next selected model **GPT-6 Luna Medium** for076measurement-only reporting support: strict bounded corpus/report format validation and aggregation across field/qualification/identity/repair, per-source denominators and explicit unmeasured groups, retaining all missing/rejected/unknown cases. Reuse scalar evidence and ordinary deterministic fixtures. No source/model calls, user browser/session, credentials, acceptance/ground-truth changes, classifier/qualification/model/authorization edits. Sol retains076ownership and model/semantic remediation. Keep076in_progress until remaining implementation/acceptance is actually complete. No API key or user test is needed for that Luna subtask.

Owned API/worker reloaded after this batch (API 14109, worker 14110); direct database, broker and queue-consumer checks passed. Proxy, retention, web, env and installed images were left in place. No HTTP request to the user app/API or user auth session was made.

## Luna SKR-076 reporting support handoff — 2026-10-16

Implemented `scripts/quality_reports.py` and `docs/QUALITY_REPORT_SCHEMA.md`. The bounded validator checks existing extraction and repair case rows against declared counts, accuracy, and repair gate thresholds; it accepts a common versioned labelled-case format for field extraction, qualification, identity and repair. Aggregation stores report hashes and per-run/per-source denominators without pooling repeated trials. Missing qualification/identity groups are explicitly `unmeasured`; unknown/not-executed common cases stay in denominators and count as non-correct. Unreported sources are not mapped to platforms.

Current `docs/completions/QUALITY-AGGREGATE-LOCAL.json`: synthetic field extraction 4/5; repair has two separate 24-case runs (20 positive cases each), both 14/20 (70%) and gate failed; qualification and identity unmeasured. Reporting tests7passed; Ruff/format, checked-body MyPy, aggregate generation, diff check passed. No model/source/browser/credential call. Ticket remains in_progress because quality semantics and representative acceptance remain open. Next model **GPT-6.1 Sol Medium** for failed repair/semantic quality remediation; do not alter labels or thresholds.

## Sol grouped repair and semantic quality completion — 2026-10-16

SKR-048 is now done. Added bounded source-attribute CSS enum generation via the copied Selector DOM, with unchanged semantic/current/regression validation and explicit refusal of a wider attributed wrapper containing a valid attributed inner field. No gold selectors supplied to actual model. The enum-only intermediate measured19/20 with1wrong target and failed; saved as REPAIR-QUALITY-LOCAL-ENUM.json. The preceding70%stable-guidance report is retained as REPAIR-QUALITY-LOCAL-STABLE-ATTRIBUTES.json. Final unchanged corpus actual local Llama run passed19/20 exact targets (95%),1missing,0silent wrong matches,4/4adversarial rejections,24metered calls/9770tokens/29.278seconds. REPAIR-QUALITY-LOCAL.json has actual code/corpus hashes. A separate actual local-model durable job passed explicit owner review/activation and rollback1→2→1 with one model call; REPAIR-REVIEW-LOCAL.json. PRD FR-06 requires20changed fixtures90%, now met. Broader platform/pilot quality belongs076; deployment belongs074, rather than an extra invented048scope.

SKR-076 local evaluation now includes tests/fixtures/research/semantic-quality.json and actual tenant database tests/db/test_semantic_quality_corpus.py.24qualification exact statuses passed, with6/6accepted precision;21identity exact decisions passed, with6/6eligible precision. All near matches, unknown criteria and negatives remain visible. Seeded reviewed facts are explicit; no source/model extraction quality implied. The21-case identity corpus first found future-dated native observations eligible:20/21,6/7precision; saved IDENTITY-QUALITY-FUTURE-FAILURE.json. Fixed production qualification/identity.py to reject future-collected evidence; same corpus then21/21. SKR-049 staysdone with this regression corrected. QUALIFICATION-QUALITY-LOCAL.json and IDENTITY-QUALITY-LOCAL.json record actual local DB outcomes/corpus+implementation hashes.

Hardened scripts/quality_reports.py:32reports/2MiB/1000cases bounds, accepts failed adversarial silent_wrong reports rather than dropping them, retains per-run/source denominators, negative/accepted denominators and precision, and labels measurement origin as supplied reports (no attestation by aggregator). Expanded aggregate contains prior failures plus current measurements; no pooled duplicate sample size. Field extraction diagnostic remains4/5, and representative200-record field/contact and50-prompt model/source acceptance remains open, so076stillin_progress. Docs/completions and canonical status synced. Board52done/21pending/3in_progress/20planned.

Final related repair/workflow/semantic/identity/API/qualification/report suite78passed/1optional local-model case skipped; that owner-review case separately passed with actual local Ollama. Actual24-case local model corpus separately passed. Ruff/format8files, checked-body MyPy3source modules, aggregate generation and diff checks passed. Existing lxml strip_cdata warnings unchanged. No cloud/source/account request or user browser/app/auth session. No env/image change. Verified owned commands and zero unexpired active attempts before graceful API/worker reload; journal nowAPI36188/worker36189. Proxy/web/retention unchanged; direct readiness checks recorded separately.

Next assigned model GPT-6 Luna Medium: SKR-087 local saved-page job/pricing/industry-directory preset extension only. Reuse extraction/presets.py and copied saved-content graph/tests. Preserve literal currencies/amounts, billing periods, publication dates and availability; localized prices remain literal where normalization unsupported; expired/closed jobs never imply current hiring. Source-specific unverified drafts only, no new collector/model adapter, contacts inference or qualification promotion. Ordinary controlled graph/DOM fixtures and established real-DB accounting; no source/model/browser/session calls. Keep deferred pilot/source gates explicit. No API key/user test is needed. Sol retains remaining backend/security/semantic work; not globally complete.

## Luna SKR-087 job/pricing/industry preset completion — 2026-10-16

SKR-087 is **done**. Existing saved-page graph now supports `jobs`, `pricing`, and `industry_directory`, retaining `careers` and `directory`. Price, currency, billing period, effective date and availability are distinct literal claims; prompt guidance prohibits normalization or inferred availability. An expired/closed/filled/non-accepting job source rejects model claims that the listing is open/current/active/hiring. Claims remain source-specific and unverified. No new scraper engine, source call, model provider or browser/session access was introduced.

Verification: `uv run pytest -q tests/extraction/test_presets.py tests/db/test_directory_presets.py` — 9 passed, including monthly/annual/localized prices and a real PostgreSQL/shared-ledger controlled-model expired-job test; Ruff and MyPy passed for changed files. Report: `docs/completions/SKR-087.md`. Board: 53 done / 21 implemented_pending_verification / 3 in_progress / 19 planned.

Next required switch: **GPT-6.1 Sol Medium** for local SKR-089 webhook endpoint safety, signing, idempotency, and bounded retry/ledger acceptance. Hosted endpoint delivery remains pending; no API key is needed for local implementation.

## Grouped Sol SKR-080/SKR-089 completion — 2026-10-16

Both tickets are **done** against their listed backend acceptance checks. Canonical board: **55 done / 21 implemented_pending_verification / 3 in_progress / 17 planned**. Reports: `docs/completions/SKR-080.md`, `docs/completions/SKR-089.md`; operator commands and boundaries: `docs/AUTOMATION_RUNBOOK.md`. Hosted/account/customer release gates remain pending under their existing tickets; no external webhook receiver or source/model provider was contacted.

SKR-089: new owner-only `/v1/workspaces/{workspace_id}/webhooks` configuration/history/revoke routes. One-time signing secret uses existing AES keyring and endpoint/workspace-bound AAD. Saved-list snapshot transactions enqueue fixed metadata-only events for opted-in endpoints, unique per endpoint/snapshot. Stable event ID/body and timestamped HMAC-SHA256 signature; committed attempt/lease before I/O, five attempts maximum, bounded retry and redacted history. Copied-derived URL/DNS policy and pinned socket helper reused; original-hostname TLS and no redirect/environment proxy. Explicit `python -m skriller.webhooks.runtime` worker executes each send in an existing-helper bounded child (20 seconds, 4096-byte stdout/stderr cap, opaque task IDs only); crash uncertainty remains at-least-once and requires receiver deduplication. Revoke/erasure/restore clears encrypted signing material. No worker was enabled automatically.

SKR-080: owner-only `/v1/workspaces/{workspace_id}/research-schedules` create/list/disable/resume/history routes. One schedule/list, ten/workspace, cadence1–720hours,1–25runs; explicit opt-in. Durable60-second due lease, atomic occurrence/job/outbox/admission and next-due advance; missed intervals coalesce, no overlapping unfinished run or allowance reset. Reuses actual existing research worker/cache/budgets/source switches. Required source refs are current metadata dependency fences, not new credential injection/rebinding. Before-I/O gate rejects revoked/expired dependency, disabled schedule or demoted owner; persisted scoped jobs.schedule_id prevents RLS hiding a schedule from bypassing this gate. Schedule pins immutable original user message at saved plan creation, so later follow-ups cannot silently change objective. Actual controlled source execution through checkpoint worker finished normally with one admission and old objective. Results are separate reviewable research jobs; saved lists remain immutable.

Migrations0029–0033 applied locally for endpoint/delivery tables, scheduler/occurrence tables, scoped job schedule provenance, journal-protected delivery erasure and immutable prompt binding. Erasure quarantines automations before deleting snapshot derivatives; actual offline restore test proves restored opt-ins/schedules are disabled, pending delivery cancelled, ciphertext removed and old active jobs cancelled. New focused suite34passed. Related research/quota/erasure/actual-backup-restore/OpenAPI37passed; preceding overlapping worker/recovery/list/connection/egress84passed. Ruff/format32files, checked-body MyPy17source modules, generated OpenAPI and TypeScript/client drift checks passed. Existing lxml strip_cdata warnings unchanged. No user browser/app/auth session or key was inspected.

After zero unexpired running attempts and exact command identity checks, gracefully reloaded only owned API/worker; journal `.runtime/sol-services.json` now API55612/worker55613. Proxy/web/retention unchanged. New scheduler/webhook workers remain off until explicitly configured/started. Direct readiness: database/broker/worker_consumer passed. No API key or manual user test is needed for this completed group.

Next assigned switch: **GPT-6 Luna Medium**, SKR-081 local meaningful-change reporting support. Compare immutable saved snapshot values using existing claim/evidence provenance; observation-date-only changes do not count as meaningful changes, and no opt-in means no external delivery. Unknown/conflicting/unverified/expired data must stay explicit; do not infer current role/hiring or upgrade contacts, fit, identity or claims. Reuse existing reporting utilities; controlled fixtures and local report/UI work only. Do not call sources/models/receivers or inspect the user browser. Sol retains security/evidence-acceptance ownership if an architectural boundary becomes necessary. Allocation JSON/MD updated; this is not global product completion.

## Sol completion of SKR-081 — 2026-10-16

SKR-081 is **done** for local acceptance. Added a deterministic saved-snapshot comparator and authenticated `/v1/workspaces/{workspace_id}/lists/{list_id}/snapshots/{revision}/changes` report. Only a changed `current_role` with exactly one reviewed value per revision and a new source excerpt/URL becomes a report. It returns verbatim quote, source URL/platform, observation time, excerpt hash, literal old/new values and an explicit not-independently-verified qualification. Ambiguous, missing, and suppression-unresolved identities stay silent. Explicit webhook opt-in is unchanged; same-value or timestamp-only refreshes do not enqueue delivery. Reports are retrieved through the normal authenticated API; webhook bodies remain metadata-only.

Verification: `uv run pytest -q tests/research/test_changes.py tests/db/test_webhooks.py tests/db/test_saved_lists.py tests/db/test_saved_lists_api.py` —40 passed, including real DB role-transition evidence and no duplicate unchanged-refresh notification. Ruff and MyPy passed; generated OpenAPI and TypeScript/client contract checks, frontend typecheck, and `git diff --check` passed. No source/model/provider/browser/external receiver was contacted. Report: `docs/completions/SKR-081.md`. Board: **56 done / 21 implemented_pending_verification / 3 in_progress / 16 planned**. Hosted delivery remains under the existing SKR-074 gate. Next assigned Sol ticket is SKR-082; local OAuth contract work can proceed without user credentials, while live Google authorization needs OAuth test-client setup.

## Grouped Sol analytics, X parser and MCP batch — 2026-10-16

Canonical board is **57 done / 23 implemented_pending_verification / 4 in_progress / 12 planned**. SKR-093 is done. SKR-082/083 changed planned→implemented_pending_verification, and SKR-084 changed planned→in_progress; none of these three was falsely marked done. The prior SKR-081 verification/report was also recorded in tickets.json before regenerating the canonical board. Reports: docs/completions/SKR-082.md, SKR-083.md, SKR-084.md, SKR-093.md; operator contracts: YOUTUBE_ANALYTICS_RUNBOOK.md and MCP_RUNBOOK.md.

082: dedicated initiating-owner RLS grants, PKCE S256, authenticated single-use OAuth completion with exact read scopes and mine=true owner-channel pinning; source keyring AES-GCM/AAD reuse; encrypted single-flight refresh, generation/owner/revoke fencing, no access/refresh token in responses; 30-day absolute grant expiry; local revoke wipes ciphertext and explicitly says remote revocation not performed. Narrow privileged expiry function clears expired co-owner secrets without exposing rows, and actual offline restore revokes ALL owner grants including co-owners. Migrations0034/0035 applied locally. No OAuth client/settings/credentials were configured. Browser start/callback integration and actual Google consent/channel/refresh tests remain pending.

083: bounded historical31-day daily report endpoint under the grant; pinned owner channel; views/estimatedMinutesWatched/averageViewDuration, literal units/values and Pacific dates, credential-free query provenance and canonical response hash. Unsupported metrics, missing days, quota, empty/malformed reports never become guessed revenue/zero data; coverage false. Expired access can refresh once, no report retries. Same-owner optional internal summary reuses copied GenerateAnswerNode, ReportSelection/ResearchReport/ReportObservation and active job accounting; exact complete line selection only, default local Ollama, pre/post grant/job fence, no private metrics in workspace-shared evidence. HTTP currently returns literal summaries; UI and an explicit user-facing model-summary job integration remain open, as does live owner-report availability.

084: fetched public-clis/twitter-cli pinned commit7c634e0d396b1e7af9f63315b414925fe4f29ae7, full50-file source/tests/license with archive/file hashes under third_party/external/twitter. Copied models.py/parser.py UNCHANGED into skriller._vendor.twitter with license and provenance tests. No CLI/auth/client/write import or source operation. x_discovery.py adapts bounded search payloads: Top/Latest, cap25,1MiB/structure limits, no inferred person identity/default zero metrics, rejection/dedup/truncation and private/promoted-result exclusion.18tests passed, including4adapted upstream parser fixtures. Missing: pinned transaction dependency, isolated read executor with no host browser cookies, global budgets/bytes/cancel/credentials/checkpoints/evidence, actual session/search/read verification. Existing registry stays unavailable; parser success or credentials do not enable a route.

093: optional stdio ProductMCP reuses adapted copied Agent-Reach MCP scaffolding. Default doctor tests unchanged; custom handlers skip Config/host doctor. The copy's PROVENANCE.json patch hash and MODIFICATIONS.md record the change. Six fixed tools: list conversations, submit normal source-read research into an existing conversation, read job views, list lists, read snapshot, read evidence. Fixed configured API origin/workspace, private current-owner ID-token file, normal per-request Firebase verification. No DB/source credentials, arbitrary commands/URLs, posting/DM/export/billing/analytics tools. Research creates normal jobs/admissions, same checkpoints and usage, explicit idempotency key. Added normal workspace conversation listing and optional workspace query on message submission to prevent alternate-owned-workspace submission. Actual SDK memory protocol+API+PostgreSQL+controlled worker returned identical normal results/usage and one admission on retry; disabled entitlements, missing auth, foreign workspace/unknown tools and output bounds reject. Actual stdio child initialized and listed6tools without any source/session/API configured. No client registration or persistent MCP service started.

Verification: analytics/OAuth/summary/actual backup-restore49passed; Xparser18passed; MCP/upstream/workflow/schema/provenance31passed plusactual stdio1passed; related public YouTube/retention/connections/schema18passed/1optional live skipped. Final combined set115passed/1skipped and one transient local RabbitMQ56739connection timeout; that single failed broker dispatch case reran successfully(1passed). Ruff and checked-body MyPy15source modules pass; actual generated OpenAPI/client checks and TypeScript pass; diff check pass. Existing unrelated dirty tree preserved. Only public source code acquisition used external network; no customer Google/X/source/model/provider/receiver or browser/auth session accessed.

After tests and zero unexpired active attempts/retention leases, verified exact owned API command and gracefully reloaded API only; journal .runtime/sol-services.json now API10892, worker55613,retention48282 unchanged. Proxy/web unchanged. Retention already launches fresh bounded children, so new expiry logic is loaded on the next child. Direct database/broker/worker_consumer checks passed. New OAuth sources/workers/MCP were not automatically enabled; no .env values were printed or changed.

User explicitly said continue Sol during this batch. Model allocation next remains GPT-6.1 Sol Medium for the X executor, not a forced switch. An async user question is outstanding: select the CRM destination for088 and payment provider for090, or keep them pending. Their tickets require provider selection BEFORE implementation; do not silently choose. No API key is needed for current local work. Analytics callback/report UI can be grouped on Luna later when requested, with tab-local initiating UID/workspace/state, exact callback state match, immediate code/state URL cleanup, normal bearer complete call and no source tokens/client secrets in the browser. Existing user-deferred direct LinkedIn/Reddit and hosted deployment/backup acceptance remain pending.


## 2026-10-17 — CRM and billing foundations

The outstanding provider question is resolved: user delegated global CRM choice; selected Salesforce based on official IDC revenue-share reporting. User selected both Stripe and Razorpay. See docs/CRM_AND_BILLING_DECISIONS.md.

SKR-088 in_progress: src/skriller/crm/salesforce.py reuses existing qualified exports and copy-derived JSON. Owner opt-in, explicit LastName/Company mapping, stable workspace/entity external ID, literal near-match custom field, unknown omission, no Lead Status/guessed contact upgrades. Fixed org-specific HTTPS PATCH with finite timeouts/response bound, no redirects/proxies/retries. Three real DB tests prove erasure after selection denial, tenant/owner/opt-in, and qualification/contact preservation. Mock transport proves same native upsert request identity, not actual remote dedup. Remaining encrypted OAuth destination, durable queue/audit/authenticated routes, send-time lock/recheck and actual sandbox.

SKR-090 in_progress: billing/events.py verifies bounded raw Stripe/Razorpay HMAC, Stripe timestamp/mode/account, strict JSON duplicate keys. Hints only, no checkout grants. Razorpay unsigned event-id header is not trusted; signed-body hash identifies replay. Migration0036 and billing/inbox.py add metadata-only operator inbox with no app/PUBLIC grants. Actual committed replay dedups; forged body/signature, altered signed same event identity and workspace rebind reject. Requires server-owned binding configuration, never event metadata. No payment route/runtime enabled or entitlement change. Remaining current-state clients, persistent subscription/catalog binding, serialized reconciliation, DB paid-access fence and sandbox acceptance. Existing owner settings allow enabled=true, so boolean updates alone cannot enforce cancellations. Preserve admissions and do not invent recurring credit resets.

68passed combined billing/CRM/actual DB preparation+inbox/export/entitlement checks; Ruff and checked-body MyPy5source modules pass. Migration applied locally through actual DB tests. No real CRM/payment/model/source/browser/auth session request, no .env changes. Runtime not restarted because no new route enabled. Board57done/23pending/6in_progress/10planned. Continue Sol locally; no model switch or keys needed yet. Existing hosted/direct-source gates remain user-deferred. Reports docs/completions/SKR-088.md and SKR-090.md list unfinished scope accurately.


## 2026-10-17 — Sol billing enforcement and reconciliation continuation

Implemented concrete SKR-090 backend components, not just additional tests. Migration0037: billing_bindings, one authority/workspace and unique provider/account/subscription, initially disabled, no tenant/PUBLIC grants. billing/access.py operator-only bind and same entitlement advisory/policy-row lock order. Scoped SECURITY DEFINER billing_access_allowed() exposes boolean only; entitlements.policy_for applies it, independent zz_billing_admission trigger denies direct SQL admissions. Owner enabled=true cannot override cancellation/expiry; existing unbound finite trial/manual pilots unchanged. Already admitted execution is checked through existing execution_allowed path.

Migration0038: operator-only reconciliation audit. billing/reconcile.py validates CurrentSubscription against bound account/subscription and explicit customer/plan Allowance. Locks before provider retrieval and holds through atomic event/audit/policy/access writes. Max15min lease or periodend; absence of refresh fails closed. Paid updates preserve owner pause/lower limits and immutable admissions. Pilot caps finite lifetime ceilings, no invented recurring resets. Does not order by event creation time or trust payload status. Duplicate reconciled event does not fetch/grant twice. Concurrent test proves second provider fetch waits and final cancellation wins.

billing/providers.py fixed Stripe/Razorpay HTTPS GET current-subscription clients; no redirect/proxy/retry, finite time/body/deadline, mode-specific APIkey, explicit Stripe-Version deployment input. Stripe requires single quantity1 item, current_period_end, expanded paid same-customer/subscription invoice, no pause_collection. Active or open/unexpanded invoice alone gives paid=false. Razorpay uses documented cust_ IDs, paid_count and valid current cycle; active is separately enforced by reconciler. No live provider calls. Refund/current_invoice charge-refund verification remains unfinished. References in decision document.

Migration0039: operator-only per-workspace customer/plan/cap catalog. billing/catalog.py configure invalidates prior access, load uses strict finite Allowance, receive_bound ignores webhook metadata workspace and resolves saved native binding, unknown subscriptions reject, refresh creates operator-only internal event and uses same reconciliation/audit path. Tested controlled actual HTTPclient→DBcatalog→refresh→normal policy. Still needs bounded public ingress/runtime and scheduled polling; do not activate an unscheduled lease-based subscription.

Backup restore now disables all archived billing bindings and clears access expiry before serving: actual isolated dump/restore test seeded paid access and confirms it cannot revive. Existing OAuth/automation/erasure recovery checks still pass. No services restarted or settings/env changed; new payment routes/services are not enabled. No browser/auth session/source/model/payment access.

Verification:110passed combined tests/billing,tests/crm,DBbilling/access/reconcile/inbox,CRMpreparation,exports,entitlements,backups,research_workflow,core/schema. Then2newcatalog checks passed, final affected catalog/access/reconciliation/inbox/backup/entitlement suite25passed after migration0039. Ruff and checked-body MyPy9source modules pass; diff check pass.112unique selected tests passed overall; overlapping reruns are not additional unique checks. StatusSKR-090 stays in_progress, board57done/23pending/6in_progress/10planned. No new ticket falsely marked done. NextSol: runtime/refresh scheduling, customer checkout/refund integration; then CRM encrypted destination+durable sync and isolated X execution. No model switch is needed.


## 2026-10-17 — grouped Sol implementation and next Luna UI handoff

Completed substantial backend work across SKR-088/090 (both remain in_progress, not done). New migrations0040-0045 applied through actual DB tests. No actual payment/CRM/source/model or browser/auth session use, no env/key changes, no persistent new service or normal API restart. User explicitly said keep remote payment plan creation pending and continue locally; do not request those keys again. Hosted and LI/Reddit account gates remain user-deferred.

090: billing/runtime.py isolated operator FastAPI intake (not mounted in tenant app), max256KiB body and5sec async wall guard, single signature header, static account/mode configuration and operator-role startup. Session-advisory per-workspace worker lock spans committed attempt accounting/provider read; attempts committed before I/O, finite exponential backoff,5attempt quarantine, due-only scan max10workspaces and no unconfigured account reads. Periodic refresh every5min uses same audit; quarantine cannot silently spawn unlimited refreshes. billing_runtime.py reuses copied Agent-Reach bounded no-follow reader for0600owner JSON config, SecretStr/repr guards, serve/worker/once/provision modes, no secrets in argv. Real once child passed; no persistent service started.

USER PRICES APPROVED: Stripe StarterUSD29/month50runs25results3sources; ProUSD79/month200runs100results5sources. Razorpay StarterINR2499/month sameStartercaps; ProINR6499/month sameProcaps. billing/plans.py stores minor units2900/7900cents and249900/649900paise, native Stripe price/Razorpay plan request payloads. billing/provisioning.py commits write intent before POST, stable Stripe idempotency key, verifies exact receipt amount/currency/month/mode/nativeID, reuses durable ready receipt; unknown/caught/crashed write requires reconciliation, never blindly creates another Razorpay plan. No real plans created. Provider credential creation is explicitly user-deferred.

0043adds verified provider period_start/end to bindings and monthlyflag in storedAllowances/catalog. Actual normalAPIused_runs and DBadmissiontrigger count immutable admissions in [start,end). CurrentSubscription now has optional period_start at end of dataclass; actual providers parse subscription item/current_start. Monthly granted access requires aware validcurrentwindow <=32days and rejects regressing start. Original finite trial/manual catalog entries remain lifetime; new approvedplans allowance_for() usesmonthly=True. Repeated events don't resetusage; ownerpause/lowerlimits and admissionshistory preserved.0045forces NEW.admitted_at=clock_timestamp() before admissionguard, preventing application-role backdating. DirectSQLbackdated admission test consumescurrentquota. Audit records includeallowance/window. Remaining090: real customercheckout binding/API/UI and refunds/disputes/invoice/payment verification, actual sandbox acceptance; not alljustlivepending.

088: crm/store.py owner-scoped encrypted short-lived explicit token destination (NOT completedOAuth). ExistingKeyring/AESGCM domainAAD includesworkspace/id/owner/instance/generation/UTCexpiry. Wrongkey/expiry/metadata/tenant/coowner/revokefailclosed. Revocation takesprivacylock beforedestination/queuelocks, wipescipher, advancesgeneration and cancelsqueued/claimed work. crm/queue.py adaptedexistingwebhookleaseledger: explicitowneroptin/idempotent requesthash, oneentityselection perrequest,100pendinglimit, stable nativeSalesforce externalID; bounded5attempts/backoff/45seclease. Durableclaim beforeI/O, stale leases don'tsend. Reusesactual create_export/download_export +copiedJSON forsend-timequalification/contact/erasure checks underprivacylock. Holdsprivacythroughsinglebounded nativePATCH; uses freshdestinationgeneration/expiry. Responsebytes nowiteratedwithoutfixedbuffering so slowtricklecan'tevadedeadline. crm/runtime.py copied/adaptedwebhookboundedchildruntime, opaqueIDs argv,20secondprocessgroupkill andboundedoutput; actualmissingtaskchild returnedstale withoutprovideraccess. No workerpersistentlystarted. BackuprestoreactuallyseedednonemptyCRMtoken+pendingqueue, verifiescipherwipe andcancel; paidarchiveleasesalsoinvalidated. Remaining088: automaticSalesforceOAuth/refresh, authenticateddestination/queueAPI, liveorgpermissions/dedup.

Verification FINAL127passed combinedbilling/CRM/encryption/queue/runtime/nativecontracts/approvedplans/monthlyquotas/actualbackup/entitlement/researchworkflow/schema suite. AfterDBtimestampguard16affectedtests passed; final full127coverscurrentguard too. Ruffpass; checked-bodyMyPy18source modulespass; diffcheckpass. Newcompletiondetails: docs/completions/SKR-088.md,SKR-090.md; runbooksdocs/CRM_RUNBOOK.md andBILLING_RUNBOOK.md. Canonicalboard57done/23pending/6in_progress/10planned; no partialticket falselyclosed.

NEXT MODEL: GPT-6 Luna Medium, UI-only082/083 batch permodelallocation. ExistingAnalyticsbackend/generatedcontracts are ready for ownerconnection/callback+literalreportpresentation. MainAPIroutes /v1/workspaces/{workspace_id}/youtube-analytics: POST/oauth/start,opt_in; POST/oauth/complete grant_id/state/code SecretStr; GET/grants; POST/grants/{id}/revoke and/refresh; POST/grants/{id}/reports returnsAnalyticsReport withliteral summary and summary_status=literal_metrics_only. Do not inventa modelsummaryjob/button; internalhelperhasnouserjobroute. UI musttie callback toinitiatingUID/workspace/grant/state in tab-local sessionstorage, rejectcontextchange, remove code/state URL promptly, pass normalFirebasebearer. No source token/clientsecret inbrowser, no host cookie/browsertab inspection (existingrestriction), no privateanalytics inworkspaceevidence. Exactmetrics/daylabels/units/Pacifictimezone/coverage; missingdaysnotzeros, nounsupportedrevenue. Handleowner/auth/revoke/configmissing typedstates. Readapps/web/AGENTS.md plusfrontend skill beforeedits, followinstalledNextdocs; testcomponents andAPIclient contracts/types. This handoffdoesnotmeanSolbacklogdone: remainingcheckout/refund/CRMOAuth/XexecutorstaySol. UIcomponentcompletiondoesnotcloseactualGoogleconsent/channel/reportacceptance orsummarybackendgate.


## 2026-10-17 — Luna analytics UI batch and done-ticket follow-ups

User selectedLuna and requested a separate future-action file only for tasks whose owning tickets are DONE. Canonical auditfound no DONE tickets with remaining acceptance. Added docs/DONE_TICKET_FOLLOWUPS.md as an empty eligible-action index/policy; did NOT list Stripe/Razorpay test keys because090isstillin_progress. Payment remotecreation remains explicitlyuserdeferred; do notaskkeysagain.

Readapps/web/AGENTS.md and installedNext16.4 use-client/page/output docs. UsedImpeccableskill/context once (incumbent refinement allowed), craftfloor; no redesign. No browser/auth session or source account inspected underexistingrestriction.

Implemented apps/web/src/lib/youtube-analytics.ts: generatedschema types and privateAPI method factory, reusing createApi's Firebase bearer/no-store request boundary. Distinctanalytics errors maskrawprovider bodies, nonJSON and networkerrors, never researchprompt copy. Grantsvalidateworkspace/UUID/ownerfields/knownmetadataonly; no secret-bearing fields. Complete/refresh/revoke responseIDpinned. ConsentGooglefixedorigin/path/stateregex/expiry; reportvalidatesselectedgrant/channel/range/numerics/units/unsupportedmetrics/Pacifictimezone/literalstatus/hash/date.

analytics-consent.ts captures OAuth callbackandreturns sanitizedURL; componentimmediatelyreplaceState strips code/state/providerparams beforewaitingFirebase. Tab-local sessionStorage hasonlygrant/state/uid/workspace/expiry, nevercode/sourcecredentials/private report. Single-useconsume rejects mismatchedUID/workspace/state, expired, denied, duplicates. Callbackrefmemoryonly; generationchecksaccountchanges.

components/youtube-analytics.tsx integrated intoWorkbench alwaysmounted forcleanup whileidentityloading, renderedonlysignedin. Loadsnormalworkspaceallowance toshowowner-onlycontrols. Owner connects viaexplicit Google navigation using sameorigin root or /connections/youtube-analytics/callback redirect only. Addedthatcallbackpage re-exportingexistingHomeidentity/workspace shell. Callbackreturnautoopenspanel; StrictModecompletiononce tested. Listsinitiatingownerconnections, refresh/localdisconnect, selectablechannel and<=31 historicalPacificdays. Exactrows/units, missingdaysunknown, unsupportedmetrics unavailable, rawliteral summary, nomoney/fakemodelsummarybutton. Reportcomponentmemoryonly; account/channel/date/disconnect clears; staleasyncstatecannotcrossaccount. Existingstyles/tokens extendedsmallscoped CSS/nativeaccessiblelabels/table/disclosure. No backend/schema/APIcontract changes thisturn.

Verification:164tests across18frontendfilespass (21new consent/API/component cases), finaltsc and generatedcontractscheckpass. Mechanicaldetector returned[] andautomatic UIhooksfoundnoissues. IsolatedNext productionbuild/staticroot+callbackpassed; initialcopiedworkspace standalone-tracewarningfixed onlytemporaryconfigoutputFileTracingRoot, confirmedcleanbuild; sourcenextconfig/lock/tsconfigandrunningdevcacheunchanged. Finalsmallresponseguardtightening thenpassedfulltests/tsc. Globalpnpm11.1.1didnotmatchproject12.6.0; usednpmexec--package=pnpm@12.6.0temporarily, noglobalinstallorlockchange. Buildstage ignoredpath in.runtime/analytics-ui-build-path. No livebrowservisualverification, Googleprovider/model/networkdata orkeychanges.

Docs/completions/SKR-082-083-UI.mdrecords scope/evidence.082/083fullstatusesremainimplemented_pending_verification: actualGoogleconsent/channel/refresh/report andbrowserresponsivegateopen;083privateuser-facingmodelsummaryjobintegrationstillmissing. Board57done/23pending/6in_progress/10planned. Do notmarkpartialdonejustforcount.

NextmodelSolMedium groupedbackend: owner-privateanalytics-summaryjob usingexistinganalytics/summaries.py helper, withno rawprivate report inworkspace-sharedjobs/evidence; SalesforceOAuth/acquisition+refresh andnormalownerCRMconfig/queueAPI; checkoutcustomerbinding/refund/dispute backend. ExistingLunaUIcallbacks/literalreportsareimplemented; noUIrewrite orpassing-suite rerunswithoutnewchangesneeded. ActualGoogleOAuthclient/configandprovider/hostedacceptance stillpending; noAPIkeyneededfornextlocalbackenddevelopment.

## 2026-10-17 — Sol private summary persistence/executor

Implemented analytics/private_jobs.py and migrations0046/0047, with initiating-owner
RLS, existing Keyring AES-GCM and scope/generation/state/expiry AAD, immutable
trusted report binding to existing executable owner accounting job, <=1h expiry,
grant-invalidation/restore revocation ciphertext wipe trigger and owner-bound
cross-owner expiry cleanup wired into existing analytics retention. One-shot
execution commits running before copied summary helper/model ledger; duplicate
execution no extra call, results encrypted and owner-private, cancellation and
revocation discard in-flight answers. No private values in shared evidence/events.
7 new DB cases; grouped analytics/private/OAuth/retention 30 pass; Ruff/MyPy pass.
No external models/providers, secrets, browser access, service restart or charges.

Ticket083 remains pending: no dedicated admission/routes/worker dispatch yet. Do
not expose this internal store as if web summary jobs are ready. Next Sol work:
create bounded opaque accounting job admission and owner-only summary API/worker
wiring, preserving private contents and no blind crash replay; then CRM OAuth and
billing checkout/refund. No model change needed. Board57done/23pending/6in_progress/
10planned unchanged because full acceptance has not completed. Existing done-ticket
followup index remains valid/empty; remote payment creation still user-deferred.

## 2026-10-17 — Sol summary API/worker and CRM OAuth/API batch

Implemented analytics/jobs.py, dedicated owner_summary purpose migration0048,
reporting scheduler/runtime branch, bounded one-call/4096-token/120s admission,
required actor-hashed idempotency and owner-only POST analytics/summary-jobs, GET
/status via /summary-jobs/{id}, POST /cancel. Typed SummaryInput/Output generated.
Requests/provider report/answers only encrypted initiating-owner snapshots;
shared plans/conversations/events/outbox no private dates/metrics/channel. Early
quota check before providerGET and atomic admission repeat. Leased one-shot
execution/checkpoint prevents duplicate/uncertain replay; interruption discards
private output. Local Ollama remains default. API and shared worker tests pass.

CRM router now mounted in mainAPI: owner-private destination list/disconnect,
qualified field-mapped selection enqueue, delivery list/cancel, OAuth start/complete
and due refresh. crm/oauth.py confidential fixed production/sandbox endpoints,
S256PKCE; config helper reuses existing redirect validation. crm/consents.py separate
owner-only encrypted consent/refresh state (0049), single-use code and refresh CAS,
absolute30d consent, conservative15m access. Routine rotations keep queued
selection generation; disconnect during refresh cannot reactivate. Selection and
isolated child refresh access when due; native401 marks access due on next bounded
attempt, no immediate PATCH retry. Standard/sandbox/develop MyDomain allowlist.
0050 owner-bound retention wipes expired OAuth across owners, disables destinations
and cancels outbound work. Restore wipes pending+active OAuth in actual nonempty
restore fixtures. Callback UI is not yet implemented; no tokens/browser use.

Verification:87 grouped analytics/CRM/HTTP/OAuth/retention/backup pass before final
follow-throughs;44 worker/entitlement/resume/followup pass,1 existing opt-in skip.
Final summary guard API5 pass, CRM401/HTTP/queue/OAuth43 pass, final CRM/API/OAuth/
backup25 pass; Ruff/MyPy8modules, actual OpenAPI/client drift and TypeScript pass.
No external provider/model request, browser access, key change, process restart or
charge. Placeholder Salesforce settings added only .env.example. Real serving
API/worker were not restarted; coordinate owned restart after UI integration.

Board57done/24implemented_pending_verification/5in_progress/10planned:088 advances
from in_progress after backend implementation; no partial done.082/083/088 actual
Google/Salesforce/browser gates stay pending. DONE_TICKET_FOLLOWUPS.md remains
empty because deferred keys/accounts belong to unfinished tickets.

## 2026-10-17 Luna UI checkpoint

The assigned SKR-083/SKR-088 UI controls are implemented. Private analytics summaries
use a stable retry key, bounded status polling, cancellation and account/context
clearing. Salesforce supports owner-scoped PKCE connection management and delivery
from saved-plan results with current qualified groups, explicit near-match review,
field mapping, explicit send consent, status and cancellation. Updated ticket counts
remain **57 done, 24 implemented_pending_verification, 5 in_progress, 10 planned**;
these two tickets remain pending only for configured live Google/Salesforce and
authenticated browser acceptance.

Verification: all 169 web tests pass; TypeScript no-emit, Next production build,
Impeccable detector and `git diff --check` pass. No live provider credentials or
browser session was used. No API key is needed for the local implementation.

NEXT ALLOCATED MODEL: GPT-6.1 Sol Medium for the remaining SKR-090 customer checkout,
refund/dispute and reconciliation work, plus SKR-084 executor review. The user deferred
remote Stripe/Razorpay plan creation, so keep that external account work pending and
continue local implementation. Do not request those provider keys again.

## 2026-10-17 — Sol billing reference worker and X timeout follow-through

SKR-090: migration 0051 and billing/references.py add a durable operator-only queue
for verified Stripe charge-only disputes and Razorpay payment-only disputes and
refunds. Ingress stores only IDs/action/hash; lookup has fixed GET endpoints,
bounded body/deadline, identity/mode validation and no redirects/proxy/retries.
Exactly one matching account/customer/subscription can enter the normal inbox.
Attempt commits before I/O, session advisory lock, finite backoff and five-attempt
quarantine survive process loss. Atomic inbox handoff retains dedupe/conflict
checks. Tenant application role has no queue access. No external API was used.

SKR-084: shield the blocking X reader task when awaiting it; otherwise timeout
cancels its asyncio wrapper before its thread stops and releases capacity early.
A PostgreSQL workflow test verifies release after reader cleanup and no result
retention on timeout.

115 billing/monthly/research tests passed; Ruff/format and checked-body billing
MyPy (4 modules), research MyPy and git diff checks passed. Migration 0051 applied
successfully locally. Both tickets remain in_progress; counts remain 57done /
24pending / 5in_progress / 10planned. No service restart or remote setup occurred.

The user answered the term question: **12 monthly Razorpay cycles**. Do not ask
again. The backend batch below implements initial checkout. Remote plan creation/
live sandbox and hosting remain explicitly deferred. DONE_TICKET_FOLLOWUPS.md is
unchanged because these follow-ups belong to unfinished tickets.

## 2026-10-17 — Sol initial checkout implemented; next model Luna

New backend modules billing/checkout.py, checkout_http.py, checkout_router.py;
migration 0052. Optional billing-runtime JSON `checkout` with Firebase project ID
and exact return/CORS origin enables owner routes in the isolated operator service
(default localhost:8011), not in the main API. Native keys/DB authority never enter
the tenant app/browser. GET owner offers/readiness/current, POST initial checkout
with provider/plan/stable idempotency/opt_in:true, GET private intent status.
Native creation uses verified remote-plan receipts, one initial intent per
workspace, durable pre-POST dispatch, Stripe idempotency, safe uncertain/crashed
states, 35-minute reviewed HTTPS provider links and exactly 12 Razorpay cycles.
No PII/card details sent from app. Client return/query cannot grant paid access.

Known intent markers in signed subscription events queue reference work. Fresh
native receipt must match saved session/subscription/plan/quantity/intent and
expected subscription; Stripe requires complete/paid session, Razorpay total12.
Original owner membership rechecked before atomically creating disabled binding
and catalog/inbox. A separate normal fresh paid/active read alone enables access.
No generic metadata workspace trust. Restores remove archived URLs and require
fresh known-receipt proof. Initial expired/uncertain intent recovery, subscription
replacement after cycle12 and plan changes are operator-managed pilot limitations.

Verified:140 billing/monthly/actual PostgreSQL backup-restore tests pass, including
all four plan/provider combinations, concurrent single POST, callback misbinding,
auth/member/tenant/CORS bounds, uncertain writes/crash, host/expiry/receipt guards,
and no archived link revival. Checked-body MyPy7billingmodules, backupMyPy,
Ruff/format, main+billing contract drift and diff checks pass. No live API, keys,
real plans/checkouts, service launches, UI/browser access or deployment.
Counts unchanged57done/24pending/5in_progress/10planned;090 remains in_progress.

**NEXT: GPT-6 Luna Medium — SKR-090 billing UI.** Exported actual isolated API schema:
docs/contracts/billing-openapi.json; run scripts/export_contracts.py --service billing
--output docs/contracts/billing-openapi.json --check for drift. Main API schema
unchanged. Add configured public billing base URL and owner-authenticated client/
controls to existing web app. Read apps/web/AGENTS.md, installed Next guides and
frontend skill. Exact server offers/currencies/quotas and Razorpay12monthly terms,
explicit opt-in, stable idempotency tied to uid/workspace/provider/plan, bounded
status polling, clear private state on auth/context change, validated HTTPS native
link only for current ready/unexpired state. Do not infer access from return query
or show payment complete without server authority. Display unconfigured,
dispatching/uncertain/expired/operator-managed states accurately. No provider keys,
provisioning, services or live browser/source tests: user-deferred. Use meaningful
controlled client/component tests, contract/type checks and build. Sol retains
security/production/live gates and X OAuth/refresh, not all Sol backlog is complete.

## 2026-10-17 — Luna billing UI completed locally; Sol next

SKR-090 web slice: added `src/lib/billing.ts` and `src/components/billing-panel.tsx`,
wired beside workspace allowance in the existing workbench, configured
`NEXT_PUBLIC_BILLING_API_URL` in `.env.example` (isolated billing service defaults
to port 8011). Workspace offers and checkout status use Firebase bearer auth and
no cookies; prices/quotas/cycles come from the service. Explicit opt-in gates POST.
The stable workspace/provider/plan key ensures retries reuse one initial intent.
The UI only exposes an unexpired `ready` HTTPS link on the Stripe or Razorpay host;
dispatching/uncertain/bound states remain clear and do not claim payment/access.
Billing view clears with sign-out. No provider account/key, checkout, browser
session or service launch used.

Verification: 6 focused tests; all 175 frontend tests; TypeScript no-emit; Next
production build; Impeccable detector `[]`. `pnpm` wrapper could not run because
installed pnpm 11.1.1 differs from repo-pinned 12.6.0, so installed Vitest,
TypeScript and Next binaries were used directly. Ticket counts stay **57 done /
24 implemented_pending_verification / 5 in_progress / 10 planned**. SKR-090 remains
in progress pending authenticated browser and provider sandbox acceptance; remote
plan creation is user-deferred. Subscription replacement after 12 cycles, plan
change, and abandoned/uncertain recovery remain operator-managed pilot limitations.

SKR-091 requires pilot evidence and upstream SKR-076 acceptance; SKR-092/094/095
also depend on unfinished upstream or pilot results. No independent planned Luna
ticket is currently evidence-ready. **Next model switch: GPT-6.1 Sol Medium** for
the next backend/security batch. No API key is required for local work; provider
sandbox acceptance remains user-deferred.

## 2026-10-17 — grouped Sol batch complete; Luna X controls next

New X OAuth modules: `connectors/x_oauth.py`, `connections/x_oauth.py`,
`connections/x_router.py`; migrations0053/0054. Reused CRM transport/consent
patterns. Main routes `/v1/workspaces/{workspace_id}/x/oauth`:
GET owner grant metadata; POST `/start` opt_in; `/complete` consent_id/state/code;
`/{consent_id}/refresh`; `/{consent_id}/revoke` local204. Normal Firebase auth,
initiating-owner RLS and encrypted grants. Fixed X authorize/token hosts, PKCE
S256, Basic confidential authentication, exact read/offline scopes, bounded
native response/deadline, no redirects/retries. Commit consume before I/O;
lost/rotated receipts require reconsent. Refresh replaces/revokes source connection
ID, returns access-only metadata; no old checkpoint auto-rebinding. A boolean-only
definer function fences exchanging/revoked/expired grants and owner demotion across
RLS owners; no refresh token reaches job workers.30day authorization retention,
actual bounded native access expiry. Retention and actual encrypted restore wipe
both grant/access material. No unattended renewal or remote revocation claimed.
Read docs/X_OAUTH_RUNBOOK.md for configuration and lifecycle details.

The old X Dockerfile could not import its runtime; fixed it with five verified
uv.lock wheels, the pinned guarded Python3.12 base, attributed unchanged copied
Scrapling Retry-After function and lazy connector exports. Browser not installed.
Installed image `sha256:a65c2d2475cc3276a54a9df869f803f7dda175dbf1f6c7e0ff1e6562f0748803`
passed actual network-none native probe plus kernel/filesystem and credential
delivery/redaction/revocation checks. Temporary test containers removed. Evidence:
docs/completions/X-WORKER-LOCAL.json. No .env image enabled or persistent service
restarted. Two tracked reference CLI/output files had pre-existing whitespace
drift; compared exact pinned GitHub bytes/AST, preserved files, documented separate
local formatting hashes without changing upstream original hashes. Runtime parser/
models/license remain strict byte-identical.

Billing UI review fixed link expiry (timer and click), wrong port/response context,
and stale account requests, responses and polling. Identity abort after token
lookup prevents old workspace requests with a new token.9 billing tests pass.

Final verification: **95 grouped backend/container checks**, **178 web tests**,
Next production build, TS no-emit, eight-module checked-body MyPy and both API/
generated contract checks. Later metadata enrichment separately passed typecheck
and11billing/contract checks. Final Ruff/diff/design checks are recorded in the
turn. All checks are controlled/synthetic; no live X/payment/model/provider key,
source job, user browser/session, production setting or hosted deployment used.
Counts remain57done/24pending/5in_progress/10planned;084/090 still in progress.

**2026-10-17 Luna completion checkpoint:** SKR-084 owner X connection UI is
implemented locally on the generated API contract. The callback removes code and
state before Firebase identity resolves, validates and consumes the owner/workspace
intent once, and never stores provider tokens. List, refresh-to-replacement and
local disconnect controls distinguish access expiry from consent retention. X is
an optional source only after active owner access. Verification passed: 188 web
tests, Next production build, TypeScript no-emit and contract drift checks. No live
X account or browser session was used; the ticket remains in progress for actual
source coverage/quota/rate-limit acceptance and hosted deployment.

**NEXT MODEL: GPT-6.1 Sol Medium.** Continue local SKR-090 billing lifecycle
follow-through. Stripe/Razorpay remote plan creation and provider sandbox/browser
acceptance remain user-deferred, so choose independent local code and tests that
do not require credentials. Saved-denied localhost browser access remains
untouched.

## Latest Sol checkpoint — 2026-10-17

Grouped work completed: SKR-090 expired/interrupted checkout status recovery;
SKR-084 actual ConnectionMetadata receipt/client pairing and native result
validation fixes; SKR-061 isolated OAuth Reddit search with copied pinned search
method, existing parser, private tenant token delivery, durable capacity/budget/
evidence integration and actual minimal installed image. See completion reports.
Image: `sha256:4beb7cf8eb9961672d7f31b85c490936e6b56470cdeb8c902fdc439561cc214f`.
No source image is enabled in actual .env; only .env.example gained an empty
optional Reddit image key. No source/payment/provider/credential request occurred.
Public documentation was read; no user browser session was accessed.

Verification: 200 combined backend/container and 191 web tests passed, including
real network-none worker and private delivery/redaction/revocation checks. Next
production build, TypeScript/contracts, Ruff and ten-module MyPy passed. Billing
moved to implemented_pending_verification; 061/084 stay in progress for remaining
scope. Board57done/25pending/4in_progress/10planned. X live developer app is now
explicitly user-deferred; do not ask again. Other account/hosting/payment deferrals
persist. No partially verified ticket was marked done, and DONE_TICKET_FOLLOWUPS
was not changed.

**NEXT MODEL: GPT-6 Luna Medium.** One grouped061/084 native-results UI batch:
current `research-results.tsx` still calls every candidate a Search snippet and
uses indexed-reference copy for all result sets. Correct result badges, fallback
excerpt text, mixed-result explanatory/group copy and export action wording.
Preserve source/provider/evidence/provenance fields and unknown person/company
identity. API client native pairs are already implemented/tested. Use controlled
mixed Exa/X/Reddit fixtures; no provider key/session/browser is needed. Read
apps/web AGENTS/installed Next docs and frontend guidance. Keep layout style.
Sol retains bound Reddit cursor continuation and OAuth onboarding/refresh, source
acceptance/cost/quota and hosted gates. Billing provider sandbox remains deferred.

## Luna Reddit OAuth UI checkpoint — 2026-10-17

SKR-061 now includes the optional owner Reddit consent/callback/refresh/local-
disconnect UI. Reddit's fixed authorization URL, exact `read` scope and
`duration=permanent` are validated; callback values are stripped before other
OAuth handlers, and one-use tab-local intent is bound to account/workspace/
consent/expiry. Indexed Reddit search stays selected without an account.
Verification: **205 web tests**, TypeScript, generated contract check, Next
production build, Impeccable detector and diff passed. No key/account/browser was
used. Ticket remains in_progress for local renewal/checkpoint-rebinding work and
deferred live/hosted acceptance; board totals remain 57 done / 26 pending
verification / 3 in progress / 10 planned.

**NEXT MODEL: GPT-6.1 Sol Medium.** Continue SKR-061's local renewal and explicit
checkpoint-rebinding lifecycle work. No user key or testing action is required
for this local batch.

## Sol renewal and consent security checkpoint — 2026-10-17

SKR-061 moved to implemented_pending_verification. Configured fresh owner Reddit
discovery renews access due within 45 seconds using the initiating owner's encrypted
grant, expected-connection fence and existing single-use exchange. It requires
20 seconds original deadline margin; no background scheduler, owner impersonation,
ambiguous selection, retention extension, uncertainty retry or old-cursor rebinding.
Native reads use the replacement; checkpoint replay makes no refresh/source call.
Member/co-owner jobs cannot open the grant. Shared X/Reddit UI now fences delayed
consent starts after account changes and rejects URL userinfo/fragments, unexpected
fields and expired receipts. No environment/source/provider/account setting enabled.

Verification: 98 distinct related backend checks (94 grouped plus four new deadline/
ambiguity/kill-switch cases), final 11 renewal tests, 207 web tests, Next build,
TypeScript/contracts, Ruff, four-module checked-body MyPy and diff passed. Board:
57 done / 27 pending / 2 in_progress / 10 planned. Live/hosted/licensing/rights
acceptance stays pending.
Generic explicit checkpoint rebind remains SKR-025/SKR-030, not implicitly enabled.

**NEXT MODEL: GPT-6 Luna Medium.** Synchronize Reddit connection metadata after
renewal during a run using authenticated progress (`source_access_renewed`, details
only `source=reddit`) or terminal-run notification. Explain initiating-owner
on-demand renewal and unchanged consent retention; preserve optional indexed search.
Avoid stale expiry, duplicate refresh requests and account/workspace leakage. Use
controlled delayed-event/identity tests; no new endpoint/key/source request/browser.
Sol retains remaining source backend work and generic checkpoint rebind semantics.

## Luna Reddit renewal UI completion — 2026-10-17

`ResearchResultsPanel` watches the authenticated job event stream for the
metadata-only `source_access_renewed` event with `source=reddit`, and refreshes
once per run. Terminal completion is the fallback when the event stream is not
available. `RedditConnectionPanel` reloads workspace-scoped consent metadata on
that signal and explains owner-only fresh-run renewal, unchanged retention and
the need to start a new run instead of reusing an old checkpoint. Indexed Reddit
search remains usable without direct access. Tests: 38 focused checks passed;
all 210 web tests passed sequentially across 26 files; TypeScript and production
build passed. Parallel full-suite runs failed one Reddit connect click assertion;
the test passed isolated and in the sequential full suite.

Board remains **57 done / 27 implemented_pending_verification / 2 in_progress /
10 planned**. SKR-061 stays pending for the user's deferred live-source/hosted
gates. **Next model: GPT-6.1 Sol Medium**, continuing in-progress SKR-059 LinkedIn
discovery backend work. No key or browser test is needed for that local scope.

## Sol LinkedIn isolated discovery checkpoint — 2026-10-17

SKR-059 now has a built immutable worker reusing the full acquired LinkedIn
capture package at its pinned snapshot. The wrapper uses typed search URLs,
single-attempt extraction, private encrypted owner-session delivery, ephemeral
browser context, read-only bounded routing, blocked WebSockets/downloads/service
workers and existing guarded network controls. The initiating owner/creator,
scopes, source switches, cancellation, deadline and current credential generation
are checked before/after the source operation. Other members/co-owners cannot
open that session. Runtime native discovery uses shared browser capacity and
job call reservations; failure/replay do not trigger indexed/native retries.

Durable output is `linkedin_mcp` / `search_reference`, containing only each
reference's own label and link. Unaligned search page text is never attributed
to a person/post. Metadata is `connected_search_reference_only`, direct profile
read `not_attempted`, identity `unknown`. Fixed acquired relative URLs to absolute
public LinkedIn links. Indexed defaults remain usable. Actual environment native
source settings were not enabled. Generated API/client contracts are refreshed.

Verification: **146 distinct related backend/database/security tests passed, 1 live
test skipped** (129 grouped plus 17 request/metadata boundary checks); installed copied capture passed both people/post search in the built
image with Docker network none and cleanup confirmed. **104 existing web
client/export/results regressions**, TypeScript/contracts, Ruff and 11-module
checked-body MyPy passed. Board remains **57 done / 27 pending / 2 in_progress /
10 planned**. SKR-059 remains in_progress for its new native client handling and
deferred account-backed/hosted acceptance. Full profile/post reads remain SKR-060.

**NEXT MODEL: GPT-6 Luna Medium.** Implement strict `linkedin_mcp` /
`search_reference` candidate/provenance and matching platform-metadata acceptance,
reference-specific results/export wording, mixed-source fixtures, and preserve
unknown identity/no profile access. Keep indexed LinkedIn ungated. Also investigate
the recorded parallel Reddit connect click failure: initial context can briefly
show empty/enabled state before the metadata effect sets loading, so check loading
transitions and wait for actual loaded controls instead of raising test timeouts.
No new key, source access, OAuth surface or user browser test is needed. Then
SKR-059 may move to pending verification if local UI checks pass; deferred live
gates still prevent done. Sol retains SKR-060/SKR-062 and general checkpoint rebind.

## Luna LinkedIn client integration checkpoint — 2026-10-17

Finished SKR-059 strict native LinkedIn client handling. Candidate and provenance
must agree on `linkedin_mcp` / `search_reference` / LinkedIn. Platform metadata
must say `connected_search_reference_only`, direct read `not_attempted`, and
identity `unknown`; mixed source/backend/access/evidence/read/identity payloads
are rejected. Exa indexed references retain the source-matched indexed contract.
Results and JSON/CSV exports preserve this distinction. Fixed Reddit and X
connection panels so they wait for consent metadata before showing an empty state
or enabling connect. The recorded initial-click race now has passing regressions.

Verification: **218 web tests passed** across 26 files, TypeScript, generated
contract drift and Next production build passed; Impeccable detector found no
issues. SKR-059 moved to **implemented_pending_verification**; account-backed
LinkedIn coverage, hosted acceptance and commercial/rights review remain pending.
Board: **57 done / 28 pending verification / 1 in progress / 10 planned**.
**NEXT MODEL: GPT-6.1 Sol Medium** for SKR-060/SKR-062 direct-read backend work.
No key, source setup or user browser test is needed for the next local tickets.

## Sol Reddit read and quoted-signal checkpoint — 2026-10-17

SKR-062 now has bounded native post/comment reads, copied rdt-cli read request AST
and unchanged nested parser, isolated owner OAuth read execution and a durable
collecting stage. Private discovery connection/credential generation IDs bind later
reads; missing or replaced generations require a new run. One request, no expansion
or retry; deletes, parents, dates and partial coverage survive. Saved thread evidence
expires from results, and content-free comment indexes make comment erasure invalidate
the shared blob. The optional extraction stage reuses the copied graph with one
bounded chunk/model-ledger call and only exact resource-grounded problem quotes.
No accepted identity/company/contact/buyer claim is created. API DTO validates quote,
resource URL and source date again. Native environment settings remain disabled.

Generated main API/client contracts now include optional `reddit_thread` with
`evidence_id`, `thread`, `signals`, `rejected_signals`, `signal_coverage_complete`
and `signal_failure_code`. Thread stores flat depth-first comments with parent IDs,
source URLs, dates, tombstones, omission counts, unknown identity and buying intent
not inferred. Existing client currently ignores that new view: Luna must add strict
validation and readable incumbent results rendering before local ticket closure.

Verification: original related selection 113 passed/3 preset failures/1 broker
failure/1 live skip. Preset failures were pre-existing input-bound overrun: shortened
repeated trusted instructions while preserving accuracy rules; all 19 preset/page
checks then pass. Docker broker workflow passed; isolated native project broker
was restarted with persistent queues retained, then its real queued workflow passed.
Thus all 117 cases from the original related group are verified. Additional Reddit
discovery 12 passed, final parser/thread 16 passed; installed worker network-none
search/cursor/thread and cleanup passed. Final image:
sha256:bb0d6bc2336bc01fa7e1b11877bcf59bd15f74c630ad6c1e94cfce09d48f26ac.
Fourteen source modules passed checked-body MyPy; affected final preset/API modules
rechecked. Ruff, generated contracts, TypeScript and 112 API/results/export web tests
pass. No live source/external model/browser/account request was made.

Board: **57 done / 28 pending verification / 2 in_progress / 9 planned**. SKR-062
is in_progress for client rendering and deferred live/hosted acceptance. SKR-060
LinkedIn profile/company/post reads remain planned, Sol-owned.
**NEXT MODEL: GPT-6 Luna Medium**, one full SKR-062 client/results batch; scope is
in docs/model_ticket_allocation.json. No key or live user test is needed. Preserve
all shared dirty files. Do not retry the previously denied localhost browser path.

## Luna Reddit thread UI completion — 2026-10-17

SKR-062's generated `reddit_thread` client boundary and result view are complete
locally. Candidate/provider/evidence pairing, public Reddit URLs, resource IDs,
parent order, tombstone rules, dates, bounded counts and signal provenance are
validated. Results show the retained post and comments, nested reply context,
quoted source-specific unverified problem signals, unavailable dates and deleted
text, plus partial-coverage counts. Identity remains unknown and buying intent is
not inferred. JSON/CSV exports retain the existing metadata/snippet/provenance
whitelist; private thread bodies and signals are excluded.

Verification: **223 tests passed across 26 web test files**, TypeScript, generated
contract drift check and Next production build passed. Impeccable detector returned
no findings for the results UI and stylesheet. No source account, browser session,
API key or external model was used. SKR-062 moved to implemented_pending_verification;
real account-backed/hosted acceptance and provider commercial rights/quota remain
open. Board: **57 done / 29 pending verification / 1 in_progress / 9 planned**.

**NEXT MODEL: GPT-6.1 Sol Medium**, for remaining SKR-060 LinkedIn direct-read
backend work and eligible SKR-076 evaluation. No key or user action is needed for
the next local batch.

## Sol LinkedIn resource-read backend checkpoint — 2026-10-17

SKR-060 moved planned → in_progress. The acquired single-attempt capture now
supports typed profile/company-about/activity-or-UGC-post reads in the existing
isolated worker. Separate `linkedin_resource_read` authority uses the initiating
owner's exact discovery connection/credential generation, session/read scope,
source switches and original job deadline. No contact overlay, automatic cookie
renewal, account import, retry or implicit checkpoint rebind. Fixed safe upstream
auth/access/rate-limit/not-found codes replace raw diagnostics. Controlled capture
reuses the full pinned upstream package without editing it.

Durable collection stores private escaped resource evidence, rechecks authority
before persistence, and hides content after expiry/erasure. Replay makes no source
call. Restricted LinkedIn presets reuse existing saved graph/model accounting:
exact job-title observation survives; invented email is rejected; identity and
contact availability stay unknown/unavailable and whole-resource coverage false.
The source-text line-boundary issue found during the new workflow test was fixed
by separate escaped paragraphs, preserving source quote correspondence.

Generated optional `linkedin_read: {evidence_id, resource}` is bound back to the
native LinkedIn discovery candidate. Successful read histories suppress the old
platform-reference “not attempted” notice; original search provenance remains.
After evidence expiry, the view is null while collection.status retains read.


Verification: **134 backend/database/security tests passed, one optional live/model
skip**, final immutable installed worker passed five search/read operations plus
four upstream exception types with Docker network none and cleanup; **117 web
regressions**, TypeScript/generated contracts, Ruff and13-module checked-body
MyPy passed. Image:
sha256:afa3e9f3a80b4b9b99f4215e056b5363de5126a8e9eb923db42268d6a8205d29.
No source account, external model, user browser or ignored credential was used.
Actual native LinkedIn environment remains disabled. Board: **57 done /29 pending
verification /2 in_progress /8 planned**. SKR-076 release-scale/manual representative
corpus and source acceptance remain open; the new development tests do not certify
release quality.

The Luna client/results subtask is complete. The strict DTO checks bind each read to its
candidate URL and resource kind, bound content and enforce privacy constants. The
results view shows safe literal text, collection time, truncation and partial coverage;
expired content is described as unavailable. The export whitelist is unchanged.

Verification: **120 focused web API/results/export tests passed**, TypeScript,
generated contract drift check and production build passed, and Impeccable detector
reported no findings. SKR-060 moved to implemented_pending_verification. Board:
**57 done / 30 pending verification / 1 in_progress / 8 planned**. Live account,
hosted acceptance, source rights and provider operation limits remain open.

**NEXT MODEL: GPT-6.1 Sol Medium**, SKR-025/SKR-030 explicit checkpoint credential
rebind/resume batch defined in model_ticket_allocation.json. No key or user test is
needed for this local work. Preserve deferred account/hosted gates and the denied
localhost-browser restriction.

Latest qualified-export production web build (`next build --webpack`, standalone) passed after these changes. No deployment was performed.
