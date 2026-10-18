# User-reported launch UX fixes — SKR-097 through SKR-103

Seven separate tickets preserve the order of the user's seven issues (the original list repeated number 1).

| Ticket | Change | Verification and status |
| --- | --- | --- |
| SKR-097 | Workspace settings control beside profile opens a drawer containing allowance, billing, YouTube analytics, Salesforce, X and Reddit. Panels remain mounted so account callbacks and X readiness continue to work. | Component interaction and cancellation tests pass. Implemented pending native browser keyboard/focus and responsive inspection. |
| SKR-098 | Start with a question examples immediately follow the composer, before help, notices and results. | DOM-order and example submission regression tests pass. Done. |
| SKR-099 | Mode-specific plain-language help explains the focus. Both use the same selected-source pipeline; the backend seeds people for leads and discussions for research. | Mode switching/request tests pass; backend mode mapping inspected. Done. |
| SKR-100 | Authentication/account changes clear the obsolete sign-in-required warning and preserve composer text. | Signed-out submission followed by signed-in rerender passes. Done. |
| SKR-101 | Submission shows immediate activity; polling exposes actual backend stage and contextual explanations with a spinner. Waiting states do not invent completion percentages. Paused/connection-required/terminal states stop active feedback. | Deferred submission and actual stage-field rendering tests pass; existing polling, cancellation and terminal-state tests pass. Done. |
| SKR-102 | Individual source results have outlined tiles and spacing. Source excerpts render Markdown headings, emphasis, lists, tables and safe links. Raw HTML stays inert; images are represented as text rather than loaded. | Semantic Markdown, script/unsafe URL and image tests pass; source/export regressions pass. Implemented pending desktop/mobile visual inspection. |
| SKR-103 | Selecting unconnected X opens a connection dialog, leaves X unselected and links to the expanded X settings. Active X selects normally. Public indexed Instagram/Facebook/YouTube selection does not unnecessarily demand authentication. | Connected/unconnected X, cancellation, settings navigation and indexed source tests pass. Implemented pending native browser dialog focus/Escape verification. Actual X account/provider acceptance remains previously deferred. |

## Verification

- `corepack pnpm --dir apps/web test`: 28 files, 284 tests passed.
- `corepack pnpm --dir apps/web typecheck`: passed.
- `git diff --check`: passed.
- Impeccable mechanical scan across changed UI components and CSS: no findings; nothing suppressed.
- Native dialogs supply browser focus confinement, Escape handling and focus restoration. jsdom tests polyfill only the modal lifecycle and are not proof of native keyboard behavior.

## Remaining evidence

Browser access to http://localhost:3000 was denied by a saved permission setting. No alternate browser, indirect browser automation or network workaround was attempted. Desktop/mobile visual inspection and native dialog keyboard/focus checks therefore remain pending. This report does not claim a production deployment, real provider login, or a full production-readiness gate passed.

No additional API key, payment, model change, remote source call or model request was needed for this batch. The new Markdown dependencies and lockfile are recorded in the frontend package.
