# Skriller: product requirements

Version: 0.2 — proposed implementation baseline  
Date: 12 October 2026  
Product name: Skriller (working name; branding is undecided)  
Companion document: [Technical stack and architecture](TECH_STACK.md)  
Delivery backlog: [Implementation tickets](IMPLEMENTATION_TICKETS.md) · [Source reuse map](REUSE_MAP.md)  
Original input: the brainstorm transcript previously named `Branch • Modern AI Web Scraping Tools.md`. It has been removed from the current checkout; its requirements are captured in this PRD.

This document specifies a new product. No application, connector, benchmark, or production integration has been implemented or validated yet. Requirements, initial operating limits, and performance targets below are proposed engineering decisions, not claims of existing performance.

## 1. Product decision

Build a prompt-first lead-generation and research assistant. A user describes who or what they are looking for; the product discovers candidates, collects source evidence, resolves identities, evaluates fit, and produces structured results. Users refine results through conversation and export usable records.

Scraping infrastructure is an internal capability. The customer buys relevant, explainable research and usable prospect information. The first release is a web application with background workers, usable locally during development and deployable as a hosted pilot.

LinkedIn is the primary requested source for professional discovery. Reddit is a launch priority for discussion and demand research. Company websites, web search, public directories, GitHub, RSS, and public YouTube information complement those sources. Instagram, Facebook, X, and additional platforms remain explicit roadmap items.

Platform inclusion does not establish unrestricted access. Every connector must distinguish discovery, public reading, authenticated reading, owner-only data, and commercial usage requirements. Known restrictions are recorded as operating dependencies; they are not erased by stealth fetching. YouTube private analytics requires owner authorisation. A working startup cannot base an access guarantee on the assumption that every restriction can be bypassed.

## 2. Fixed product principles

| Decision ID | Baseline decision |
| --- | --- |
| D-01 | Prompt is the primary input. No mandatory prospect-filter form. |
| D-02 | Lead discovery and research are two modes of one product and share evidence and entities. |
| D-03 | LinkedIn and Reddit remain in scope; their production access is tested early. |
| D-04 | Copy relevant existing code and dependency/test closure from the supplied Scrapling, Agent-Reach, and ScrapeGraph-AI snapshots into attributed local source trees, then adapt behind product interfaces. Do not independently rewrite supplied feature logic. |
| D-05 | Cheap deterministic methods precede expensive browser or LLM work where appropriate. |
| D-06 | Source-specific routing happens before generic fallback. |
| D-07 | Every accepted factual field and factual research claim has source evidence. |
| D-08 | Missing, conflicting, stale, and inferred information remains distinguishable. |
| D-09 | All jobs have explicit limits, cancellation, recovery, and cost accounting. |
| D-10 | Minimise cost; do not promise permanently free infrastructure or universal access. |

These decisions are the default for implementation. D-04 reflects the user's subsequent copy/adapt instruction and supersedes a package-only reuse preference. Changes require a short decision record with the affected requirement IDs, reason, alternatives, cost/reliability impact, and acceptance-criteria changes. Routine implementation details that preserve these decisions do not require another product decision.

## 3. Users, jobs, and boundaries

Initial customer hypothesis: small B2B founders, agencies, and sales/research teams that manually discover prospects and investigate whether they match an ideal customer profile. Validate this hypothesis through pilot usage; it is not established market demand.

Primary jobs:

1. Find people or companies matching a described professional profile.
2. Research an individual or organisation across multiple sources.
3. Identify public signals relevant to a business offering, including hiring, product launches, and stated needs.
4. Investigate relevant Reddit discussions and distinguish an expressed problem from a confirmed buying intention.
5. Refine, save, refresh, and export evidence-backed results.

Initial supported outputs: company, person, creator, discussion, and research report. A discussion or anonymous account must not automatically become a named sales lead.

Outside the first release: sending email/DM outreach, posting or interacting on social platforms, a general-purpose scraping API sold separately, a complete CRM, unlimited crawling, autonomous execution of arbitrary code, and a universal people/contact database. Competitor pricing and job research are supported through the common research workflow; separate specialist products are deferred.

No feature promises exhaustive discovery of all people, access to hidden contact details, private third-party analytics, or guaranteed circumvention of every protection.

## 4. Prompt-first customer experience

