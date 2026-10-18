# Indexed-platform results regression

The reported completed run contained 18 saved source records. The frontend rejected the entire successful response when a web-discovered LinkedIn URL had platform metadata identifying LinkedIn.

The frontend now permits web discovery with indexed LinkedIn or Reddit metadata only for safe HTTP(S) URLs on the matching platform domain. Spoofed domain suffixes, unrelated sites and unsafe protocols remain rejected. Account-backed source validation is unchanged.

A failed results refresh no longer displays a stale empty response as a successful zero-source search. Previously loaded nonempty results remain visible on refresh failure.

Verification:
- API, results and workbench regression suites: 158 tests passed.
- Actual saved response replay: all 18 source records accepted; private diagnostic payload and temporary replay test removed afterward.
- Frontend TypeScript check passed.
- Local readiness reports database, broker and worker ready.

This verifies response parsing and recovery, not the qualification of these sources as confirmed leads. Authenticated browser acceptance remains separate. Existing ticket acceptance gates and statuses are preserved.
