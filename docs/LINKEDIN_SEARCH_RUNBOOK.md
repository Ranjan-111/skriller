# LinkedIn connected search

The optional `SKRILLER_PUBLIC_LINKEDIN_IMAGE` selects an immutable isolated worker.
The normal indexed LinkedIn route remains available when this setting or an
eligible owner session is absent. No actual environment setting was enabled by
the implementation batch.

The worker image copies the acquired LinkedIn backend at
`f1ba6aa87234526cf22812e59233e0c619073529`, including its notices and source
manifest, over the existing reviewed browser image. Build without network:

```sh
docker build --network=none --pull=false -f infra/egress/Dockerfile.linkedin -t skriller-linkedin-local .
docker image inspect skriller-linkedin-local --format '{{.Id}}'
```

Use the resulting immutable image ID for a controlled deployment. A session
connection must be created by the initiating workspace owner through the existing
connection API with source `linkedin`, auth kind `session`, both `read` and
`discover` scopes, and the `session_cookie` credential. Credentials remain in the
encrypted connection store and private runner file; no cookie belongs in the
job prompt, command arguments, frontend storage, or this runbook. The worker
uses an ephemeral browser context and never opens a host browser profile or
starts the acquired backend's login/import/daemon services.

Each operation uses the copied single-attempt capture with a typed people/post
search URL. The worker allows bounded HTTPS GET/HEAD requests to the selected
LinkedIn/static hosts, blocks other navigation, writes, downloads, service
workers and WebSockets, and applies an 80-request ceiling. The existing guarded
network, browser capacity, job deadline, cancellation, source switches and
post-execution credential checks remain authoritative. A failed connected
attempt does not silently retry through indexed discovery. Checkpoint replay
does not open a new browser; old connection references do not rebind to a new
session.

Search page text is not aligned to individual references. The durable discovery
adapter therefore retains only each link and its own label as `linkedin_mcp` /
`search_reference`. `platform_reference.access` is
`connected_search_reference_only`; direct profile reading is `not_attempted`
and subject identity is `unknown`. This is separate from Exa indexed references
and from the later SKR-060 profile/post-read ticket. Both search operations are
available through the typed adapter; ordinary lead discovery uses people search.

The installed worker has passed people/post extraction against synthetic HTML
with Docker networking disabled. Real account authorization, session lifetime,
source coverage, filters, rate limits, provider/commercial acceptance and hosted
deployment remain unverified and user-deferred. An expired or invalid LinkedIn
session needs owner reconnection; no automatic session renewal is claimed.
Frontend handling of the new reference contract is the next allocated Luna batch.

## Resource reads (SKR-060)

The same immutable image now supports separate typed `read_profile`, `read_company`
and `read_post` requests through `linkedin_resource_read`. Targets are explicit
profile slugs, company-about slugs and numeric activity/UGC post IDs; self/profile
aliases, contact overlays, arbitrary URLs, query parameters and fragments are
refused. Single-attempt acquired capture returns one resource section, not proof
of person identity or complete profile coverage. Missing/private contacts remain
unavailable. Source exception types yield safe auth/access/rate-limit/not-found
codes without raw diagnostic output.

Fresh native discovery records its owner connection and credential generation.
Collection requires that exact binding and rechecks it before saving private
evidence. Rotation or expiration requires reconnection and a fresh run; there is
no cookie auto-renewal or implicit old-checkpoint rebind. Private evidence uses the
existing retention/erasure pipeline and is never placed in the public response
after expiry. The optional extraction stage uses restricted LinkedIn presets,
source quotes and the copied graph/model ledger. Observations stay unverified.

`linkedin_read.resource` identifies the actual read section and its limitations.
The old discovery-only platform notice is suppressed after a successful resource
read (including when its retained body later expires); discovery provenance stays
on the result. The new strict client/view remains the next frontend batch.
Account-backed field/coverage and hosted acceptance remain user-deferred.