### 4.1 Entry and discovery

The home screen presents one prompt composer, example prompts, recent conversations, and optional compact controls for result count, sources, freshness, and execution budget. A source connection is configured once in settings when required; it is not a mandatory form on every search.

Example prompt:

> Find 25 founders of fintech companies in Bengaluru. Prioritise companies with evidence of recent engineering hiring. Include LinkedIn profile references, company websites, publicly listed business contacts, and why each matches.

The planner converts the request into a typed, versioned plan and shows a short plain-language interpretation. For an unambiguous request, execution begins under the workspace's existing limits. Ask a conversational clarification when ambiguity changes the search substantially, such as whether a city refers to company headquarters or a person's location. A spend increase beyond the existing budget needs an explicit user choice; elapsed time is not approval.

The interface streams genuine stages and counts: discovering, reading sources, qualifying, ready to review. It must not fabricate precise progress percentages, success counts, or completion estimates.

### 4.2 Results and research

Results show name, company/role where available, source references, fit explanation, contact availability, freshness, and evidence status. A detail panel shows individual claims and sources. An alternative discussion view shows topic, stated problem, author handle, date, excerpt, and relevance.

Users can say “only companies hiring now”, “research the first five”, “exclude agencies”, “find similar companies”, or “explain why this person is included”. Every refinement creates a new plan revision. Existing evidence is reused where suitable; edited criteria trigger reevaluation rather than silently changing old results.

Research responses cite actual evidence. Separate observed statements from interpretations. Suggested buying signals must not be represented as proof that the person will buy.

### 4.3 Partial and unavailable results

Show discovered profile references even when a full profile cannot be retrieved, labelled as references with limited evidence. Search snippets are discovery evidence, not automatically current profile facts. Display how many candidates were discovered, evaluated, accepted, rejected, or unavailable.

Example: “Found 18 candidates; 9 meet the supported criteria; 4 need more evidence; 5 sources could not be read.” If the user asked for 25, do not pad the output with weaker results without explicitly labelling a separate near-match group.

Source setup and failures use concise product language: “Reconnect this source”, “Source temporarily unavailable”, or “This field is not available”. Technical diagnostics remain in an operator view.

## 5. Scope and platform capability matrix

P0 means required for the first hosted pilot. P1 means the next release after P0 acceptance. P2 means named expansion, not an implementation commitment for the first release.

There are two separate statuses: **engineering readiness** (planned, implemented, tested) and **operational readiness** (experimental, available, needs connection, needs access agreement, rate-limited, unavailable). A connector is not production-ready until both statuses support the advertised operation. All currently begin as planned/unvalidated.

| Source | Phase | Intended capabilities | Data/access distinction |
| --- | --- | --- | --- |
| LinkedIn | P0 | Discover profile/company/post references; extract available professional facts and posts; qualify against the prompt; attach evidence | Direct search/read availability depends on the selected access route. Approved API, licensed data, source-permitted public reading, and permitted imports are distinct routes. Account login alone does not remove restrictions. |
| Reddit | P0 | Discover relevant communities/discussions; read available posts/comments; classify stated needs; link related companies when explicitly evidenced | Commercial Data API use needs a separate agreement under current terms. Anonymous identities stay anonymous. Public-web/search discovery does not guarantee complete discussion coverage. |
| Company websites and directories | P0 | Company facts, team pages, service descriptions, published contacts, hiring pages, structured data | Per-source access and crawling rules; browser rendering when required. |
| Web search | P0 | Candidate discovery, domain-restricted queries, query expansion, supporting sources | Provider-specific coverage, operators, quotas, storage rights, and pricing. No completeness guarantee. |
| GitHub | P0 | Public organisation/repository evidence and explicitly published professional profile information | Public/API access within applicable terms and limits; private repositories require proper access. |
| RSS/Atom | P0 | Public feed ingestion, dated updates, linked source discovery | Preserve attribution and feed-specific constraints. |
| YouTube public data | P0 | Public channels/videos, permitted metadata, available transcripts, creator research | Transcript availability varies. Public counts are not private analytics. |
| YouTube owner analytics | P1 | Connected owner's permitted channel reports and date-range summaries | Owner OAuth, supported scopes, quotas, revocation, and report availability. |
| X | P1 | Available professional/company references and relevant public discussions | API/provider/session route must be assessed for the specific operation. |
| Instagram/Facebook | P1 | Available business/creator/company information and public content research | Public, business-account, authenticated, and private data are separate capabilities. |
| Jobs, pricing, industry directories | P1 | Source-specific extraction presets and change research | Use shared pipeline; each source gets fixtures and capability definitions. |
| Bilibili, Xiaohongshu, regional networks and other sources | P2 | Additional adapters and language/source coverage | Evaluate independently; no “all platforms enabled” claim. |

