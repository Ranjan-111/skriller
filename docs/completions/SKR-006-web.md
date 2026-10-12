# SKR-006 — Web scaffold

Implemented `apps/web` as a Next.js 16.4.0 / React 19.3.0 / TypeScript 7.0.2
application. Direct dependencies are exactly pinned; `pnpm-lock.yaml` records the
resolved tree. Local verification used Node 26.10.0 and pnpm 12.6.0. The declared Node floor is
22.12; CI and Docker target Node 24 and have not yet run remotely.

The research workbench gives priority to a single prompt, with lead/research
modes, editable examples, optional source selection and result limits. No fake
conversations, prospects, counts or progress are rendered. Service readiness is
obtained from `/health/live` and `/health/ready`; disconnected/not-ready states
explain recovery and disable the start button. Source access is described as
backend-dependent.

The client uses `POST /v1/conversations` then
`POST /v1/conversations/{id}/messages` and provides typed entry points for job and
result reads. Requests encode IDs, time out, preserve user input on failure and
classify unavailable, authentication, quota and malformed-response states.
A token-provider hook supports later Firebase authentication; this ticket does
not add sign-in or supply demo credentials. A successful job acknowledgement is
shown only for a returned job ID. Streaming and result rendering are later work.

`PRODUCT.md` derives product facts from the existing PRD and marks the audience as
a hypothesis. `DESIGN.md`, `.impeccable/design.json` and the workbench surface brief
record the proposed light research-reading-desk visual system. The user requested
autonomous implementation; visual direction is proposed, not user-approved.

## Verification

- Vitest: **15 passed** in two test files. Cases cover health separation,
  conversation/message payloads and Bearer tokens, unavailable/auth/malformed and
  network responses, planner clarification, real source/limit request controls,
  retained input, empty prompts, mode switching and connection retry.
- TypeScript: `tsc --noEmit` passed.
- Next production build: `next build --webpack` passed, generated `/` and
  `/_not-found` static routes.
- Headless Chrome inspection at desktop 1440x1050 and mobile 390x844: no horizontal
  overflow or runtime page errors; mode switch and source checkboxes function.
  Screenshots: `.impeccable/review/desktop.png`, `mobile.png`.
- Impeccable detector over the changed UI target: no findings (`[]`).

Package install required npm network access. pnpm 12 performs supply-chain
verification that can require registry access even when packages are cached.
Running local binaries after frozen install avoids repeated network checks during
verification. Dockerfile uses the standalone Next output, a non-root runtime,
and configurable build-time API URL; Docker execution has not been verified in
this frontend task.

Frontend CI is added in `.github/workflows/web-ci.yml`: frozen install, unit
tests, production build, typecheck and container build. Its commands were run
locally except the Docker build; the remote workflow has not executed.

Independent visual finish review is pending parent coordination. This note does
not assert live research execution, real authentication or complete SKR-006
backend/Compose acceptance.

## Independent-review fix batch

Applied the two material findings in `docs/completions/WEB_REVIEW.md`:

- Empty results now explicitly state that rendering is not implemented in this
  scaffold and identify the later source/fit/refinement capabilities as future
  work.
- New research, mode switching, source disclosure and example buttons join the
  existing disabled textarea/count/source controls during submission. A delayed
  request cannot acknowledge an apparently replaced request context.

Added a delayed-submission interaction regression that attempts all context
changes, verifies the original prompt/mode/sources/limit and single submission,
then verifies controls recover and New research clears the acknowledgement.
Existing failure coverage also checks context controls become enabled again.

Final fix-batch verification: **16 Vitest tests passed**, Next production build
passed, `tsc --noEmit` passed. Same desktop 1440x1050/mobile 390x844 captures were
replaced at `.impeccable/review/{desktop,mobile}.png`; both had zero horizontal
overflow and zero runtime page errors. No second detector or unrelated design
polish was performed. Fix verdict remains assigned to the independent reviewer.

## Resume verification on 2026-10-12

Independent review disposition is **ship** for the two scored fixes, recorded in
`WEB_REVIEW.md`. The resumed scaffold has **17 passing Vitest tests** after adding
one CI contract rejection check; Next production build and `tsc --noEmit` passed.
Actual JUnit output is now archived by CI. This is frontend-scaffold verification;
the parent still coordinates API/Compose and container acceptance for SKR-006.
