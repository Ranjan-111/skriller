# Opt-in research schedules and webhook notifications

These are backend APIs and explicit per-workspace operator workers. Ordinary research does not require either worker. No source account, model provider, payment integration, or notification endpoint is enabled by creating a list.

## Saved-plan research schedules (SKR-080)

An owner can `POST /v1/workspaces/{workspace_id}/research-schedules` with `list_id`, `opt_in: true`, `cadence_hours` (1–720), `max_runs` (1–25), and optional `required_connection_ids` (at most nine). The selected list must reference the latest immutable plan in its conversation and have an explicit user objective. The schedule pins the immutable objective that existed at that plan's creation. Later follow-ups cannot silently replace that objective.

There are at most ten schedules per workspace and one schedule per list. `GET` on the collection lists current configuration; `GET /{schedule_id}/runs` returns up to 25 opaque occurrence/job references. `DELETE /{schedule_id}` disables future work and stops a queued scheduled job at its next permission check. `POST /{schedule_id}/resume` requires `opt_in: true`, preserves consumed run allowance, and waits a full cadence before another due time. Exhausted schedules cannot reset their allowance through resume.

Start the optional dispatcher explicitly, using an existing owner identity and workspace UUID:

```sh
uv run python -m skriller.schedule_runtime --workspace-id WORKSPACE_UUID --actor-id OWNER_UID
```

`--once` performs one bounded scheduling pass and dispatches existing authorized outbox work. The scheduler performs no source/model call itself. It reserves a durable 60-second due-record lease, then atomically admits one existing research job, records its occurrence, and advances the cadence from the current time. Missed intervals are coalesced; no backlog storm is replayed. A committed occurrence survives restart without another logical job or admission. All actual research uses the existing job worker, source switches, reservations, deadlines, cancellation, cache and result rules.

A disabled discovery source, expired/revoked required connection, missing search service, unavailable plan, exhausted workspace allowance, or unfinished prior scheduled job pauses the schedule. Required connection references are explicit generation dependencies; this scheduler does not inject credentials or automatically substitute a reconnected account. Native account task rebinding remains in the source-connection tickets. Current execution is the existing research/indexed-discovery route, not an assertion of direct LinkedIn/Reddit account access. Each run produces a separately reviewable research job; it does not overwrite the immutable saved list or upgrade lead qualification.

## Signed metadata webhooks (SKR-089)

An owner can `POST /v1/workspaces/{workspace_id}/webhooks` with `list_id`, a public HTTPS `url` without query/fragment/userinfo, and `opt_in: true`. The private source-encryption keyring must be configured. The response returns a newly generated `signing_secret` exactly once, with `Cache-Control: private, no-store`. Store that secret at the receiver. Later list/history responses omit key material. Ten endpoints per workspace is the local bound, including disabled entries.

After that opt-in, only a supported, evidence-backed current-role change queues a `list.snapshot_ready` event in the same database transaction. Identical values, observation-time-only refreshes, ambiguous role values, and suppression-unresolved identities do not queue a notice. The event is a change signal, not independently verified hiring or role truth; retrieve the cited deterministic report at `GET /v1/workspaces/{workspace_id}/lists/{list_id}/snapshots/{revision}/changes`. No historical snapshots are automatically backfilled. The fixed webhook JSON envelope contains schema version, event ID, workspace/list/snapshot IDs, revision, and event creation time. It contains no research values, names, contact details, source excerpts or signed download URLs. Data retrieval still requires the normal authenticated API.

Start notification delivery explicitly:

```sh
uv run python -m skriller.webhooks.runtime --workspace-id WORKSPACE_UUID --actor-id OWNER_UID
```

`--once` reserves at most one delivery. Each reserved attempt is committed before I/O, with a 30-second lease. A fixed child process has a 20-second total wall-clock/output bound, including DNS/TLS/response handling. Public destination checks repeat for every send; dialing uses the vetted numeric IP, verified TLS uses the original hostname, environment proxies are not consulted, and redirects are never followed. HTTP 2xx succeeds; redirects are blocked; 408/429/5xx and transport failures retry after 30/60/120/240 seconds, up to five reserved attempts total. Process death still consumes an attempt. Responses and transport exceptions are not stored or printed.

Delivery is **at least once**. A receiver can accept an event before a crash prevents the sender from committing success. Deduplicate using `event_id`/`X-Skriller-Event-ID`, not a particular timestamp or HTTP request. Verify `X-Skriller-Signature: t=UNIX_SECONDS,v1=HEX_HMAC_SHA256` over `timestamp + "." + exact_request_body` using the signing secret. Compare in constant time and reject timestamps outside the receiver's bounded replay window (for example five minutes with synchronized clocks). Retries retain the event ID and body while obtaining a new signature timestamp.

`GET /{endpoint_id}/deliveries` returns bounded delivery history with redacted outcome codes. `DELETE /{endpoint_id}` revokes delivery, clears encrypted signing material, and cancels pending/leased events. Recheck/disable is serialized with delivery so a completed revocation prevents a new send. Create a new explicitly opted-in endpoint to obtain a new signing secret.

## Erasure and recovery

Entity erasure invalidates broad workspace snapshot derivatives: schedules and webhooks are disabled, notification records are removed under the existing journalled erasure guard before snapshots are deleted, and stale tasks cannot send. An offline backup restore cancels active jobs, disables schedules/endpoints, cancels pending notifications and removes webhook signing ciphertext. Restoring a dump is not renewed delivery consent. Schedule resume requires explicit owner opt-in; a webhook needs a new endpoint/secret.

These local acceptance checks do not close the separate hosted-network, native-account, payment, source-rights or customer-pilot release gates. No hosted receiver was contacted during implementation.
