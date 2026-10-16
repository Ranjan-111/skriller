# Salesforce sync implementation

The owner-authenticated connection and delivery backend is locally implemented.
Browser connection/callback/selection controls and actual Salesforce acceptance
remain pending. Tests use synthetic providers and tokens; no host browser session
or real Salesforce credential was accessed.

`crm/store.py` reuses the versioned connection Keyring and AES-GCM pattern.
Destinations belong to the owner who connected them. Tenant, actor, destination,
instance, generation and expiry are authenticated metadata. Token expiry is at
most one hour; expired, revoked or tampered records cannot deliver. The OAuth backend supplies and rotates these access tokens automatically;
manual token replacement is not the normal connection workflow.

`crm/queue.py` adapts the existing signed-webhook claim/lease ledger and uses the
copied-export path rather than a second qualification implementation. Each
request queues one selected entity, explicit mapping and near-match opt-in.
Repeating an idempotency key returns the same delivery; changed intent rejects.
At most 100 pending selections per workspace are accepted. Five attempts and
bounded backoff limit retries. Lease identity is generation-fenced and durable
before provider I/O.

Delivery repeats current qualification, contact and erasure checks. The privacy
lock spans the actual bounded Salesforce PATCH; revoke takes that same lock,
wipes the token and cancels queued/claimed deliveries. An already in-flight
bounded call can finish before revoke returns. A stale lease does not send.
Erased or newly disqualified selections are suppressed. No names/contact rows
are copied into the queue. Salesforce unique external-ID prerequisites are in
CRM_AND_BILLING_DECISIONS.md.

`crm/runtime.py` is copied/adapted from the existing webhook bounded-child worker.
It passes opaque IDs only, drains bounded output and kills the child process
group after twenty seconds. Credentials load inside the fixed trusted child
through the private configured keyring. Failed/killed child outcomes remain
uncertain until their durable lease expires; retries reuse the native external ID.

Explicit local operator command (not started automatically):

```sh
uv run python -m skriller.crm.runtime --workspace-id WORKSPACE_UUID --actor-id OWNER_UID --once
```

Omit `--once` only when an operator intentionally starts the worker. It always
uses the restricted application DB role and verifies owner membership. Do not
use a browser profile, account cookies or a different owner's source connection.
Backup restore disables destinations, wipes token ciphertext and cancels queued
delivery work. Actual isolated restore and a real bounded child stale-task test
verify these protections. Live OAuth, Salesforce permissions and actual remote
unique external-ID deduplication remain pending.


## OAuth connection and normal authenticated API

Configure an External Client App for the web-server authorization-code flow with
PKCE S256 and confidential client secrets for code and refresh flows. Request
only `api refresh_token`. Set the callback to the exact frontend URL and configure
`SKRILLER_SALESFORCE_OAUTH_CLIENT_ID`, `SKRILLER_SALESFORCE_OAUTH_CLIENT_SECRET`,
`SKRILLER_SALESFORCE_OAUTH_REDIRECT_URI` in ignored local settings, plus the existing
private `SKRILLER_SOURCE_ENCRYPTION_KEY_FILE`. Set
`SKRILLER_SALESFORCE_OAUTH_SANDBOX=true` for the fixed `test.salesforce.com` endpoint;
otherwise the fixed endpoint is `login.salesforce.com`. No arbitrary login origin
is accepted. Standard, sandbox and partitioned developer My Domain instance URLs
are supported; credentials cannot redirect to an unrelated host.

All routes below require normal Firebase identity and the workspace owner role,
under `/v1/workspaces/{workspace_id}/crm`; connection and delivery records remain
restricted to their initiating owner, including against other workspace owners.

- `POST /oauth/start` with `opt_in: true` returns `consent_id`, authorization URL and
  ten-minute expiry. Browser callback must bind state/consent to initiating user
  and workspace in tab-local storage and remove code/state from the URL promptly.
- `POST /oauth/complete` accepts `consent_id`, single-use `state`, and `code` in the
  bounded JSON body. No code/state/provider details enter error diagnostics.
- `GET /destinations` returns credential-free metadata; `POST
  /destinations/{id}/refresh` renews access when due; `POST
  /destinations/{id}/revoke` wipes local OAuth/access tokens and cancels pending
  deliveries. This is local disconnect; remote provider revocation is not performed.
- `POST /deliveries` takes destination/plan/entity IDs, an explicit `field_map`,
  `selected_near`, `opt_in: true` and a bounded `idempotency_key`.
  `GET /deliveries` lists the latest 100 owner deliveries, and `POST
  /deliveries/{id}/cancel` stops pending work under the actual-send privacy fence.
  Already-completed sends cannot be undone by cancellation.

OAuth state/PKCE and refresh tokens use a separate encrypted initiating-owner RLS
table, with configuration, destination, owner, generation and absolute-expiry
AAD. Consent expires after 30 days; renewal then requires fresh owner consent.
Access is conservatively cached for 15 minutes, renewed before selection and
inside the isolated worker when due. A provider 401 marks access due for the
next bounded attempt without immediately replaying the PATCH. Routine rotation
preserves the destination generation and queued selection identities. Rotated
refresh tokens are committed before use; uncertain refreshes consume the local
credential and require renewed consent, never blind token replay. A disconnect
racing refresh cannot reactivate the destination. Owner retention wipes expired
consents across owners and cancels their deliveries. Restore wipes active and
pending OAuth records as well as access tokens and pending sends.

The browser callback/controls are not yet implemented. Do not claim that the
current website has a complete Salesforce onboarding flow. Actual org API/Lead
permissions, custom external-ID/fit fields and native retry deduplication still
need a configured test org, then explicit acceptance before production.

Provider references: [web-server flow](https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_web_server_flow.htm&language=en_US&type=5),
[External Client App and PKCE](https://developer.salesforce.com/docs/platform/data-loader-impl/guide/loader-eca-oauth-pkce.html),
[OAuth endpoints](https://help.salesforce.com/s/articleView?id=xcloud.remoteaccess_oauth_endpoints.htm&language=en_US),
[enhanced domain formats](https://help.salesforce.com/s/articleView?id=sf.domain_name_url_formats.htm&language=en_US&type=5).
