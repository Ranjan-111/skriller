# Instagram and Facebook backend review

SKR-085/086 are locally implemented, pending external acceptance. Both routes default
off; configuration is not proof of live access.

## Reuse and isolation

OpenCLI commit `e6174a952c763a836a9bb0dd2f097d2962b3876b` is preserved unchanged in
`third_party/external/opencli` (2,343 files). Five selected read modules are copied
into `src/skriller/_vendor/opencli`, with Apache-2.0 attribution, original/adapted
hashes and modification notices. Instagram search/profile adaptations reject private
or unknown visibility, preserve missing counts as null and verify the requested handle.
Facebook search/profile and the shared response reader are unchanged.

`scripts/build_social_read_scripts.mjs` derives the static runtime scripts from the
actual copied functions. The closed build/fixture loader allows only those modules;
it is trusted tooling, not a production security sandbox. Production runs Python and
Playwright-compatible isolated browser workers without Node, a host browser, daemon,
global CLI registry, write operations or account discovery.

## Product integration

The optional pinned `SKRILLER_PUBLIC_SOCIAL_IMAGE` enables prepared executors. Session
credentials are workspace-owned and restricted to the initiating owner, source,
operation, scopes, generation and expiry. Facebook requires user ID plus session
cookie; Instagram requires its session cookie. Read and discovery permissions are
separate. Cancellation, revocation, kill switches and generation fences apply before,
during and after dispatch. No automatic cookie renewal or implicit reconnect occurs.

Discovery checkpoints preserve native provider/reference provenance without retrying
through an indexed route on native failure. Profile collection binds the original
credential generation. Instagram reserves up to three API attempts and reconciles
successful primary reads to one; Facebook captures bounded headers with zero API
requests. Network requests seen include blocked attempts, not billed wire calls.
Private evidence bodies and raw views expire after seven days; erasure and source-body
expiry remove duplicated raw view attributes too. Social observations do not create
person/company identities, contact details, buying intent or owner analytics.

The client accepts aligned typed observations, offers both optional sources, and
renders partial coverage, unknown counts/identity and Facebook's original count
wording. JSON/CSV source exports retain provenance while excluding raw profile bodies.

## Evidence and remaining limits

`completions/SOCIAL-READ-UPSTREAM-LOCAL.json` records 10 upstream synthetic scenarios;
`completions/SOCIAL-READ-ADAPTED-LOCAL.json` records 13 adapted scenarios. Actual copied
JavaScript executes against offline DOM/fetch fixtures; source calls are zero. The
reports include source/code hashes and do not close live acceptance.

Related backend checks: 228 distinct checks passed across the initial run and one
recovered native RabbitMQ handshake retry. A later focused 57-check run verified the
final license notices, hashes, generated scripts and worker contracts (overlapping,
not additive). Eighteen changed Python modules passed MyPy. Container checks are
explicitly user-deferred; the social Dockerfile has not been built or validated.

Live account access, hosted isolation, platform/operation rights and rate behavior
remain unverified. Facebook's conservative GET-only policy may prevent SPA rendering
that needs POST/GraphQL; that requires live acceptance before any coverage claim.
Facebook named profile/header reads do not imply group, post or arbitrary page reads.
Session expiry still requires owner reconnection. No source account or host session
was used in this batch.