LinkedIn and Reddit feasibility is a release-critical dependency. If a viable route cannot meet the advertised operation, keep the connector visible with its limitation, continue backend development, and revise the launch claim or resolve access before launching that claim. Do not silently substitute another source and call it LinkedIn coverage.

## 6. Functional requirements and acceptance criteria

### FR-01 — Prompt interpretation and planning (P0)

Extract entity type, geography, industry, role, company characteristics, must-have versus preferred criteria, requested fields, source preferences, freshness, exclusions, and budget into a validated plan. Detect unsupported requests and material ambiguities.

Acceptance: on a curated set of at least 50 representative prompts, at least 90% have correctly interpreted essential criteria under human review. Every plan has a revision, criteria provenance, execution limits, and source plan. Invalid plans cannot dispatch jobs. Unsupported criteria are visible, not silently dropped.

### FR-02 — Candidate discovery and search operators (P0)

Generate query variants, including Google-style dorking such as domain restrictions, quoted phrases, and exclusions where the provider supports them. Example: `site:linkedin.com/in/ "founder" "fintech" "Bengaluru"`. Use a search-provider adapter; preserve query, rank, URL, snippet, provider, and retrieval time. Google-specific execution is a replaceable route requiring its own provider/access decision; the operator syntax does not imply a free Google backend.

Acceptance: deduplicate canonical candidate URLs; record actual provider calls; cap expansion/pagination; stop on budget or result exhaustion. Operator conformance tests prevent claiming support for ignored operators. Search snippets carry a separate evidence type.

### FR-03 — Multi-platform adapters and diagnostics (P0 framework)

Provide one internal connector contract for search/discovery, read, capability inspection, health, and authentication status. Reuse Agent-Reach channel selection and diagnostics concepts and selected upstream tools. Isolate legacy CLI/MCP tools behind a typed adapter with fixed arguments, timeouts, output limits, and JSON validation.

Acceptance: every enabled capability passes connector contract tests, has an upstream/version record and known limits, and returns typed failures. A broken adapter can be disabled without disabling other sources. Setup must not run uncontrolled install/update scripts inside customer jobs.

### FR-04 — Fast fetching and low latency (P0)

Use Scrapling's HTTP/parser path for suitable pages. Reuse connections, cache appropriate data, limit unnecessary downloads, and dispatch bounded concurrent reads. Parser timing is recorded separately from network, queue, browser, extraction, and full-job latency.

Acceptance: return visible incremental results without waiting for the entire crawl; enforce response-size and timeout limits; benchmark on declared fixtures/hardware. Never advertise the upstream parser multiplier as an end-to-end product multiplier.

### FR-05 — Dynamic pages and anti-bot resilience (P0)

Support browser-rendered extraction and Scrapling stealth fetching, including its documented challenge-handling capabilities, on supported sources. Track block/challenge/empty-page detection, selected engine, attempts, elapsed time, and outcome. Support configured proxy providers and consistent sessions where needed; charge actual traffic and obey source-specific backoff limits.

Acceptance: a fixture requiring JavaScript can escalate from HTTP to a browser and extract the intended content. A challenge page cannot be mistaken for a successful profile. Persistent denial terminates with a specific reason and preserves partial results. Every alternate engine shares one job attempt/deadline budget. No rotation or browser fallback runs indefinitely, or overrides authentication and data-visibility boundaries.

### FR-06 — Adaptive element tracking and extraction repair (P0)

Persist source-scoped extraction templates and element fingerprints. Use exact selectors, adaptive matching, then bounded LLM-assisted repair where applicable. Check semantic anchors and field relationships, not just whether some text was found. Version candidate repairs and retain the old template until the repair passes fixtures or a defined review step.

