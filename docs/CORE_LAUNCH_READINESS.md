# Core launch readiness

Recorded 2026-10-18. This is a release checklist, not additional tickets or a claim
that all local/core implementation is complete. tickets.json is authoritative.

## Implemented and checked in the latest batch

- Numeric planner comparison/value binding corrected after four reproduced
  failures. Rejected swapped bounds cannot publish or dispatch on replay.
- Copied source extraction -> explicit owner review -> confirmed private export
  integration passes, including rejection of unconfirmed discussion exports.
- Application Compose definitions added and statically checked. No containers
  or host acceptance ran. The priority batch passed 100 focused local tests with one
  optional model skip; see completions/PRIORITY-LAUNCH-LOCAL.md.

- Production web build succeeds (Next.js standalone, installed toolchain).
- Private cache owner/generation binding and rotation races: 15 targeted database
  cache/collection checks pass; Ruff, formatting and MyPy pass.
- Persisted discovery wiring: three targeted database workflow checks pass.
- Previous combined social client batch: 170 focused web checks pass. Social runtime
  routes remain default-off; no live source or container acceptance is implied.

## Core acceptance still open

- SKR-076 / SKR-096: both local planning models independently score 2/5 on the five
  synthetic diagnostic cases. Authorized Groq 20B and 120B baseline comparisons
  also scored 2/5; guidance experiments were rejected and the final one reached
  provider HTTP 429. Remote evaluation stopped. Representative semantic/field-quality gates remain
  open. Keep grounding guards and all failed reports; no repeated benchmark without
  a meaningful implementation change. Quality acceptance is explicitly user-pending
  on base M4 Air; no heavy model downloads. This remains a core release blocker.
- SKR-067: confirmed-record export client/UI is now implemented and checked against
  the existing private backend; checkpointed reviewed-fact qualification exports
  correctly. Full actual-model prompt-to-evidenced-qualified-export acceptance
  remains open; these fixture/client checks do not close that gate.
- SKR-011 / SKR-027 / SKR-033: provider-use/storage and deployment egress acceptance
  remain open. The source provider/stage is implemented; access is not guaranteed.
- SKR-041: authenticated workers use fresh reads. Optional authenticated replay
  integration is not enabled; hosted cache/storage acceptance remains open.
- Authenticated browser acceptance remains unverified under the existing saved
  localhost browser restriction; earlier user confirmation covers sign-in/results,
  not every later refinement/billing/owner-analytics journey.
- Hosted pilot, off-host backups, container packaging/isolation, source accounts,
  X live access, and remote billing plan/sandbox work remain user-deferred. Local
  implementation cannot mark these required acceptance checks Done.
- Customer-pilot/relevance/coverage/latency evidence cannot be replaced by fixtures.

## Deferred expansion

SKR-091 (language), SKR-092 (regional source): explicitly deferred by user for launch.
SKR-094 semantic retrieval and SKR-095 companion are conditional later-roadmap work;
do not add infrastructure or a desktop product speculatively.

No new credentials or model switch are required for the local changes recorded here.
Credentials, when future acceptance is scheduled, belong only in ignored local
configuration and never in these reports.
