# X authorization and read worker

Local backend implementation is available. The X setup/callback web controls and
real account/source acceptance remain open; this does not advertise live coverage.

## Configuration

Use the ignored local environment for `SKRILLER_X_OAUTH_CLIENT_ID`,
`SKRILLER_X_OAUTH_CLIENT_SECRET`, and `SKRILLER_X_OAUTH_REDIRECT_URI`, plus the
existing private `SKRILLER_SOURCE_ENCRYPTION_KEY_FILE`. The redirect must match
the registered callback exactly; production requires HTTPS. Browser controls
are the next implementation batch, so no account setup is needed for local tests.

The confidential server client uses PKCE S256 and exactly `tweet.read users.read
offline.access`. It posts only to the fixed X token endpoint, uses HTTP Basic
client authentication, bounds the response and deadline, rejects redirects,
duplicate JSON keys, missing refresh receipts and extra/write scopes, and never
automatically retries an exchange. No source credential enters a URL, DTO,
ordinary error, or job-worker refresh environment. This follows the
[documented X authorization flow](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code).

## Authenticated owner API

The main API contract includes `/v1/workspaces/{workspace_id}/x/oauth`:

- `GET` lists up to three current consents belonging to the initiating owner,
  with separate authorization-retention and access-token expiry/state fields.
- `POST /start`, with `opt_in:true`, creates a ten-minute pending consent and
  returns its ID and provider authorization URL.
- `POST /complete`, with `consent_id`, `state`, and `code`, consumes the saved
  state before provider I/O and creates an encrypted read/discover connection.
- `POST /{consent_id}/refresh` consumes the encrypted refresh generation before
  I/O and replaces the source connection. Its new ID is returned as metadata.
- `POST /{consent_id}/revoke` wipes the local grant and revokes its local access
  connection. Provider-side remote revocation is explicitly `not_performed`.

Only the initiating owner can complete, refresh, list or revoke a grant; another
workspace owner cannot use that owner's callback or decrypt their refresh grant.
Callbacks, codes and refresh attempts are single use. Concurrent revocation,
configuration drift, process loss, malformed receipts and uncertain rotation
cannot replay an old grant or reactivate a retired connection. Reconnect with
fresh user consent when an exchange is uncertain.

The application retains authorization for at most 30 days; refresh does not
extend that retention. The actual access expiry comes from a bounded provider
receipt. Routine refresh is explicit through the API; there is no unattended
renewal scheduler in this pilot. Jobs bound to a retired connection stop passing
the runner fence; refresh does not silently rebind historical job checkpoints.
Submit a new run or use a separately approved reconnect workflow.

The existing connection loader injects only the access token into `x_read`.
A boolean-only database function checks initiating-owner status and consent
generation even when the job actor cannot inspect the private refresh table.
Refreshing/revoked/expired grants and demoted owners fail this check. Retention
wipes both refresh and access material. Backup restore revokes grants and clears
archived credentials; a restored authorization never becomes live automatically.

## Installed worker

Stage the five hash-verified `uv.lock` wheels, then build without network access:

```sh
.venv/bin/python -m scripts.provision_x_assets --download
docker build --network=none --build-context x_wheels=.runtime/x-build -f infra/egress/Dockerfile.x -t skriller-egress-x .
```

`Dockerfile.x` reuses the pinned guarded Python worker base and installs only the
minimal Pydantic closure. It contains no browser or source-account acquisition
utility. The Retry-After function is copied unchanged from pinned Scrapling into
a small attributed module; the source license is included. Lazy package exports
prevent the standalone worker from importing orchestration dependencies.

Set `SKRILLER_PUBLIC_X_IMAGE` only to an operator-reviewed immutable image after
the container checks. The current locally tested image is recorded in
`docs/completions/X-WORKER-LOCAL.json`; this work did not enable it in `.env` or
start a source job. Tests use synthetic credentials and network-none transport,
plus the existing kernel/filesystem/credential cleanup checks. Actual X account
permissions, API cost/quota, coverage and rate-limit behavior, production host
deployment, and authenticated browser acceptance remain unverified. Pagination
execution is unavailable; the existing result flag reports possible more data.