Acceptance: on at least 20 changed-page fixtures plus adversarial wrong-element fixtures, correct repairs achieve at least 90% field accuracy; intentionally ambiguous matches are rejected or flagged. Measure silent wrong matches separately from missing fields. Private/session-derived templates are tenant-scoped.

### FR-07 — Prompt-driven schema extraction (P0)

Convert requested fields into a safe typed schema. Extract structured data (including JSON-LD), deterministic fields, then relevant cleaned text for AI fallback. Preserve useful embedded structured data before removing scripts. ScrapeGraph-AI provides an optional extraction implementation behind this contract.

Acceptance: all stored outputs pass strict schema validation; unsupported facts remain null with a reason; LLM-generated values without evidence cannot enter the accepted factual result. Arbitrary prompts cannot generate executable application code or unbounded schema depth.

### FR-08 — Authenticated sources and session lifecycle (P0 framework)

Distinguish app identity, provider OAuth, and source browser sessions. Maintain tenant-specific connections, permitted scopes, expiry, revocation, and reconnect state. Prefer scoped OAuth where an applicable integration supports it. A session-based adapter needs an explicit documented access route, secure storage, and a tested reconnect flow. Never pool customer accounts or session credentials across tenants.

Acceptance: session expiry pauses only affected tasks; reconnect resumes from a checkpoint; disconnect revokes/removes locally stored credentials and prevents queued reuse. Workers cannot read another tenant's connection. Browser automation cannot acquire data the account is not authorised to see.

### FR-09 — Evidence and research assistant (P0)

Attach source, excerpt/locator, collection timestamp, publication timestamp when known, extraction method, and observed/inferred status to fields and research claims. Answer follow-ups over relevant saved evidence, expanding research only when requested and within budget. Display conflicts rather than inventing resolution.

Acceptance: factual claims resolve to stored evidence IDs; the service verifies referenced evidence exists. Instructions embedded in retrieved pages cannot change the plan, access secrets, or initiate unrelated tool calls. Deleted or expired evidence is not cited as current.

### FR-10 — Identity resolution and deduplication (P0)

Normalise URLs/domains and use source-native identifiers plus corroborating information to link records. Do not merge people solely by name or companies solely by a similar brand. Preserve the reason for each merge and allow reversal.

Acceptance: same-name/different-company and same-brand/different-entity fixtures remain separate. Merge precision is at least 98% on the labelled evaluation set. Uncertain links remain suggestions. Suppressed entities are not reintroduced through another source URL.

### FR-11 — Qualification and relevance (P0)

Evaluate each essential criterion as matched, contradicted, or unknown. Use a transparent weighted preference score only after determining essential-criteria status. Keep score distinct from factual confidence. Intent signals identify explicitly stated problems and their dates; they are not consent to contact or guaranteed intent to buy.

Acceptance: an essential criterion with unknown evidence cannot be labelled a confirmed match. Every accepted result explains its match using evidence. Display confirmed matches and near matches separately. Target at least 90% qualification precision in the pilot benchmark.

### FR-12 — Contacts and freshness (P0)

Collect explicitly available professional/business contact channels. Keep email syntax, domain mail capability, ownership evidence, and any external deliverability result as separate checks. Guessing an email must not produce a verified contact; guessing is excluded from P0. Model freshness per claim and source, not only per conversation.

Acceptance: no email is called verified solely because of regex or MX checks. Refresh can supersede a role while retaining source history. A requested freshness threshold is enforced or labelled unknown.

### FR-13 — Exports, saved lists, and refinements (P0)

Save lists and export UTF-8 CSV, JSON, and JSONL. Include IDs, source references, evidence/freshness status, and a machine-readable schema version. Maintain organisation/person/discussion distinctions. Saved lists are snapshots with a refresh action.

Acceptance: export round-trip preserves Unicode, nulls, dates, and identifiers; CSV protects against spreadsheet formula injection; export ownership and suppression checks run server-side. Export files expire and are tenant-scoped. Refinements remain linked to the previous plan revision.

### FR-14 — Jobs, budgets, and recovery (P0)

Run long work outside web request processes. Support cancellation, pause/resume, bounded retry, per-source rate limits, deduplication, cost reservation, and checkpoints. Stream real progress from persisted events. Job-level deadlines apply to queueing and execution.

