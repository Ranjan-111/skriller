# Reddit isolated OAuth discovery

Status: experimental local implementation, not live-source acceptance. Indexed
search remains available. No source image or account is enabled by this work.

## Optional configuration and owner consent

The server supports a confidential Reddit app with these ignored local settings:
`SKRILLER_REDDIT_OAUTH_CLIENT_ID`, `SKRILLER_REDDIT_OAUTH_CLIENT_SECRET`,
`SKRILLER_REDDIT_OAUTH_REDIRECT_URI`, and `SKRILLER_REDDIT_OAUTH_USER_AGENT`.
Do not place client secrets, access tokens or refresh grants in browser storage.
The User-Agent must be a descriptive app identifier, 16–256 printable characters.
Configured discovery forwards it to the isolated source worker. A production
source image requires an explicit User-Agent; the local fixture default does not
establish an approved app or operator identity.

Owner-only routes under `/v1/workspaces/{workspace_id}/reddit/oauth`:

- `GET` returns safe initiating-owner consent metadata, including separate access
  expiry and consent-retention expiry. It does not test provider access.
- `POST /start` with `{"opt_in":true}` returns a fixed Reddit authorization URL,
  opaque consent ID and ten-minute expiry. Only provider scope `read` is requested,
  with `duration=permanent`. This is a confidential authorization-code flow; it
  does not claim Reddit PKCE support.
- `POST /complete` takes `consent_id`, `state`, and `code`. It consumes the state
  before token I/O and returns the normal `ConnectionMetadata` DTO.
- `POST /{consent_id}/refresh` returns replacement `ConnectionMetadata`; the old
  source connection is retired. Reddit may omit a new refresh grant, in which
  case the consumed grant is retained only after a valid read-only receipt.
- `POST /{consent_id}/revoke` disconnects locally. Remote provider revocation is
  not performed.

The lifecycle reuses the reviewed X encryption, initiating-owner RLS, one-use
exchange, generation and uncertainty controls. Refresh grants remain encrypted
in the control plane for at most 30 days; workers receive only access tokens.
Native `expires_in` bounds access expiry, and refresh does not extend original
consent retention. An uncertain exchange/refresh is not replayed: access is
fenced and reconnection is required. Revocation, owner demotion and expiry block
all readers, including other workspace owners whose RLS cannot inspect grants.
Retention clears expired grants/access; restoring an archive revokes archived
grants and clears pagination references. Migrations 0055 and 0056 apply locally.

The owner connection/callback/refresh/local-disconnect UI is implemented locally.
Configured discovery automatically renews access within 45 seconds of expiry
before its first native read, only for the initiating grant owner's run. It
requires a single eligible consent, no competing access account and at least
20 seconds left in the original job deadline. The selected old connection is
compared again under lock before consuming a refresh grant. Healthy access,
member/co-owner runs, canceled jobs and ambiguous selections do not refresh.
The one-use exchange, original consent retention and uncertainty fences apply.
Uncertain renewal stops that attempt without native retries or indexed fallback.
Checkpoint replay does not refresh. The persisted `source_access_renewed` event
contains only the platform name. No background scheduler, owner impersonation
or checkpoint rebinding is claimed; provider behavior is tested with synthetic
credentials and controlled native receipts only.

## Bounded source execution and continuation

Discovery requires `SKRILLER_PUBLIC_REDDIT_IMAGE` set to an immutable digest and
exactly one active, unexpired workspace OAuth connection with product scopes
`read` and `discover`. Those product scope names do not establish provider
permission or commercial rights. The worker performs one fixed-host GET against
`https://oauth.reddit.com/search.json` or the validated subreddit variant using
the copied pinned rdt-cli search builder/parser. It rejects arbitrary commands,
redirects, browser cookies, oversized replies and automatic source retries.

Each source cursor becomes a server-side opaque reference bound to the initiating
actor, workspace, job, plan revision, connection, exact credential generation and
query/community/sort/time/limit/User-Agent request hash. References expire within
five minutes and the current execution deadline. Raw cursor input is rejected by
the public adapter. Consumption is committed before dispatch, so an uncertain
following-page request cannot be replayed. Connection replacement invalidates the
old references; repeated source cursors stop a loop.

The durable workflow covers initially selected sources before following Reddit
pages, charges each dispatch against the stage's reserved search-call budget,
and stops when its result target, call cap, source end or deadline is reached.
Each page contains at most 10 workflow results; final normal deduplication and the
requested result cap still apply. Continuations honor persisted adaptive cadence
with a bounded five-second capacity wait. Rate limits stop further source calls
and preserve earlier pages; no disguised indexed-search fallback is used after a
native failure. Capacity remains held until a canceled worker actually stops.
Cross-job continuation and automatic resume using a replacement connection are
not supported.

The immutable image and synthetic installed-worker evidence are recorded in
`completions/REDDIT-WORKER-LOCAL.json`. Reproduce the offline build with:

```sh
docker build --network=none --build-context x_wheels=.runtime/x-build \
  -f infra/egress/Dockerfile.reddit -t skriller-reddit-local .
docker image inspect skriller-reddit-local --format '{{.Id}}'
```

## Remaining release gates

- The owner consent UI is implemented locally but has not been exercised against
  a registered Reddit app.
- Account-backed permission, actual relevance/coverage/pagination/limits,
  commercial use, cost and quota/rate-limit acceptance remain user-deferred.
- Real registered-app callback, token lifetime and refresh behavior are unverified.
- Hosted deployment remains user-deferred. Background renewal, delegated renewal
  for member runs and rebinding existing checkpoints remain unsupported. Explicit
  direct-source rebind/resume is tracked by SKR-025/SKR-030.
- Profile/comment reads and source completeness are outside this search route;
  SKR-062 remains planned. Native result labels and provenance exports are implemented.

Request fields and OAuth protocol were checked against Reddit's
[API documentation](https://www.reddit.com/dev/api/#GET_search) and the
[official OAuth2 wiki](https://github.com/reddit-archive/reddit/wiki/OAuth2).
These references do not prove access approval for this deployment.

## Native post/comment reads and problem quotations

The optional native reader now supports one typed `reddit_oauth_read` request for
one subreddit/post ID. It reuses the pinned rdt-cli read builder and comment
parser. It never expands more-comment placeholders, retries a failed source call,
or follows redirects. Read scope and initiating-owner access are required. Later
collection requires the exact connection and credential generation captured by
native discovery; reconnecting requires a fresh run rather than rebinding an old
checkpoint. Indexed discovery remains usable without an account.

Private thread evidence preserves deleted/unavailable bodies, resource parents,
dates, links, omitted replies and partial coverage. Nested comment erasure
invalidates the shared evidence; expiry/erasure removes its API view. Optional
saved-evidence extraction uses the existing configured model and copied graph,
one bounded chunk per thread. It retains only exact resource-grounded problem
quotations with source dates; it does not establish buying intent or identity.
The generated client/results work and account-backed/hosted acceptance remain
pending under SKR-062. No actual native source configuration was enabled.
