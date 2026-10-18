# Local frontend and failed-search recovery

The reported run c98dec53-d065-4234-96bf-105618198198 persisted terminal reason `source_interrupted`. All three searches recorded `source_unavailable`, with zero saved records. This was a real unsuccessful search, separate from the earlier frontend response-validation issue.

The old Next.js process was orphaned and had revoked stdout/stderr descriptors. It was stopped and restarted on the requested port 3000, with output retained in ignored `.runtime/web-restart.log`. The new server reported ready in 342 ms; subsequent page requests recorded HTTP 200 in 186 ms and 35 ms. These are server observations, not an authenticated browser acceptance claim.

One bounded direct search initially reproduced unavailability. Subsequent calls using the three source queries generated from the reported run's stored plan succeeded: LinkedIn 2, Reddit 1, Web 2 references. No paid API credentials or account-backed platform access were used. This supports an intermittent search-path failure; the original generic error does not prove its underlying upstream cause.

A separate synthetic broker-to-worker-to-free-search probe completed with 2 unverified references in 3.383 seconds. The user's failed run was not modified, silently retried or charged another workspace run.

The results empty state now distinguishes unsuccessful runs from completed searches with no matches. A source interruption explicitly explains that the failure is not evidence of no matches. Paused/canceled/other unsuccessful runs direct users to their run status instead of blaming prompt specificity.

Verification: 72 results/workbench tests passed, including the new source-outage empty-state regression; TypeScript and diff whitespace checks passed. Live provider checks are bounded observations, not a promise of continuous free-provider availability. Existing browser verification restrictions remain in place.

Refresh the site and explicitly start a new run when ready. The previous terminal failed run remains an accurate record of its failed source calls.
