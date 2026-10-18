# Billing operator services

These services are separate from the tenant HTTP API and remain disabled unless
explicitly started. The normal research worker never receives billing operator
database credentials. Hosted deployment remains user-deferred.

## Approved monthly catalog

| Plan | Stripe / USD | Razorpay / INR | Runs per billing month | Results per run | Sources per run |
| --- | --- | --- | --- | --- | --- |
| Starter | $29 | ₹2,499 | 50 | 25 | 3 |
| Pro | $79 | ₹6,499 | 200 | 100 | 5 |

The user approved these values on 2026-10-17. Source limits do not enable
unavailable connectors. All monetary API values use integer cents/paise.
No prices or plans have been created in an actual provider account yet.

`billing/plans.py` produces the reviewed native create payloads.
`billing/provisioning.py` persists creation intent before POST, verifies the
provider receipt, and returns an existing ready receipt on retry. Stripe gets
a stable native idempotency key. Unknown/crashed writes require operator
reconciliation, especially because Razorpay plan creation cannot be blindly
retried without risking another plan. No card is charged by plan provisioning.

References: https://docs.stripe.com/api/prices/create and
https://razorpay.com/docs/api/payments/subscriptions/create-plan/

## Explicit configuration

Keep the operator JSON in ignored `.runtime/billing.json`, mode 0600 and owned
by the service user. Symlinks, shared permissions, oversized files, duplicate
endpoints and unknown fields are rejected. The reader reuses the copied
Agent-Reach bounded no-follow file helper. Exceptions and configuration reprs
do not include credentials.

Top-level fields: `operator_database_url` (dedicated trusted operator Postgres
connection), and `endpoints` (one to eight entries). Each entry declares:

- `provider`: `stripe` or `razorpay`.
- `account_id`: null for direct Stripe; explicit account for connected Stripe
  or Razorpay. It is deployment configuration, never a webhook argument.
- `live_mode`: false for sandbox validation. Key mode must match.
- `webhook_secret`, `api_key`, and Razorpay `api_secret`.
- `stripe_version`: explicitly reviewed API version for Stripe.

Optional top-level `checkout` configuration enables the owner checkout routes:

```json
{"firebase_project_id":"your-firebase-project","return_origin":"http://localhost:3000"}
```

Use the same Firebase project as the web app. `return_origin` must be an exact
origin with no path/query/credentials, HTTPS except for local loopback development.
It controls both the fixed return URLs and browser CORS. The service verifies
normal Firebase bearer tokens and independently checks workspace owner membership;
source credentials, provider keys and the operator database URL stay server-side.
Configure exactly one checkout account per provider. Omit `checkout` to leave all
customer routes disabled. No configuration or listener was enabled during testing.

Do not commit a populated configuration or pass credentials in command arguments.
Test keys may be supplied in ignored local `.env` for local operator setup;
they are not automatically used or copied into the tenant app.

## Commands

After migrations and private configuration are ready, these are explicit
operator commands; none was launched persistently during development:

```sh
uv run python -m skriller.billing_runtime provision --config-file .runtime/billing.json
uv run python -m skriller.billing_runtime once --config-file .runtime/billing.json
uv run python -m skriller.billing_runtime worker --config-file .runtime/billing.json
uv run python -m skriller.billing_runtime serve --config-file .runtime/billing.json
```

`provision` creates Starter and Pro in each configured account, recording actual
native IDs only after a verified response. `once` performs at most ten actions:
due reference lookups first, then due workspace reconciliations with any remaining
budget. A resolved reference is reconciled on a later available action. `worker`
repeats the bounded scan every ten seconds. `serve` binds
127.0.0.1:8011 by default and exposes
`POST /webhooks/{provider}/{account_scope}` and the opt-in checkout routes below.
Configure TLS and ingress controls
before hosted use. Public docs/OpenAPI/access logs are disabled for this service.
Do not mount it on the tenant app or start it with the restricted app DB role.

Existing manual subscription bindings still require operator action. Initial
checkout can establish its own binding only after the worker verifies the native
receipt as described below. A plan receipt or client return alone never grants
access. Actual provider sandbox acceptance remains pending.

## Initial customer checkout

All routes are owner-authenticated and return `Cache-Control: no-store`:

- `GET /v1/workspaces/{workspace_id}/checkout`: approved offers in integer
  cents/paise, configured-plan readiness, current intent and `can_start`.
- `POST /v1/workspaces/{workspace_id}/checkout`: JSON `provider` (`stripe` or
  `razorpay`), `plan` (`starter` or `pro`), `idempotency_key` (16–100 URL-safe
  characters) and explicit boolean `opt_in: true`.
