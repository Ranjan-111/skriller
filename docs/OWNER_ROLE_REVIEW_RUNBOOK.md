# Owner review of original LinkedIn profile roles

The source reader and copied extraction graph retain unverified profile observations.
An owner can review two dated role observations on the same original record using
the existing `/v1/workspaces/{workspace_id}/role-refreshes/preview` and
`/role-refreshes` APIs. This is a local evidence-review operation, with no new
source/model call and no credential payload.

Native discovery deliberately stores an unreviewed subject as `other`. For that
record, preview now permits only the candidate's own saved native LinkedIn **profile**
section. Both role/date references must cite that same stored profile evidence.
Canonical resource URL, source/provider, excerpt and observation time must agree;
post/company sections, unrelated evidence, changed text, expiry, future observations
and unavailable subjects are rejected. Existing reviewed `person` records retain
their original chronology-review behavior.

Preview returns `requires_person_confirmation`. The owner must review the original
subject, saved excerpts, literal role dates and source URLs. Approval includes the
unchanged preview `expected_review_hash`, `same_subject_confirmed: true`, and, when
required, a separately explicit `person_subject_confirmed: true`. Neither flag may
be set by loading choices or by a model. Missing confirmation returns 409 without
changing claims or subject type. Membership and preview evidence are rechecked
under the existing privacy/entity locks.

Confirmed classification, claim acceptance and chronological supersession commit
together. The immutable role-history record retains the actor and review hash; a
private `_person_subject_review` attribute additionally records the original type,
profile evidence and actor. Raw source metadata keeps `subject_identity: unknown`,
contacts unavailable and buying intent not inferred. No Reddit handle is linked to
this person. A confirmed fit describes the saved plan's supported criteria, not an
independently verified identity or purchasing decision.

The LinkedIn profile preset now admits literal `role_effective_date` drafts alongside
`job_title`. It does not infer or normalize dates or accept model output. The current,
reviewed title projection can satisfy the planner's `role` criterion while preserving
original claims, conflicts, dates and evidence. Only the already-supported grammatical
forms `founders`/`engineers` become `founder`/`engineer` for `role contains` criteria.
Ambiguous person/company geography cannot be resolved by a model guess; exact later
user clarification remains supported.

## Owner UI implementation

The existing candidate results render this review only for native LinkedIn profile
resources with at least two role/date observation pairs. The owner chooses saved
claim references; the client sends no free-text claim values. Preview is explicit.
The preview shows both roles, dates, exact excerpts and safe saved-source links, then
requires same-subject confirmation and a separate person confirmation when the API
requires it. The strict API client validates response shape/hash, binds workspace,
entity and all claim/date/evidence IDs to the request, and binds both source links to
the selected canonical LinkedIn profile URL. It validates successful decision
projections as well.

403 preserves current results. A 409 invalidates the preview, refreshes results and
requires the owner to select and confirm again. An unclear approval response also
refreshes results and drops the old hash; it is never blindly retried. Confirmed
success refreshes current qualification results. Source identity, contact access,
and buying intent retain their original uncertainty states.

Sol's follow-up review fences empty choices (they never resolve to index zero),
locks selection during pending requests and aborts/ignores work after scope or
candidate changes. Every approval error drops the preview/hash/confirmations,
including ordinary transport failures. Non-403 failures refresh results, while a
403 preserves the visible run without a refresh. Projection decisions must contain
both selected role claims with no duplicate IDs; empty success bodies are rejected.

## Verification — 2026-10-17

The three actual PostgreSQL/API integration scenarios cover dual native sources,
LinkedIn outage isolation, and a grounded founder plan through both readers, private
saved evidence, copied extraction, explicit owner review, current qualification,
cited follow-up reporting and immutable refinement. Fixtures inject synthetic source
receipts and model responses; they do not claim live account or model quality.

Final focused backend selection: **138 passed, 2 optional model checks skipped**.
Eight native-profile admission cases exercise confirmation, source/resource type,
excerpt, expiry and observation-clock barriers. The owner UI/API suites pass **114
tests**, with TypeScript and Prettier clean; the Impeccable detector found no changed
UI issues. The repository pnpm wrapper requires 12.6.0 while the installed version
is 11.1.1, so checks ran through existing local binaries. Account/hosted and
representative semantic quality acceptance remain open.

After these recovery fixes, **124 API/results tests pass**, including explicit blank
choice, scope change during preview, network loss, conflict and permission cases.