Acceptance: after worker termination, resume does not duplicate entities or logical charges. Cancellation prevents new provider calls, apart from already in-flight requests that cannot be cancelled. Provider billing for an interrupted request remains visible. Exhausted budgets return partial results with a reason.

### FR-15 — Workspace access and operator controls (P0)

Google sign-in through Firebase authenticates app users. Organisation memberships and permissions are enforced by the application. Include owner/member roles, per-workspace quotas, connector kill switches, redacted diagnostics, job metrics, and usage summaries. Payment automation is P1; a hosted paid pilot may use manual invoicing plus enforced entitlements.

Acceptance: tenant isolation is exercised for conversations, evidence, sessions, exports, jobs, and events. A source kill switch stops new tasks on that source while preserving finished work. User-visible cost summaries reconcile to the usage ledger within documented estimation uncertainty.

### FR-16 — Monitoring and integration expansion (P1/P2)

P1 adds scheduled source refresh, meaningful change reports, owner-authorised YouTube analytics, CRM/webhook exports, and additional named social adapters. Notifications are opt-in and sent only for relevant changes. P2 adds an MCP interface and regional sources after the shared connector contract is stable.

Acceptance: schedules do not double-run after restarts; webhook endpoints are validated, signed deliveries are retried with idempotency, and deleted/suppressed data is not re-exported. Each newly advertised platform operation passes the same readiness gate as P0.

## 7. Initial operating limits

These are configurable pilot defaults, not safe-request guarantees for every source. Connector limits can only make them stricter unless an operator explicitly changes the deployment configuration.

| Limit | Initial default |
| --- | --- |
| Requested results | 25; up to 100 per run |
| Search-provider calls | 20 per run, including pagination and query expansion |
| Discovered candidates evaluated | 300 per run |
| Fetch attempts | 200 per run; every engine/fallback/retry counts |
| Attempts for one URL | 3 total across methods, unless the job ends earlier |
| LLM calls | 40 per run, with a separate token/currency cap |
| Job wall-clock deadline | 20 minutes including queue time |
| HTTP request timeout | 20 seconds |
| Browser navigation deadline | 45 seconds within the remaining job deadline |
| Decoded page body size | 5 MiB; bounded streaming/decompression required |
| Fetch concurrency | 8 global HTTP tasks and 2 browser pages per pilot worker host |
| Same-source concurrency | 1 initially; source rules may require stricter limits |
| Same-source cadence | Source-specific minimum interval and published limits; no universal hardcoded “safe” delay |
| Active jobs per workspace | 2; remaining jobs queued with visible status |
| Per-job monetary cap | Deployment must set it before enabling paid provider calls; no implicit unlimited value |

Resource controls govern all traffic: browser assets, redirects, retries, APIs, and HTTP reads. Requested result count does not guarantee the backend will find that many accepted results within limits. Increasing result count does not silently increase spend.

## 8. Job states and failure handling

States: `planned`, `queued`, `running`, `waiting_for_connection`, `paused`, `completed`, `partial`, `failed`, `cancelled`. Use a separate stage field for discovering, collecting, extracting, resolving, and qualifying. `completed` means the plan ran to its defined end; actual count may be below the request after source exhaustion. `partial` means a blocking limit, outage, or interruption ended the plan with useful saved work.

| Failure | Expected handling |
| --- | --- |
| HTTP 429/quota response | Honour retry information, reduce activity, schedule within deadline; no immediate retry storm. |
| Temporary network error or provider 5xx | Bounded backoff; checkpoint and surface provider health. |
| HTTP 403/challenge page | Classify first; use an applicable configured alternative only within source and job boundaries. |
| Expired connection | Mark affected tasks waiting; show reconnect; do not erase unrelated results. |
| Unsupported field or private data | Leave unavailable with a reason; never infer it as observed. |
| LLM malformed output | At most one repair call if budget permits; otherwise typed extraction failure. |
| Changed DOM | Run validated adaptive/repair path; quarantine uncertain mapping. |
| Search results exhausted | Finish with actual count and coverage description. |
| Worker/browser crash | Recover leased tasks and checkpoints; isolate browser process. |
| Provider outage | Circuit breaker, per-capability status, partial results. |
| Cost cap or deadline | Stop dispatch; finalise ledger and partial outcome. |

## 9. Data contracts

