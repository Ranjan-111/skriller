# Priority launch implementation — 2026-10-18

## SKR-096 / SKR-076: numeric comparison grounding

A model could select the wrong number from an otherwise literal quote. For
`at least 25 and at most 100 employees`, the previous guard accepted `gte 100`
because both the number and an at-least cue occurred somewhere in the quote.
The guard now binds the selected numeric token directly to its comparison cue;
recency additionally binds the number to its day unit. No missing rule is invented,
grounding requirement removed, model retried, or provider changed.

The new seven-case regression initially failed four cases. After the production
fix, the planner/schema/regression selection passed 57 checks with one optional
actual-model test skipped. A real restricted-role database/bootstrap check confirms
that swapped bounds pause, create no successor or discovery attempt, retain one
metered model call, and do not call the model again on replay. The bootstrap suite
passed 11 checks. This improves rejection correctness; it does not demonstrate
improved model interpretation accuracy or replace the representative quality corpus.

## SKR-067: copied observations through review and private export

Extended the existing combined LinkedIn/Reddit journey with private JSON export.
The unchanged copied extraction path creates draft role observations. Explicit
owner review accepts the chronology/person mapping, qualification confirms the
founder, and the actual export API requalifies/downloads the single record with
its saved evidence ID. Selecting the unconfirmed Reddit discussion is rejected.
This reuses the existing production export implementation and adds no export logic.

The combined journey passed all three variants. Export/resume regressions passed
20 checks. Source transports and model answers are synthetic; owner approval is
an explicit fixture operation. Actual-model prompt-to-qualified-export accuracy,
authenticated browser acceptance and account-backed operation remain open.

## SKR-074: application orchestration groundwork

Added `infra/deploy/compose.yaml` and operating instructions for API, research,
retention, standalone web and Caddy. The application manifest requires explicit
image references, protected runtime configuration, domain and memory budgets.
Only ingress publishes ports; web uses an internal network; backends are non-root
in the prepared image, read-only with bounded temporary storage, dropped capabilities
and process limits. The manifest disables demo auth, unaccepted AI planning and
direct extraction/source workers, requires S3, and preserves Settings' commercial
provider checks. Private DB/broker and operator migrations are separate prerequisites.

YAML parsing and application exposure/gate invariants were checked without reading
runtime secrets or starting containers. Outbound networking is not claimed to be
an egress firewall. Actual image/Compose/Caddy/TLS/memory/recovery/secret and backup
acceptance remain user-deferred. No deployment or cloud purchase occurred.

## Verification and state

Focused local tests across the selections: **100 passed, 1 optional model skip**,
including nine Groq adapter/selection checks. Ruff formatting/checks and three-module
checked-body MyPy pass. These local checks made no external requests. The separately
authorized cloud evaluation below has its own failed results and denominators.
No browser session, Docker execution or hosted action ran.

SKR-096 and SKR-067 remain implemented_pending_verification; SKR-076 and SKR-074
remain in_progress. No Done promotion is justified by these local checks alone.
Board remains 57 done / 33 implemented_pending_verification / 2 in_progress /
4 planned. The prior 2/5 local-model report remains historical
evidence with its original hashes, not a new run against this guard change.

## Authorized Groq comparison and retained failures

The user approved a bounded synthetic Groq evaluation while retaining the Ollama
default. Added an opt-in diagnostic harness that reuses the unchanged five local
case labels/assertions, real database accounting and the existing Groq adapter.
Reports keep failed/unexecuted cases, bounded synthetic outputs, invocation counts,
reported usage and source/corpus hashes captured before execution. A successful
schema response is not a semantic pass. Clients close after each case, and runtime
configuration/credentials are not changed or reported.

Groq 20B at the existing 512-token output bound passed 2/5 assertions; the three
compound cases returned provider errors. Two single-case diagnostics identified
HTTP 400 `json_validate_failed`; the 1,024-token comparison got a structured numeric
answer but still failed the unchanged operator label. General operator guidance
at 1,024 tokens remained 2/5 and was reverted. An explicit 120B comparison at
1,024 tokens also scored 2/5. A role/geography guidance experiment scored 1/5,
including a final provider HTTP 429; it was reverted and remote evaluation stopped.
No failed case was silently retried by the application, removed from its run,
pooled across experiments, or re-labelled as a semantic success.

There were **23 synthetic provider invocations total** across two five-case 20B
runs, three single-case diagnostics, and two five-case 120B runs. Full baseline
reports remain PLANNER-QUALITY-GROQ.json and PLANNER-QUALITY-GROQ-120B.json;
the named FAILURE, ERROR-DIAGNOSTIC and PRE-GUIDANCE files preserve each separate
experiment. The final prompt remains the original instructions plus the separately
verified numeric binding guard. No heavier local model was downloaded.

Production now supports an operator-only allowlisted Groq model selection
(`SKRILLER_GROQ_MODEL`: 20B or 120B). Its default stays 20B and the application provider
is still Ollama, independently checked after the probes. Production output bounds
were not raised. A mocked real-ledger check verifies the 120B request/usage model
attribution and rejects unreviewed model IDs. Offline mocked-provider tests now
use unique capacity source/host names, so a real provider cooldown remains intact
without blocking synthetic fixtures; no live cooldown was cleared or bypassed.

Groq's official current structured-output documentation lists both models and
warns that best-effort schema mode can return validation errors. This provider
comparison does not close the 50-prompt or 200-record representative quality gates:
https://console.groq.com/docs/structured-outputs
