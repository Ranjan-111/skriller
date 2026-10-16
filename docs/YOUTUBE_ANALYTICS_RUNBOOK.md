# Owner YouTube Analytics: backend contract and pending setup

This integration is separate from public video metadata and captions. Ordinary research needs no Google OAuth client. The browser connection/callback and literal report interface are implemented and locally tested; actual Google consent and owner-channel acceptance remain open. Do not advertise the integration as production-ready yet.

## Local configuration

When ready for live validation, configure a Google OAuth **web application** client and enable YouTube Data API v3 and YouTube Analytics API in that project. Keep these values in the ignored root `.env`:

```text
SKRILLER_YOUTUBE_ANALYTICS_OAUTH_CLIENT_ID=...
SKRILLER_YOUTUBE_ANALYTICS_OAUTH_CLIENT_SECRET=...
SKRILLER_YOUTUBE_ANALYTICS_OAUTH_REDIRECT_URI=http://localhost:3000/connections/youtube-analytics/callback
```

Use the exact registered redirect URI; production requires HTTPS. The existing `SKRILLER_SOURCE_ENCRYPTION_KEY_FILE` is required. Firebase sign-in configuration does not automatically provide this source OAuth client. No payment or hosted model is required by this adapter. Google account/API consent configuration is a separate operator action; this implementation did not create it.

The requested scopes are `https://www.googleapis.com/auth/yt-analytics.readonly` and `https://www.googleapis.com/auth/youtube.readonly`. The fixed endpoints and scope requirements follow Google's [server OAuth guide](https://developers.google.com/youtube/reporting/guides/authorization/server-side-web-apps) and [report query reference](https://developers.google.com/youtube/analytics/reference/reports/query).

## Authenticated API flow

All routes have prefix `/v1/workspaces/{workspace_id}/youtube-analytics` and use the existing Firebase bearer authentication.

1. `POST /oauth/start` with `{"opt_in": true}` returns a grant ID, authorization URL and 10-minute expiry. Only the initiating workspace owner can complete or use it. The authorization URL contains the public client ID, state and PKCE challenge, never the client secret or tokens.
2. The browser interface retains grant ID/state/initiating UID/workspace/expiry in tab-local session storage, navigates to the fixed Google consent endpoint, and receives the registered callback. `/connections/youtube-analytics/callback` renders the existing app identity/workspace shell; the root page is also supported as a callback. Other origins/paths are rejected before navigation. Code/state and provider query values are removed immediately, before waiting for Firebase identity. Completion checks the initiating account/workspace and single-use unexpired state; decline or mismatch requires a fresh connection. Consent codes and private report values are never stored in browser storage.
3. `POST /oauth/complete` with `grant_id`, `state` and `code` must be authenticated as the same owner. The code/state go in the request body. Consent is single-use and consumed before provider I/O; failure or interrupted completion requires a new start. Tokens are never returned. Zero or multiple returned owner channels are unavailable rather than silently choosing a channel.
4. `GET /grants` returns only the initiating owner's metadata, with `Cache-Control: private, no-store`. Another workspace owner cannot see or use these grants. Expired secret bytes are cleared without decrypting them.
5. `POST /grants/{grant_id}/refresh` refreshes using encrypted offline credentials. Report reads can also refresh an expired access token once. The original 30-day retention expiry is preserved; renewed consent is required beyond it. Some Google grants may omit a refresh token, in which case renewal is explicit.
6. `POST /grants/{grant_id}/revoke` disconnects locally and wipes encrypted credentials. Remote Google revocation is `not_performed`; the owner can also revoke the application's grant in Google Account permissions. A restored backup is always locally revoked and cannot renew consent.

No source session is loaded from the user's host browser. No source write, posting, upload or monetary report scope is requested.

## Reports and summaries

`POST /grants/{grant_id}/reports` accepts:

```json
{"start_date":"2026-01-01","end_date":"2026-01-02","metrics":["views","estimatedMinutesWatched"]}
```

At most 31 historical days and five unique metric names are accepted. Supported metrics are views (count), estimatedMinutesWatched (minutes) and averageViewDuration (seconds). Other names are returned as `unsupported_metric`; they are not sent to Google. An unsupported-only request makes no source call or refresh. The provider query pins the owner channel, `dimensions=day`, sorting and a 31-row limit. No arbitrary filters, channel IDs, URLs, pagination or commands are accepted.

Rows retain exact values and dates. Currency is null because monetary analytics is unavailable. Dates use `America/Los_Angeles`, following Google's [time dimension definition](https://developers.google.com/youtube/analytics/dimensions). Missing days remain missing, and `coverage_complete` is false because requested end dates do not prove provider data availability. API errors are typed/redacted; quota errors never fabricate results or trigger retries. A source URL and canonical JSON response hash identify provenance without OAuth material; the hash is not claimed to be an original transport-byte hash.

The HTTP response includes deterministic literal metric summaries. The frontend displays them with exact daily values/units, Pacific dates and missing-day/unsupported-metric labels. Report reads require an explicitly selected owned channel and a historical range of at most31 days. Account changes, date/channel changes and disconnect clear private reports; stale async results cannot repopulate another account's view. Refresh and local disconnect use the existing owner API. Backend configuration/authentication failures have analytics-specific messages, never source errors or credentials.

`analytics.summaries.summarize_report` additionally reuses the copied answer node under an explicit active same-owner job budget, with exact-quote validation and before/after grant checks. It defaults to local Ollama, persists no workspace-shared private report/evidence, and is not yet wired into a user-facing model-summary job. No model-summary button is advertised. Its citation IDs identify response-hash-bound rows rather than database evidence. This optional workflow remains open under SKR-083.

## Verification boundaries

Local tests cover actual PostgreSQL owner policies, consent replay/expiry, key encryption, single-flight refresh, expiry cleanup, actual archive restore, fixed Google request construction with an offline HTTP transport, bounded metrics parsing, revocation races and the copied summary node/ledger. Public-video research retains its existing path. No Google client configuration or source account was used during implementation. Live authorization/report coverage and browser callback acceptance remain required before closing the two tickets.

## Private local-model summary jobs

The summary backend is now implemented. POST `/summary-jobs` under the same
analytics prefix with `grant_id`, `report` (the same bounded ReportRequest) and a
required `Idempotency-Key` header. This admits one finite workspace-budgeted run,
reads the authorised report once, and queues only opaque IDs. GET
`/summary-jobs/{job_id}` returns initiating-owner-only status and the encrypted
stored result after execution; POST `/summary-jobs/{job_id}/cancel` cancels and
wipes unfinished private work. Every response is private/no-store. Repeating the
same request/key returns the same job; changed intent requires another key.

The normal research worker handles the `owner_summary` reporting stage, using the
same private keyring file as the API. The graph remains the copied saved-content
answer node, with local Ollama default, a one-call/4096-token budget and original
120-second deadline. Queue delay counts toward that deadline. Interrupted calls
are not automatically retried. A paused/interrupted result requires a new explicit
request after review; generic resume must not replay an uncertain model charge.
The separate private row expires within an hour; revoked/expired grants and key
or envelope tampering fail closed. No private analytics enter shared evidence.

Frontend summary controls are the next allocated UI batch. The serving API/worker
were not restarted during backend fixture work; deploy/restart through the normal
owned service flow after the UI integration, without inspecting browser sessions.