Every tenant-owned row includes `workspace_id`; every mutable record has timestamps and a schema/version where needed.

Core records:

- `Workspace`, `Membership`, `Conversation`, `Message`: app identity and conversational context.
- `SearchPlan`: revision, entity type, essential/preferred criteria, exclusions, fields, sources, freshness, limits, and spend cap.
- `Job`, `TaskAttempt`, `JobEvent`: execution state, checkpoints, idempotency keys, typed outcomes, sequence numbers, and timing.
- `ConnectorCapability`, `SourceConnection`: engineering/operational status, operation, access route, version, scope, expiry, secret reference, and last health check.
- `Candidate`: source-native ID/URL, discovery query and provenance, first-seen time, and candidate type.
- `Entity`, `EntityLink`: person/company/creator/discussion identity and auditable links/merges.
- `Evidence`: source URL/provider, snippet-versus-page kind, excerpt/locator, collected/published dates, content hash, access context, storage reference, and expiry.
- `Claim`: entity, field, typed value, evidence IDs, observed/inferred status, conflict/freshness status, and extraction version.
- `Qualification`: plan revision, per-criterion outcome, preference score, reason/evidence IDs, and accepted/near-match/rejected status.
- `SavedList`, `Export`, `UsageEntry`, `BudgetReservation`, `Suppression`: snapshots, output control, provider costs, concurrency-safe budget accounting, and deletion/exclusion enforcement.

Typed plans and schemas must stay bounded. Do not use a free-form LLM response as the database schema or job instructions. Emails, source IDs, and social handles are stored as strings; null is not replaced with a made-up placeholder value.

Evidence-derived numeric scores are heuristics until calibrated. Do not label an uncalibrated LLM self-score “95% certainty”.

## 10. Quality, latency, and production targets

All targets are provisional acceptance gates and must be measured before being advertised. They apply to supported source operations under a declared test profile, not the entire internet.

Benchmark profile: 4 vCPU/8 GiB worker host, separate browser processes, warm supported-source cache where explicitly indicated, two active workspaces, fixed provider/model versions, and recorded network region. A local CPU-only model is evaluated separately and has no inherited cloud-model latency target.

| Metric | Proposed pilot target and measurement |
| --- | --- |
| Prompt interpretation | At least 90% essential-criteria correctness on 50 labelled prompts. |
| Field accuracy | At least 95% on at least 200 manually labelled records, stratified by source and engine. |
| Qualification precision | At least 90% of accepted results actually meet essential criteria on the labelled set. |
| Evidence coverage | 100% accepted factual fields and factual report claims have resolvable evidence. |
| Unsupported contact invention | Zero invented contacts presented as observed/verified in acceptance tests. |
| Merge precision | At least 98% on ambiguous and ordinary identity fixtures. |
| Job submission | p95 at most 1 second, excluding upstream plan-generation time. |
| Plan generation | p95 at most 10 seconds on chosen pilot model/provider. |
| First useful result | p95 at most 45 seconds on the declared accessible-source benchmark; unavailable sources reported separately. |
| 25-result run | p95 at most 5 minutes on that benchmark, if enough matching evidence exists within limits. |
| Cached deterministic extraction | p95 at most 50 ms for declared HTML fixtures at most 1 MiB; excludes network and adaptive repair. |
| Progress delivery | Persisted updates appear within 2 seconds while connection is healthy. |
| App API/UI availability | Initial operating objective 99.5% monthly; source/provider availability reported separately. No contractual SLA before measurement. |
| Cancellation | Dispatch stops within 5 seconds of accepted cancellation; bounded in-flight work may finish. |
| Recovery | No duplicate final records/logical charges after worker restart and duplicate queue delivery. |
| Backup | Pilot RPO at most 24 hours; demonstrated restore RTO at most 4 hours. |

Measure p50/p95 latency, acceptance yield, coverage, blocked/empty responses, adaptive repair failures, token use, queue wait, bandwidth, and cost per accepted result by source. Report the denominator for all success rates; “accessible pages only” must never hide total discovery/access failure.

Evaluation suite includes supported static/JS pages, changed DOM, conflicting facts, same-name people, expired sessions, empty results, challenge pages, 429s, quota exhaustion, prompt injection, SSRF URLs/redirects, tenant boundaries, cancellation, duplicate delivery, budget races, and deletion propagation. Fixtures and live source probes are separate; most CI should not scrape external sites.

