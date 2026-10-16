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
native IDs only after a verified response. `once` scans at most ten due
workspaces. `worker` repeats the bounded scan every ten seconds. `serve` binds
127.0.0.1:8011 by default and exposes only
`POST /webhooks/{provider}/{account_scope}`. Configure TLS and ingress controls
before hosted use. Public docs/OpenAPI/access logs are disabled for this service.
Do not mount it on the tenant app or start it with the restricted app DB role.

Subscription binding and finite customer/plan catalog setup require explicit
operator action. The local customer checkout flow and provider sandbox approval
remain unfinished; a provider plan receipt alone does not grant access.

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
workspace; ambiguity fails closed. Standard Stripe dispute callbacks containing
only a charge reference, and Razorpay dispute callbacks, are not yet mapped into
the subscription inbox and therefore fail closed pending a durable reference
resolver.

Pending: authenticated checkout/customer lifecycle, durable dispute-reference
resolution, provider sandbox acceptance, and any production tax/renewal changes
beyond these approved monthly prices. No live billing, provider keys or customer
payment data were used by the development tests.