- `GET /v1/workspaces/{workspace_id}/checkout/{checkout_id}`: private current
  intent status and an unexpired provider link when ready.

Razorpay authorizes **12 monthly cycles**, approved by the user; each cycle has
the approved monthly price. Stripe uses a recurring monthly subscription without
an end date. No add-on, discount, trial or new price is silently created.
Remote plans must already have verified ready provisioning receipts. Checkout
uses native provider pages to collect customer/payment information; no email,
card or payment credentials are collected by these API routes.

Migration 0052 persists intent before the first provider POST, bound to the
initiating owner/workspace/provider/account/approved plan. Stripe also receives
a stable native idempotency key. The initial pilot allows one checkout intent
per workspace; a matching retry reuses its state, while another key cannot create
a second subscription. Lost/malformed creation receipts leave `uncertain` state;
process loss leaves `dispatching`. Neither state retries the POST automatically.
Ready links expire after 35 minutes and are restricted to the reviewed Stripe
or Razorpay host. Expired, uncertain, subscription-replacement and plan-change
workflows require operator reconciliation; they are not automated in this pilot.

Subscription callbacks containing a known server-created intent ID enqueue a
reference lookup. The worker retrieves the saved native session/subscription,
verifies its identity, account/mode, approved plan, quantity, intent marker and
expected subscription. Stripe additionally requires a complete paid session;
Razorpay must retain the approved 12-cycle count. An owner membership recheck
precedes binding. Arbitrary workspace claims or an unrelated callback cannot
establish authority. Binding/catalog setup and inbox handoff are atomic; the
binding starts disabled until a separate fresh paid/active subscription read
passes normal reconciliation. Restores clear archived checkout URLs and require
fresh provider proof to resolve known receipts.

The backend-only OpenAPI contract is `docs/contracts/billing-openapi.json`.
Export/check it locally with `scripts/export_contracts.py --service billing
--output docs/contracts/billing-openapi.json [--check]`; public API docs remain
disabled. The web checkout controls are the next Luna UI task.

## Runtime behaviour

Intake has a raw-body cap and wall timeout, requires exactly one signature
header and commits only verified, configured subscriptions. It resolves the
workspace from the saved authority and ignores webhook workspace metadata.

The worker commits an attempt before provider I/O, holds a per-workspace session
advisory lock, and uses the same workspace/policy serialization for actual state
updates. Failed reads back off, stop after five attempts, and quarantine work.
Quarantined work is not silently replaced with endless refresh events. Other
due workspaces remain eligible. A worker crash cannot erase consumed attempts.
Native subscription reads are safe to retry; plan creation is treated separately.

Periodic refresh occurs after five minutes, without requiring an external event.
Each successful read grants at most fifteen minutes or the paid period end.
Absent or failing refresh therefore expires access. Owner pause settings and
lower run limits remain separate from provider access.

Monthly catalogs require verified start/end dates from the current subscription.
The quota counter uses immutable admissions within `[period_start, period_end)`.
Event delivery and repeated payment events do not reset the counter. Earlier
periods remain stored. Regressing provider windows are rejected. Trial/manual
pilot policies retain their original lifetime accounting until explicitly bound
to a monthly catalog. Backup restore disables archived paid access and requires
fresh reconciliation.

Refund/dispute event policy currently pauses access on a classified full refund
or open/lost dispute. Partial refunds preserve access only if the fresh provider
read remains active and paid. A later refresh may restore access only after a
fresh active/paid read. Customer-only events must resolve to one configured
workspace; ambiguity fails closed. Migration 0051 adds an operator-only reference
queue for Stripe charge-only and Razorpay payment-only disputes. Ingress verifies
the signature/account/mode and commits only the event hash, normalized action and
reference ID, without provider I/O or raw payment data. The worker uses fixed
provider GET endpoints, validates returned identity/mode, and resolves only a
unique configured customer/subscription in the same provider account. Missing
or ambiguous identities retry with persisted backoff and quarantine after five
attempts. Session advisory locks prevent simultaneous lookups, and each attempt
commits before I/O so process loss cannot erase it. Resolution and subscription
inbox insertion commit together; only normal reconciliation changes access.

Pending: web checkout controls, provider sandbox acceptance, and any production
tax/renewal changes beyond these approved monthly prices. Initial checkout backend
is locally verified; this is not a complete self-service subscription-management
product. No live billing, provider keys or customer
payment data were used by the development tests.