## 11. Security and data lifecycle

Run browsers and external connector tools with restricted privileges and egress, without application/provider secrets unrelated to the task. Do not run user-generated code or arbitrary shell commands. Treat retrieved content as data, not instructions. Source tools are read-only for this product.

Validate all user, search-result, and page-discovered URLs. Deny local/private/link-local/metadata addresses, unsafe schemes and ports, DNS rebinding, and unsafe redirect destinations. Apply equivalent network controls to browser subresources and external tools. Public URL validation in Python alone does not secure browser traffic.

Use tenant checks and database policies for conversations, jobs, evidence, connections, exports, event streams, caches, and adaptive templates. Encrypt sensitive credentials; redact cookies, tokens, and unnecessary personal content from logs. App login is distinct from target authorisation. No shared credential pool.

Initial retention defaults: transient fetched bodies up to 7 days where storage is permitted; evidence excerpts, claims, and saved results up to 90 days, configurable to shorter source requirements; export links expire after 24 hours. Store only the minimum source content needed and allowed. Retention is not a licence to store prohibited content.

Deletion removes active records/objects and prevents replay from caches/tasks. Maintain minimal suppression identifiers where appropriate to prevent reappearance. Backups expire under a documented policy within 30 days; restored data must replay deletions/suppressions before serving traffic. Aggregate usage can remain without source content or direct identifiers. Connector disconnection revokes tokens where supported and destroys stored secrets.

## 12. Cost model and commercial operation

Aim for no additional paid subscriptions in local fixture-based development. Live search, hosting, provider calls, platform access agreements, proxies, storage, and support may incur costs. Free allowances are optional reductions, not promised permanent capacity.

Track:

`job_variable_cost = search + network/proxy + browser/compute allocation + LLM + enrichment + output/storage allocation`

`cost_per_accepted_result = job_variable_cost / accepted_unique_results`

If accepted count is zero, cost per result is undefined; still report the job's spend. Track review/support effort separately. A lead may require several page reads, and failures may consume billable traffic.

Illustrative traffic scenario, not a price quote: 100 candidates × 3 page attempts × 0.5 MB average transfer = 150 MB before extra browser assets/provider overhead. At a 30% acceptance yield, that is 30 accepted results. Real traffic and yield must be measured; proxies do not have to be enabled for sources that work directly.

Commercial baseline: capped workspace usage with included research runs/results and explicit metered limits. No unlimited plan in P0. Subscription amount, included limits, and margin target remain decisions for pilot evidence. Trial jobs have enforced resource limits. Manual invoicing is acceptable during a small pilot; billing/entitlement enforcement is still required.

Parallel tasks reserve estimated budget transactionally before dispatch. Actual usage reconciles reservations. Count provider retries and failed requests when billed. If the next bounded call could exceed the remaining cap, do not dispatch it. Mark costs estimated versus confirmed and include any documented provider billing uncertainty.

## 13. Delivery phases and completion gates

| Phase | Deliverables | Completion gate |
| --- | --- | --- |
| A: source and dependency feasibility | LinkedIn/Reddit access experiments; exact capability inventory; upstream pins/licences; search-provider operators/storage decision; model/schema trial | At least one viable route for each advertised launch operation, measured limits/costs, and a compatibility lockfile. Any unavailable operation remains explicit and blocks its launch claim. |
| B: complete prompt-to-result slice | Prompt plan, web discovery, HTTP fetch, evidence, qualification, streamed result, CSV/JSON, persistence | An actual prompt discovers candidates without requiring an uploaded list; results cite evidence; cost/deadline controls work. |
| C: resilience and launch sources | LinkedIn/Reddit adapters, browser/stealth path, adaptive extraction, session framework, selected GitHub/RSS/YouTube capabilities | Contract and fixture tests pass; live probes document usable operations and gaps; no silent wrong-page/identity acceptance. |
| D: hosted pilot hardening | Firebase identity, tenant isolation, worker recovery, cancellation, quotas, diagnostics, retention, backups, security | Quality/performance suite and recovery/restore drills pass; support/operator runbook exists. |
| E: pilot and refinement | At least 3 prospective customer workspaces, repeat research tasks, feedback, margin/retention measurement | Demonstrated repeated value and credible operating cost; do not infer market fit from a single successful scrape. |
| F: expansion | P1 owner analytics, monitoring, social adapters, CRM/webhooks; P2 regional sources/MCP | Each operation independently meets source-readiness and product acceptance gates. |

