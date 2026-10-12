## Verdict

1. **Resolved — explicit results limitation.** The replaced desktop and mobile captures visibly say “Result rendering is not implemented in this scaffold yet” and identify source inspection, fit comparison and conversational refinement as later implementation work. The same wording is present in apps/web/src/components/workbench.tsx. It no longer implies a completed backend run alone will populate this frontend.
2. **Resolved — stable pending request context.** The current component disables New research, both mode buttons, source disclosure and example buttons while `busy`, alongside the existing prompt, result count, source checkboxes and submit controls. The delayed-request regression in apps/web/tests/workbench.test.tsx attempts those context changes, checks that the prompt/mode/source/count and submitted payload stay intact, then checks controls recover and New research clears the acknowledgement after completion. Completion documentation reports 16 passing tests, build and typecheck; this reviewer inspected the test and code rather than rerunning those checks. The supplied recaptures show the unchanged resting/offline state, not a pending submission; pending-state resolution is therefore supported by the actual code and regression coverage.

No regressions from the fix batch are visible in either valid recapture. The longer honest empty-state paragraph fits both layouts without clipping or disrupting the prompt-first hierarchy.

## Remaining

Clear for the two scored material fixes. This ship verdict covers the scored fixes for the frontend scaffold; it does not assert completed authentication, persistent history, live source access, research execution, streamed jobs or result rendering. The initial bounded review found the research-reading-desk composition and real offline recovery appropriate to this scaffold. No new full-surface hunt or backend acceptance review was performed, and no UI/backend files were edited by this reviewer.

disposition: ship
