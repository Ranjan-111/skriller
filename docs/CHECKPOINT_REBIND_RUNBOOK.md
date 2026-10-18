# Explicit checkpoint credential replacement

The local API supports replacing an existing saved LinkedIn or Reddit read
binding for a paused collecting checkpoint. This is explicit owner consent, not
automatic session renewal. A normal resume never changes credentials.

1. The initiating workspace owner reads `GET /v1/jobs/{job_id}/rebind-options`
   with the workspace query parameter. This advisory response contains the job
   version, source, old opaque connection reference and all pending candidate IDs.
   It contains no credential generation or secret. An empty option list means
   this checkpoint cannot currently offer this operation.
2. The owner configures/selects an active replacement through the existing source
   connection setup. Selecting a stored configuration does not prove provider
   authorization. Real account acceptance remains separately deferred.
3. After explicit confirmation, submit `POST /v1/jobs/{job_id}/rebind-and-resume`
   with `Idempotency-Key` and `source`, `previous_connection_ref`,
   `replacement_connection_ref`, `expected_job_version`, and `entity_ids`.
   Keep the same key and exact body for a retry whose response was lost. Reusing
   that key with a different selection is rejected.

The mutation requires current owner membership, the original job initiator,
replacement connection ownership, current read scope/authentication kind, source
switches, entitlement, remaining deadline/budget and a matching saved version.
All pending native candidates for the chosen source must be selected, with the
same previous binding and successful discovery membership. Completed reads,
existing collection outcomes, erased/suppressed entities, dispatched reservations
and uncertain/failed/running work cannot be rebound. Such work needs reconciliation
or a fresh run. Missing original bindings cannot be fabricated by this API.

The replacement's current encrypted generation is admitted through the existing
trusted runner boundary. Queueing, binding updates, route-account updates and a
metadata-only consent event commit in one transaction. Any failure rolls back all
of them. Existing route provider choice, configuration digest and spent
attempts/traffic are preserved; a failed route requires a fresh task. Pagination
cursors are untouched. Later source dispatch repeats current authority and exact
generation checks, so subsequent revocation/rotation still stops the read.

The original immutable plan, deadline, usage and reservation history are retained.
No source/model/browser call occurs during selection or replacement. The bounded
web client methods `rebindOptions` and `rebindAndResume` validate response scope,
choices and snapshot confirmation. The paused-results UI makes the owner load
choices deliberately, select a source and a separate unexpired active replacement,
and check a clear confirmation before sending the mutation. Ambiguous transport
failures preserve the exact request key and payload; a stale-version response clears
the old request and requires refreshed choices and a new confirmation. Connection
metadata is strictly validated and rejects unexpected fields, including any secret.
Native source configuration stays operator-controlled; no ignored environment
settings were changed.

## Local evidence — 2026-10-17

- 16 real PostgreSQL/API tests cover LinkedIn and Reddit saved-read continuation,
  exact retry/conflict behavior, owner/co-owner/member barriers, stale versions,
  wrong prior/candidate/source, expiry/revocation/scopes, kill switch, original
  deadline, cancellation, uncertain work and failed routes. A controlled read
  follows each successful replacement. Route spend and job usage remain intact.
- Combined regression: **66 passed, one optional local-model test skipped** across
  rebind, resume, vault execution, LinkedIn/Reddit resource evidence, follow-ups
  and the new dual-platform journey.
- **122 focused web API/results/export tests passed**, with generated API/client
  contracts, TypeScript, Ruff and checked-body MyPy passing.
- Tests use encrypted synthetic credentials and controlled worker responses.
  Account-backed provider behavior, hosted operation and source rights are not
  certified by these local tests. No API key, model request or user browser was used.
- New UI/client coverage adds 111 focused tests in `results.test.tsx` and
  `api.test.ts`; TypeScript, generated-contract check, production build, Prettier
  and Impeccable detection passed. SKR-025/SKR-030 stay pending verification for
  the account-backed and hosted acceptance listed above.

The concrete collecting pipeline now checks known saved native bindings before
claiming an attempt or reserving a call. A stale/revoked/missing generation pauses
that still-pending work with a safe `connection_required` event and no source I/O
or new usage. Both successful replacement tests reach this pause through the actual
collector, rather than setting a synthetic paused state directly. Changes occurring
after dispatch retain the existing output-fencing/new-run behavior; this endpoint
does not retry uncertain calls. Operator-disabled/unconfigured readers retain their
existing route availability handling. Source configuration is not auto-enabled.