Phases can overlap where independent, but live source feasibility cannot be postponed until after launch. No delivery date is promised before the feasibility findings establish scope and capacity.

## 14. Risks and explicit decisions still needed

| Risk | Response/owner role |
| --- | --- |
| LinkedIn/Reddit access cannot support the promised workflow | Connector engineer documents route and failure; product owner resolves access or adjusts the claim. These platforms remain in scope. |
| Low candidate coverage | Compare search/provider/source yield, record unknowns, avoid completeness claims. |
| Unreliable contact availability | Sell qualification/research value; expose unavailable contacts; consider separately evaluated enrichment later. |
| Silent adaptive extraction error | Semantic validation, versioned repair, adversarial fixtures, operator rollback. |
| Source content induces unsafe agent actions | Typed tools, evidence-only prompts, egress restrictions, secret separation. |
| Browser/LLM costs exceed margin | Budgets, deterministic extraction, caching, concurrency limits, source-level economics. |
| Upstream update breaks integrations | Pinned releases, isolated environments when needed, contract tests, controlled upgrades. |
| Excessive platform scope | Named phased matrix; a new operation gets an ID, budget, fixtures, and readiness gate. |

Open decisions: initial customer niche; launch geography/languages beyond English prompts; deployment region/provider; viable LinkedIn and Reddit access agreements/routes; search-content storage rights; paid model/provider configuration; currency cap; pricing; permitted retention per source. Baseline assumes English prompts and UTF-8 source content, a small hosted B2B pilot, and no outbound outreach.

These unknowns do not prevent local fixtures, core planning, evidence storage, or connector interfaces from being built. They do prevent claiming unvalidated production access or capacity.

## 15. Scope control and definition of done

Before adding a feature, identify its user job, requirement ID, phase, measurable acceptance criterion, source dependencies, cost impact, and deletion/security implications. Features without these stay in the backlog. Do not add another orchestration framework, database, or UI surface merely because an upstream tool uses it.

P0 is done when FR-01 through FR-15's P0 scope is implemented, the declared quality/security/recovery gates pass, advertised source operations have a viable access route, and pilot customers can complete prompt → discovery → research → refinement → export. P1/P2 features are not necessary to claim P0 completion; unavailable P0 source claims are not quietly waived.

## 16. Source notes

Sources checked on 12 October 2026. Source terms, capabilities, prices, and quotas can change; recheck before implementation and release. Strategic decisions and numeric product targets above are proposals.

1. [Scrapling repository and parser benchmarks](https://github.com/D4Vinci/Scrapling): fetching/parsing/adaptive framework and BSD-3-Clause licence; benchmarks are not product throughput guarantees.
2. [Scrapling stealth fetching documentation](https://scrapling.readthedocs.io/en/latest/fetching/stealthy.html): documented browser and challenge-handling options, not proof of universal access.
3. [Agent-Reach upstream](https://github.com/Panniantong/Agent-Reach): source routing/setup/diagnostics and upstream tool integration. The brainstorm's 404QAQ link is a separate fork.
4. [ScrapeGraph-AI](https://github.com/ScrapeGraphAI/Scrapegraph-ai): AI extraction library, distinct from the unnamed Claude skill and from the provider's hosted API.
5. [LinkedIn Profile API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/people/profile-api) and [User Agreement](https://www.linkedin.com/legal/user-agreement): restricted API access/data usage and scraping restrictions.
6. [Reddit Data API Terms](https://redditinc.com/policies/data-api-terms): current commercial API use requires a separate agreement. This does not define every possible public-web access route.
7. [YouTube Analytics reports](https://developers.google.com/youtube/analytics/reference/reports/query): authorisation required; separate from [public video search](https://developers.google.com/youtube/v3/docs/search/list).
8. [Brave Search API](https://brave.com/search/api/) and [query documentation](https://api-dashboard.search.brave.com/app/documentation/web-search/query): candidate search provider and query options; Google execution is a separate choice.
9. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing): free/paid availability and data-use distinction; free capacity is not the production assumption.

