# CRM and billing destinations

Decision recorded 2026-10-17, before provider-specific implementation.

The user delegated CRM selection based on global adoption and selected Stripe
for global payments plus Razorpay for India.

## First CRM: Salesforce

Salesforce reports IDC ranked it first in CRM for the thirteenth consecutive
year, with 20.0% of 2025 CRM revenue. That supports selecting it for established
global sales organisations. This measures revenue share, not customer count;
it cannot establish which integration will generate the most Skriller revenue.
Validate customer demand before adding a second destination.

Source: https://www.salesforce.com/news/stories/idc-crm-market-share-ranking-2026/

Lead sync uses explicit field mappings and the existing qualified-export path,
which includes the copied ScrapeGraph-AI JSON exporter. Required LastName and
Company must be evidence-backed; no name splitting or company invention.
Professional email remains subject to existing publication/contact checks.
Near matches retain their literal classification in `Skriller_Fit__c` and never
map to Salesforce Lead Status. Unknown fields are omitted, not sent as null.

The destination must provision `Skriller_Entity_ID__c` as a **unique external ID**
text field and `Skriller_Fit__c` as a compatible text field. Tenant/entity hash
identity stays stable across retry and plan revision. PATCH targets the native
external-ID endpoint, using the explicitly pinned supported REST v66.0 contract.
Custom fields, permissions, API access and actual org behaviour still require
sandbox verification. Mock responses prove request contracts, not remote dedup.

Reference: https://developer.salesforce.com/docs/platform/api-rest/guide/dome-upsert.html

## Billing: Stripe and Razorpay

Use separate configured secrets and account/mode bindings. Verify the raw body
before parsing; keep a small durable inbox containing hashes and reconciliation
hints, not payment details. Never trust client checkout success or a workspace
ID from provider metadata to grant access.

Stripe signatures have a five-minute delivery timestamp tolerance. Multiple v1
signatures support rotation. Razorpay signs the raw body without a signed
delivery timestamp; a body hash provides replay identity independently of its
unsigned event-ID header. Both require durable deduplication and current-state
subscription reconciliation. Event creation timestamps cannot order all events.

References:

- https://docs.stripe.com/webhooks
- https://razorpay.com/docs/webhooks/validate-test/

The inbox has no tenant application grants. Operator-owned bindings, serialized
current-state reconciliation, bounded catalog inputs and an independent DB
paid-access check are now implemented. Workspace owners can still pause their
workspace, but cannot bypass provider cancellation/expiry by re-enabling it.
Each provider read refreshes access for at most fifteen minutes or the paid
period end. Deployment must supply a bounded periodic refresh worker and
persistent reviewed catalog configuration before activating payment webhooks.
No billing route is enabled by these foundations.

Prices, allowances, renewals, refunds and tax policy are not invented here.
The PRD allows a capped pilot; recurring credit resets must not be inferred from
each received payment event. Both providers must share one workspace billing
authority to prevent duplicate allowances.

Reviewed current-state contracts:

- https://docs.stripe.com/api/subscriptions/retrieve
- https://docs.stripe.com/api/subscriptions/object
- https://github.com/razorpay/razorpay-python/blob/master/documents/subscription.md
