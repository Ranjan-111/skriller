# Skriller implementation tickets

Version: 0.1 · 12 October 2026 · Implementation is in progress; [verified execution status](TICKET_STATUS.md) is authoritative.

96 tickets: 80 P0, 12 P1, 4 P2. All include verification scenarios; actual results are recorded per ticket in the execution status.

Related: [PRD](PRD.md), [stack](TECH_STACK.md), [source reuse map](REUSE_MAP.md), [machine-readable tickets](tickets.json), [reference hashes](REFERENCE_INVENTORY.json).

## How to execute this backlog

Validate ticket IDs, dependencies, PRD coverage, source/test paths, local links and reference hashes with `python3 docs/validate_delivery_plan.py`. This checks the plan; it does not run the future application tests.

Choose an unimplemented ticket only when its dependencies are complete. Source-feasibility tickets may run independently of most core product work; inability to validate access does not stop unrelated fixture-based implementation, but blocks claims of production source readiness. Ticket IDs are identifiers, not execution order; the dependency list is authoritative. SKR-096 is the dedicated production planner ticket and appears with the product-experience tickets.

Sizes: **S** targets up to 4 focused hours; **M** targets up to 8. These are rough planning sizes, not calendar promises. Split unexpectedly larger tickets instead of declaring partial work complete. External agreement/account/provider waits are separate. A platform ticket is one bounded adapter operation set; if the selected backend is larger, split by operation before coding.

For reused capabilities, copy the mapped supplied source and supporting dependencies/tests into the local third_party tree, then adapt. Do not independently reimplement its algorithm. Original product glue is appropriate only where the supplied projects have no equivalent; explain that boundary in the ticket completion note. The earlier package-only preference is superseded by this copy/adapt direction.

Normal ticket completion: scoped implementation, acceptance checks, relevant upstream regressions, product-boundary tests, genuine result report, provenance/modification log updates for copied code, and no unrelated changes. A test asserting that an internal function was called is not enough; check the expected user/domain outcome.

Live probes are opt-in, use a documented supported access route and explicit test credentials, and are separate from no-network CI. Missing credentials or unavailable access must be recorded as **not validated**, not passing. Never use real customer credentials or personal data as committed fixtures.

## Definition of done and test discipline

- Reused source origin, hash/licence and modifications are traceable; reference snapshots remain unchanged.
- At least one meaningful positive and one failure/boundary case apply to each implementation ticket.
- Database/queue/tenant behaviour is verified against real local services, not only mocks.
- Fixture-provider tests still use the actual copied parser/graph being integrated.
- Paid/network tests never run unexpectedly in ordinary CI; results distinguish pass, fail, skipped and unavailable.
- Every completed ticket records actual commands, relevant versions, outcomes and remaining limitations.
- A release needs journey/quality/recovery gates; individually passing units alone do not establish a working product.

## First work queue

Start with SKR-001, then source import tickets SKR-002–004, dependency lock SKR-005, local scaffold SKR-006, fixtures SKR-007 and CI SKR-008. Source feasibility SKR-009–012 should be resolved early. Then follow dependencies to the first full prompt-to-export gate SKR-067. LinkedIn/Reddit journey SKR-068 and hosted release gates SKR-075–079 are required before advertising the corresponding customer workflow.

## Index

| Ticket | Phase | Size | Task | Dependencies |
| --- | --- | --- | --- | --- |
| [SKR-001](#skr-001) | P0 | S | Register supplied snapshots and import provenance | None |
| [SKR-002](#skr-002) | P0 | M | Copy and package Scrapling source and baseline tests | SKR-001 |
| [SKR-003](#skr-003) | P0 | M | Copy and package Agent-Reach source and baseline tests | SKR-001 |
| [SKR-004](#skr-004) | P0 | M | Copy and package ScrapeGraph-AI with telemetry isolation | SKR-001 |
| [SKR-005](#skr-005) | P0 | M | Resolve local source dependencies and lock runtime environments | SKR-002, SKR-003, SKR-004 |
| [SKR-006](#skr-006) | P0 | M | Bootstrap web, API and local services | SKR-005 |
| [SKR-007](#skr-007) | P0 | M | Create labelled fixtures and no-network test harness | SKR-001 |
| [SKR-008](#skr-008) | P0 | M | Set up ticket-level CI and artifact reporting | SKR-006, SKR-007 |
| [SKR-009](#skr-009) | P0 | M | Validate LinkedIn backend route and acquire missing implementation | SKR-003, SKR-007 |
| [SKR-010](#skr-010) | P0 | M | Validate Reddit route and acquire missing implementation | SKR-003, SKR-007 |
| [SKR-011](#skr-011) | P0 | M | Validate search coverage, operators and provider terms | SKR-007 |
| [SKR-012](#skr-012) | P0 | M | Validate cloud/local models against copied extraction code | SKR-004, SKR-005, SKR-007 |
| [SKR-013](#skr-013) | P0 | M | Verify Firebase identity on API requests | SKR-006, SKR-007 |
| [SKR-014](#skr-014) | P0 | M | Create workspaces, memberships and row-level isolation | SKR-013 |
| [SKR-015](#skr-015) | P0 | M | Persist conversations and immutable plan revisions | SKR-014 |
| [SKR-016](#skr-016) | P0 | M | Persist entities, evidence, claims and qualifications | SKR-014 |
| [SKR-017](#skr-017) | P0 | M | Persist jobs, attempts, events and usage records | SKR-014, SKR-015 |
| [SKR-018](#skr-018) | P0 | M | Implement private evidence object storage | SKR-014, SKR-016 |
| [SKR-019](#skr-019) | P0 | M | Define typed plans, connector contexts and error schemas | SKR-015, SKR-017 |
| [SKR-020](#skr-020) | P0 | M | Implement canonical job state machine | SKR-017, SKR-019 |
| [SKR-021](#skr-021) | P0 | M | Dispatch jobs through transactional outbox | SKR-017, SKR-020 |
| [SKR-022](#skr-022) | P0 | M | Execute checkpointed idempotent worker stages | SKR-021 |
| [SKR-023](#skr-023) | P0 | M | Enforce shared source and worker capacity limits | SKR-022 |
| [SKR-024](#skr-024) | P0 | M | Reserve and reconcile job spending budgets | SKR-017, SKR-022 |
| [SKR-025](#skr-025) | P0 | M | Implement cancellation, deadline and resume semantics | SKR-020, SKR-022, SKR-023, SKR-024 |
| [SKR-026](#skr-026) | P0 | M | Stream persisted progress with reconnect cursors | SKR-013, SKR-017, SKR-020 |
| [SKR-027](#skr-027) | P0 | M | Adapt public URL validation and network egress controls | SKR-003, SKR-006, SKR-007 |
| [SKR-028](#skr-028) | P0 | M | Adapt subprocess helpers into isolated backend runner | SKR-003, SKR-005, SKR-027 |
| [SKR-029](#skr-029) | P0 | M | Store source credentials with tenant-scoped access | SKR-014, SKR-018, SKR-028 |
| [SKR-030](#skr-030) | P0 | M | Implement source connect, expire, reconnect and revoke | SKR-025, SKR-029 |
| [SKR-031](#skr-031) | P0 | M | Adapt channel registry to typed product capabilities | SKR-003, SKR-019 |
| [SKR-032](#skr-032) | P0 | M | Adapt doctor/probe results and expose connector status | SKR-028, SKR-030, SKR-031 |
| [SKR-033](#skr-033) | P0 | M | Implement chosen search-provider adapter | SKR-011, SKR-019, SKR-024, SKR-027 |
| [SKR-034](#skr-034) | P0 | M | Generate bounded search/dork query variants | SKR-019, SKR-033, SKR-096 |
| [SKR-035](#skr-035) | P0 | M | Normalise and deduplicate discovered candidates | SKR-016, SKR-027, SKR-033 |
| [SKR-036](#skr-036) | P0 | M | Adapt copied Scrapling HTTP fetching into product stage | SKR-002, SKR-023, SKR-024, SKR-027, SKR-035 |
| [SKR-037](#skr-037) | P0 | M | Classify challenges, empty pages and unavailable access | SKR-036 |
| [SKR-038](#skr-038) | P0 | M | Adapt copied dynamic browser engine and bounded pool | SKR-002, SKR-023, SKR-025, SKR-027, SKR-037 |
| [SKR-039](#skr-039) | P0 | M | Adapt copied stealth/challenge engine with bounded retries | SKR-038 |
| [SKR-040](#skr-040) | P0 | M | Adapt copied proxy rotation and session continuity | SKR-023, SKR-024, SKR-029, SKR-039 |
| [SKR-041](#skr-041) | P0 | M | Adapt copied cache logic to access-scoped freshness | SKR-018, SKR-030, SKR-036 |
| [SKR-042](#skr-042) | P0 | M | Adapt copied adaptive storage to tenant/template scope | SKR-002, SKR-014, SKR-016 |
| [SKR-043](#skr-043) | P0 | M | Integrate copied adaptive selector matching with validation | SKR-036, SKR-042 |
| [SKR-044](#skr-044) | P0 | M | Adapt copied HTML cleanup and chunking without evidence loss | SKR-004, SKR-036 |
| [SKR-045](#skr-045) | P0 | M | Adapt copied model creation and usage callbacks | SKR-012, SKR-024, SKR-044 |
| [SKR-046](#skr-046) | P0 | M | Adapt SmartScraper graph to already-collected content | SKR-004, SKR-044, SKR-045 |
| [SKR-047](#skr-047) | P0 | M | Validate extraction fields against schema and evidence | SKR-016, SKR-019, SKR-043, SKR-046 |
| [SKR-048](#skr-048) | P0 | M | Adapt bounded LLM selector repair and template promotion | SKR-025, SKR-043, SKR-045, SKR-047 |
| [SKR-049](#skr-049) | P0 | M | Resolve entity identity with reversible links | SKR-016, SKR-035, SKR-047 |
| [SKR-050](#skr-050) | P0 | M | Evaluate essential criteria and preference ranking | SKR-019, SKR-047, SKR-049 |
| [SKR-051](#skr-051) | P0 | M | Validate contacts and per-claim freshness | SKR-041, SKR-047, SKR-049 |
| [SKR-096](#skr-096) | P0 | M | Implement prompt-to-plan interpretation and clarification service | SKR-015, SKR-019, SKR-024, SKR-045 |
| [SKR-052](#skr-052) | P0 | M | Build prompt composer and editable interpretation UI | SKR-006, SKR-013, SKR-015, SKR-019, SKR-026, SKR-096 |
| [SKR-053](#skr-053) | P0 | M | Build results and evidence detail views | SKR-016, SKR-026, SKR-049, SKR-050, SKR-051 |
| [SKR-054](#skr-054) | P0 | M | Adapt copied export helpers for CSV, JSON and JSONL | SKR-004, SKR-018, SKR-047, SKR-050, SKR-051 |
| [SKR-055](#skr-055) | P0 | M | Implement saved-list snapshots and refresh | SKR-015, SKR-049, SKR-053, SKR-054 |
| [SKR-056](#skr-056) | P0 | M | Implement evidence-grounded research follow-ups | SKR-015, SKR-045, SKR-047, SKR-053 |
| [SKR-057](#skr-057) | P0 | M | Implement conversational refinement and plan reevaluation | SKR-034, SKR-050, SKR-052, SKR-055, SKR-056 |
| [SKR-058](#skr-058) | P0 | M | Build partial results, reconnect and usage UX | SKR-024, SKR-025, SKR-030, SKR-032, SKR-052, SKR-053 |
| [SKR-059](#skr-059) | P0 | M | Adapt LinkedIn discovery and candidate routing | SKR-009, SKR-028, SKR-030, SKR-031, SKR-034, SKR-035 |
| [SKR-060](#skr-060) | P0 | M | Adapt LinkedIn profile, company and post reads | SKR-059, SKR-037, SKR-039, SKR-040, SKR-047, SKR-051 |
| [SKR-061](#skr-061) | P0 | M | Adapt Reddit discussion discovery | SKR-010, SKR-028, SKR-030, SKR-031, SKR-034, SKR-035 |
| [SKR-062](#skr-062) | P0 | M | Adapt Reddit post/comment reading and signal extraction | SKR-061, SKR-037, SKR-047, SKR-050 |
| [SKR-063](#skr-063) | P0 | M | Adapt GitHub public research connector | SKR-028, SKR-030, SKR-031, SKR-035, SKR-047 |
| [SKR-064](#skr-064) | P0 | M | Adapt RSS/Atom feed connector | SKR-031, SKR-035, SKR-036, SKR-047 |
| [SKR-065](#skr-065) | P0 | M | Adapt public YouTube metadata and available transcripts | SKR-028, SKR-030, SKR-031, SKR-035, SKR-047 |
| [SKR-066](#skr-066) | P0 | M | Create company/directory extraction presets using copied engine | SKR-036, SKR-043, SKR-044, SKR-047, SKR-051 |
| [SKR-067](#skr-067) | P0 | M | Verify first complete prompt-to-export slice | SKR-021, SKR-022, SKR-023, SKR-024, SKR-025, SKR-026, SKR-034, SKR-036, SKR-037, SKR-044, SKR-047, SKR-049, SKR-050, SKR-051, SKR-052, SKR-053, SKR-054, SKR-058, SKR-066 |
| [SKR-068](#skr-068) | P0 | M | Verify combined LinkedIn/Reddit research journey | SKR-056, SKR-057, SKR-059, SKR-060, SKR-061, SKR-062, SKR-067 |
| [SKR-069](#skr-069) | P0 | M | Enforce workspace entitlements and abuse limits | SKR-014, SKR-024, SKR-025, SKR-032 |
| [SKR-070](#skr-070) | P0 | M | Instrument stages, source health and costs | SKR-017, SKR-024, SKR-032 |
| [SKR-071](#skr-071) | P0 | M | Enforce evidence and export retention | SKR-018, SKR-041, SKR-054 |
| [SKR-072](#skr-072) | P0 | M | Propagate deletion and suppress rediscovery | SKR-030, SKR-049, SKR-055, SKR-071 |
| [SKR-073](#skr-073) | P0 | M | Implement encrypted backups and restore rehearsal | SKR-017, SKR-018, SKR-072 |
| [SKR-074](#skr-074) | P0 | M | Package and deploy bounded hosted pilot | SKR-008, SKR-027, SKR-028, SKR-029, SKR-069, SKR-070, SKR-071, SKR-073 |
| [SKR-075](#skr-075) | P0 | M | Benchmark parser, full-job latency and resource use | SKR-038, SKR-039, SKR-040, SKR-067, SKR-070, SKR-074 |
| [SKR-076](#skr-076) | P0 | M | Evaluate field, qualification and identity quality | SKR-048, SKR-049, SKR-050, SKR-051, SKR-060, SKR-062, SKR-063, SKR-064, SKR-065, SKR-066, SKR-068 |
| [SKR-077](#skr-077) | P0 | M | Verify tenant boundaries and prompt-injection resistance | SKR-027, SKR-028, SKR-029, SKR-030, SKR-047, SKR-056, SKR-058, SKR-072, SKR-074 |
| [SKR-078](#skr-078) | P0 | M | Verify recovery, rate limits and budget races | SKR-022, SKR-023, SKR-024, SKR-025, SKR-039, SKR-068, SKR-074 |
| [SKR-079](#skr-079) | P0 | M | Prepare runbook and execute small customer pilot | SKR-009, SKR-010, SKR-011, SKR-012, SKR-068, SKR-075, SKR-076, SKR-077, SKR-078 |
| [SKR-080](#skr-080) | P1 | M | Schedule idempotent saved-research refreshes | SKR-055, SKR-071, SKR-078 |
| [SKR-081](#skr-081) | P1 | M | Report meaningful changes and optional notifications | SKR-056, SKR-072, SKR-080 |
| [SKR-082](#skr-082) | P1 | M | Connect owner-authorised YouTube Analytics OAuth | SKR-030, SKR-065 |
| [SKR-083](#skr-083) | P1 | M | Retrieve and summarise owner analytics reports | SKR-056, SKR-082 |
| [SKR-084](#skr-084) | P1 | M | Adapt X discussion/professional connector | SKR-028, SKR-030, SKR-031, SKR-047, SKR-079 |
| [SKR-085](#skr-085) | P1 | M | Adapt Instagram business/creator connector | SKR-028, SKR-030, SKR-031, SKR-047, SKR-079 |
| [SKR-086](#skr-086) | P1 | M | Adapt Facebook company/content connector | SKR-028, SKR-030, SKR-031, SKR-047, SKR-079 |
| [SKR-087](#skr-087) | P1 | M | Add job/pricing/industry research presets | SKR-048, SKR-056, SKR-066, SKR-079 |
| [SKR-088](#skr-088) | P1 | M | Export qualified records into selected CRM | SKR-054, SKR-072, SKR-079 |
| [SKR-089](#skr-089) | P1 | M | Deliver signed idempotent webhooks | SKR-027, SKR-054, SKR-072, SKR-079 |
| [SKR-090](#skr-090) | P1 | M | Automate billing and entitlements | SKR-024, SKR-069, SKR-079 |
| [SKR-091](#skr-091) | P1 | M | Add selected language and locale support | SKR-052, SKR-054, SKR-056, SKR-076 |
| [SKR-092](#skr-092) | P2 | M | Adapt first regional-platform connector | SKR-028, SKR-030, SKR-031, SKR-047, SKR-079 |
| [SKR-093](#skr-093) | P2 | M | Expose read-only MCP research interface | SKR-019, SKR-056, SKR-069, SKR-077, SKR-079 |
| [SKR-094](#skr-094) | P2 | M | Evaluate optional semantic retrieval before adding infrastructure | SKR-056, SKR-070, SKR-076, SKR-079 |
| [SKR-095](#skr-095) | P2 | M | Evaluate local companion only if selected routes require it | SKR-009, SKR-010, SKR-028, SKR-030, SKR-079 |

## PRD traceability

| Requirement | Tickets |
| --- | --- |
| FR-01 | [SKR-007](#skr-007), [SKR-012](#skr-012), [SKR-015](#skr-015), [SKR-019](#skr-019), [SKR-034](#skr-034), [SKR-045](#skr-045), [SKR-096](#skr-096), [SKR-052](#skr-052), [SKR-057](#skr-057), [SKR-067](#skr-067), [SKR-068](#skr-068), [SKR-076](#skr-076), [SKR-079](#skr-079), [SKR-091](#skr-091) |
| FR-02 | [SKR-009](#skr-009), [SKR-010](#skr-010), [SKR-011](#skr-011), [SKR-033](#skr-033), [SKR-034](#skr-034), [SKR-035](#skr-035), [SKR-059](#skr-059), [SKR-061](#skr-061), [SKR-067](#skr-067), [SKR-068](#skr-068) |
| FR-03 | [SKR-001](#skr-001), [SKR-003](#skr-003), [SKR-005](#skr-005), [SKR-009](#skr-009), [SKR-010](#skr-010), [SKR-019](#skr-019), [SKR-027](#skr-027), [SKR-028](#skr-028), [SKR-031](#skr-031), [SKR-032](#skr-032), [SKR-059](#skr-059), [SKR-060](#skr-060), [SKR-061](#skr-061), [SKR-062](#skr-062), [SKR-063](#skr-063), [SKR-064](#skr-064), [SKR-065](#skr-065), [SKR-066](#skr-066), [SKR-068](#skr-068), [SKR-077](#skr-077), [SKR-079](#skr-079), [SKR-084](#skr-084), [SKR-085](#skr-085), [SKR-086](#skr-086), [SKR-092](#skr-092), [SKR-095](#skr-095) |
| FR-04 | [SKR-002](#skr-002), [SKR-005](#skr-005), [SKR-023](#skr-023), [SKR-036](#skr-036), [SKR-041](#skr-041), [SKR-067](#skr-067), [SKR-070](#skr-070), [SKR-075](#skr-075) |
| FR-05 | [SKR-002](#skr-002), [SKR-023](#skr-023), [SKR-027](#skr-027), [SKR-037](#skr-037), [SKR-038](#skr-038), [SKR-039](#skr-039), [SKR-040](#skr-040), [SKR-075](#skr-075), [SKR-078](#skr-078) |
| FR-06 | [SKR-002](#skr-002), [SKR-007](#skr-007), [SKR-042](#skr-042), [SKR-043](#skr-043), [SKR-048](#skr-048), [SKR-076](#skr-076) |
| FR-07 | [SKR-004](#skr-004), [SKR-005](#skr-005), [SKR-012](#skr-012), [SKR-044](#skr-044), [SKR-045](#skr-045), [SKR-046](#skr-046), [SKR-047](#skr-047), [SKR-066](#skr-066), [SKR-067](#skr-067), [SKR-076](#skr-076), [SKR-087](#skr-087) |
| FR-08 | [SKR-009](#skr-009), [SKR-010](#skr-010), [SKR-025](#skr-025), [SKR-028](#skr-028), [SKR-029](#skr-029), [SKR-030](#skr-030), [SKR-058](#skr-058), [SKR-060](#skr-060), [SKR-068](#skr-068), [SKR-077](#skr-077), [SKR-078](#skr-078), [SKR-082](#skr-082), [SKR-095](#skr-095) |
| FR-09 | [SKR-004](#skr-004), [SKR-012](#skr-012), [SKR-016](#skr-016), [SKR-018](#skr-018), [SKR-044](#skr-044), [SKR-047](#skr-047), [SKR-053](#skr-053), [SKR-056](#skr-056), [SKR-060](#skr-060), [SKR-062](#skr-062), [SKR-063](#skr-063), [SKR-064](#skr-064), [SKR-065](#skr-065), [SKR-067](#skr-067), [SKR-068](#skr-068), [SKR-071](#skr-071), [SKR-072](#skr-072), [SKR-076](#skr-076), [SKR-077](#skr-077), [SKR-079](#skr-079), [SKR-083](#skr-083), [SKR-094](#skr-094) |
| FR-10 | [SKR-007](#skr-007), [SKR-016](#skr-016), [SKR-035](#skr-035), [SKR-049](#skr-049), [SKR-067](#skr-067), [SKR-072](#skr-072), [SKR-076](#skr-076) |
| FR-11 | [SKR-007](#skr-007), [SKR-016](#skr-016), [SKR-050](#skr-050), [SKR-053](#skr-053), [SKR-062](#skr-062), [SKR-067](#skr-067), [SKR-068](#skr-068), [SKR-076](#skr-076), [SKR-079](#skr-079) |
| FR-12 | [SKR-016](#skr-016), [SKR-041](#skr-041), [SKR-051](#skr-051), [SKR-055](#skr-055), [SKR-067](#skr-067), [SKR-071](#skr-071), [SKR-076](#skr-076) |
| FR-13 | [SKR-015](#skr-015), [SKR-018](#skr-018), [SKR-054](#skr-054), [SKR-055](#skr-055), [SKR-057](#skr-057), [SKR-067](#skr-067), [SKR-068](#skr-068), [SKR-071](#skr-071), [SKR-072](#skr-072), [SKR-077](#skr-077), [SKR-088](#skr-088), [SKR-089](#skr-089), [SKR-091](#skr-091) |
| FR-14 | [SKR-008](#skr-008), [SKR-017](#skr-017), [SKR-019](#skr-019), [SKR-020](#skr-020), [SKR-021](#skr-021), [SKR-022](#skr-022), [SKR-023](#skr-023), [SKR-024](#skr-024), [SKR-025](#skr-025), [SKR-026](#skr-026), [SKR-058](#skr-058), [SKR-067](#skr-067), [SKR-070](#skr-070), [SKR-073](#skr-073), [SKR-074](#skr-074), [SKR-075](#skr-075), [SKR-078](#skr-078) |
| FR-15 | [SKR-006](#skr-006), [SKR-008](#skr-008), [SKR-013](#skr-013), [SKR-014](#skr-014), [SKR-017](#skr-017), [SKR-024](#skr-024), [SKR-029](#skr-029), [SKR-032](#skr-032), [SKR-058](#skr-058), [SKR-069](#skr-069), [SKR-070](#skr-070), [SKR-072](#skr-072), [SKR-073](#skr-073), [SKR-074](#skr-074), [SKR-077](#skr-077), [SKR-078](#skr-078), [SKR-079](#skr-079), [SKR-090](#skr-090) |
| FR-16 | [SKR-080](#skr-080), [SKR-081](#skr-081), [SKR-082](#skr-082), [SKR-083](#skr-083), [SKR-084](#skr-084), [SKR-085](#skr-085), [SKR-086](#skr-086), [SKR-087](#skr-087), [SKR-088](#skr-088), [SKR-089](#skr-089), [SKR-090](#skr-090), [SKR-091](#skr-091), [SKR-092](#skr-092), [SKR-093](#skr-093), [SKR-094](#skr-094), [SKR-095](#skr-095) |

## Integration checkpoints

| Gate | What establishes correctness |
| --- | --- |
| SKR-067 | One prompt discovers candidates and produces expected qualified, evidenced exports through real product stages. |
| SKR-068 | LinkedIn and Reddit data keep correct provenance through research/refinement; live readiness is independent of mocked replay. |
| SKR-075/076 | Measured latency/resources and labelled field/identity/qualification accuracy satisfy or explicitly revise provisional PRD targets. |
| SKR-077/078 | End-to-end tenancy, injection, network, recovery and spending limits withstand adversarial/failure tests. |
| SKR-079 | Customer pilot completes repeat workflows with measured value/cost and only validated source operations advertised. |

## Ticket details

### Foundation

<a id="skr-001"></a>
#### SKR-001 — Register supplied snapshots and import provenance

**Phase:** P0 · **Size:** S · **Status:** done

**Dependencies:** None

**PRD:** FR-03

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Turn the reference inventory into the canonical source manifest; define third_party destinations, copy rules, licence notices, modification log and manifest verifier. Preserve reference trees.

**Acceptance:**

- No fabricated upstream commit IDs
- Every source file imported later is attributable to its supplied content hash.

**Verification to implement/run:**

- **static** — Source file modified after import. Expected: verifier detects changed hash and requires a recorded patch.
- **static** — Missing licence or unregistered copied file. Expected: distribution check fails.

<a id="skr-002"></a>
#### SKR-002 — Copy and package Scrapling source and baseline tests

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-001](#skr-001)

**PRD:** FR-04, FR-05, FR-06

**Reuse:** S-HTTP, S-PARSE, S-STORE, S-BROWSER, S-STEALTH, S-RATE, S-CACHE — see source reuse map for exact code/tests.

**Scope:** Copy complete Scrapling package, metadata/licence and relevant test closure to third_party/scrapling. Install the local tree; record which optional features load.

**Acceptance:**

- Product imports resolve to copied tree, not reference or a remote wheel
- Baseline regression outcomes are recorded without hiding existing failures.

**Verification to implement/run:**

- **integration** — Import parser and HTTP/browser entry points in clean environment. Expected: paths resolve to third_party.
- **regression** — Copied deterministic parser suite. Expected: results match the recorded source baseline.

<a id="skr-003"></a>
#### SKR-003 — Copy and package Agent-Reach source and baseline tests

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-001](#skr-001)

**PRD:** FR-03

**Reuse:** A-CORE, A-SEC, A-LI, A-REDDIT, A-PUBLIC, A-SOCIAL — see source reuse map for exact code/tests.

**Scope:** Copy Agent-Reach package, metadata/licence and test closure. Inventory external commands without running installer scripts or using host-global credentials.

**Acceptance:**

- Local copied package is the runtime source
- External tools are marked missing/configured separately from usable.

**Verification to implement/run:**

- **integration** — No external CLIs installed. Expected: diagnostics reports unavailable, not ready.
- **regression** — Channel contract and URL/redaction suites. Expected: preserve baseline behaviour.

<a id="skr-004"></a>
#### SKR-004 — Copy and package ScrapeGraph-AI with telemetry isolation

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-001](#skr-001)

**PRD:** FR-07, FR-09

**Reuse:** G-GRAPH, G-EXTRACT, G-CLEAN, G-EXPORT, G-PRIVACY — see source reuse map for exact code/tests.

**Scope:** Copy package, metadata/licence and test closure. Patch telemetry default/home-write behaviour and local-source logging before runtime use. Do not copy upstream code-generation flows into enabled product operations.

**Acceptance:**

- No external telemetry or unrelated home-file writes during import/run
- Raw source content and credentials are absent from logs.

**Verification to implement/run:**

- **integration** — Import and run mocked extraction with network/file spies. Expected: no telemetry or home config write.
- **regression** — Telemetry flag and generation tests. Expected: adapted copies pass with redacted logs.

<a id="skr-005"></a>
#### SKR-005 — Resolve local source dependencies and lock runtime environments

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-002](#skr-002), [SKR-003](#skr-003), [SKR-004](#skr-004)

**PRD:** FR-03, FR-04, FR-07

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Resolve Python 3.12 dependencies including browser/model integrations. Pin local source copies and external tool versions; isolate incompatible environments only if demonstrated necessary.

**Acceptance:**

- Clean installs are reproducible
- Version conflicts are recorded instead of solved through silent source replacement.

**Verification to implement/run:**

- **integration** — Fresh install from checked-in lockfiles. Expected: all selected copied entry points import.
- **integration** — Missing optional model/browser dependency. Expected: capability disabled with explicit diagnostic.

<a id="skr-006"></a>
#### SKR-006 — Bootstrap web, API and local services

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-005](#skr-005)

**PRD:** FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Create Next.js/TypeScript and FastAPI scaffolds with PostgreSQL/RabbitMQ and local object volume. Add environment schema, readiness/liveness and credential-free examples.

**Acceptance:**

- One documented local startup path
- API readiness reflects required service health without exposing configuration secrets.

**Verification to implement/run:**

- **integration** — Database unavailable at startup. Expected: readiness false and process remains diagnosable.
- **smoke** — Local stack started with placeholders. Expected: UI and API health render without paid provider calls.

<a id="skr-007"></a>
#### SKR-007 — Create labelled fixtures and no-network test harness

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-001](#skr-001)

**PRD:** FR-01, FR-06, FR-10, FR-11

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Define synthetic company/person/discussion pages, JSON-LD, JS pages, changed DOM, same-name entities and failure responses. Add fake search/model/server interfaces and frozen clock.

**Acceptance:**

- Fixtures have expected evidence and criterion outcomes
- Ordinary CI makes no live source/model calls.

**Verification to implement/run:**

- **static** — Fixture missing expected labels. Expected: corpus validation fails.
- **integration** — Accidental outbound call in offline test. Expected: test fails rather than accessing internet.

<a id="skr-008"></a>
#### SKR-008 — Set up ticket-level CI and artifact reporting

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-006](#skr-006), [SKR-007](#skr-007)

**PRD:** FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add selective pytest/type/lint/frontend/build checks, copied-source regression groups and integration service setup. Archive genuine failures/skips and generated contract drift.

**Acceptance:**

- Applicable checks run on each ticket change
- Live probes are opt-in, separate from offline CI.

**Verification to implement/run:**

- **integration** — Deliberately broken schema or frontend build. Expected: CI fails.
- **static** — Live test skipped for absent credentials. Expected: report says skipped, never passed.

### Source feasibility

<a id="skr-009"></a>
#### SKR-009 — Validate LinkedIn backend route and acquire missing implementation

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-003](#skr-003), [SKR-007](#skr-007)

**PRD:** FR-02, FR-03, FR-08

**Reuse:** A-LI — see source reuse map for exact code/tests.

**Scope:** Inspect selected LinkedIn backend beyond Agent-Reach diagnostics. Acquire/pin actual backend source when available, record licence/operations/access limits and isolate an opt-in feasibility harness. Do not claim channel check implements search/read.

**Acceptance:**

- One operation-level feasibility report with source provenance and gaps
- Unavailable access remains a release dependency, not successful coverage.

**Verification to implement/run:**

- **contract** — Only mcporter config exists. Expected: capability remains unvalidated.
- **live** — Controlled discovery/read probe on selected route. Expected: report actual fields, failures, time and access conditions.

<a id="skr-010"></a>
#### SKR-010 — Validate Reddit route and acquire missing implementation

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-003](#skr-003), [SKR-007](#skr-007)

**PRD:** FR-02, FR-03, FR-08

**Reuse:** A-REDDIT — see source reuse map for exact code/tests.

**Scope:** Inspect/pin actual selected OpenCLI/rdt/API backend and source/licence where available. Record server-versus-desktop requirements, search/read availability, commercial access and session expiry.

**Acceptance:**

- Operation-level feasibility report distinguishes configured and usable
- No assumed free anonymous .json production route.

**Verification to implement/run:**

- **contract** — Bridge available but no tested Reddit session. Expected: source not marked ready.
- **live** — Controlled thread/search probe. Expected: actual pagination, fields and access failures recorded.

<a id="skr-011"></a>
#### SKR-011 — Validate search coverage, operators and provider terms

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-007](#skr-007)

**PRD:** FR-02

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Trial candidate provider with fixed LinkedIn/Reddit/company queries; record operator semantics, pagination, duplicate rate, pricing and permitted storage/use. Choose provider configuration.

**Acceptance:**

- Search-provider decision cites measured responses
- Google-style operator generation is distinct from a Google backend.

**Verification to implement/run:**

- **contract** — Provider ignores domain operator. Expected: adapter cannot advertise domain-constrained search.
- **live** — Fixed query corpus. Expected: coverage/yield and actual costs recorded without completeness claim.

<a id="skr-012"></a>
#### SKR-012 — Validate cloud/local models against copied extraction code

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-004](#skr-004), [SKR-005](#skr-005), [SKR-007](#skr-007)

**PRD:** FR-01, FR-07, FR-09

**Reuse:** G-GRAPH, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Benchmark candidate cloud model and optional Ollama using labelled extraction/planning examples. Verify schema support, bounded chunk use, evidence fidelity, token usage and data handling.

**Acceptance:**

- Explicit model/provider selected for hosted pilot
- Local results have independent timing and quality report.

**Verification to implement/run:**

- **contract** — Valid JSON contains invented contact. Expected: model evaluation counts factual failure.
- **live** — Same labelled inputs on selected models. Expected: record accuracy, latency, calls and cost.

### Identity and storage

<a id="skr-013"></a>
#### SKR-013 — Verify Firebase identity on API requests

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-006](#skr-006), [SKR-007](#skr-007)

**PRD:** FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Implement app sign-in and server token verification; map external identity to an application user. Keep target-source authorisation separate.

**Acceptance:**

- Invalid/expired/wrong-audience tokens cannot read app data
- No token appears in URL/log/error.

**Verification to implement/run:**

- **integration** — Forged Firebase token. Expected: request denied.
- **integration** — Expired token during stream reconnect. Expected: user reauthenticates without leaked token.

<a id="skr-014"></a>
#### SKR-014 — Create workspaces, memberships and row-level isolation

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-013](#skr-013)

**PRD:** FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add workspace/membership migrations and owner/member permissions. Use non-owner DB role with transaction-scoped tenancy and explicit privileged maintenance paths.

**Acceptance:**

- Tenant boundary survives connection-pool reuse
- Supplied workspace ID is not authorisation.

**Verification to implement/run:**

- **integration** — User A requests workspace B row. Expected: denied at application and database boundary.
- **integration** — Pooled connection reused for another workspace. Expected: no prior tenant context leaks.

<a id="skr-015"></a>
#### SKR-015 — Persist conversations and immutable plan revisions

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-014](#skr-014)

**PRD:** FR-01, FR-13

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add conversation/message/plan schemas and repositories; store request interpretation and revision links. Preserve prior plan/result meaning after refinement.

**Acceptance:**

- Every run references one immutable plan revision
- Messages/plans are tenant-owned.

**Verification to implement/run:**

- **integration** — Edit criteria after a completed run. Expected: previous plan stays unchanged.
- **integration** — Cross-workspace conversation lookup. Expected: unavailable.

<a id="skr-016"></a>
#### SKR-016 — Persist entities, evidence, claims and qualifications

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-014](#skr-014)

**PRD:** FR-09, FR-10, FR-11, FR-12

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add minimal typed result/evidence/claim/link/qualification/suppression migrations and repositories. Enforce evidence references and separate inferred/observed statuses.

**Acceptance:**

- Claim cannot reference nonexistent/cross-tenant evidence
- Results preserve null/conflicting values.

**Verification to implement/run:**

- **integration** — Claim cites another workspace evidence. Expected: transaction rejected.
- **integration** — Two contradictory role claims. Expected: both stored with conflict status.

<a id="skr-017"></a>
#### SKR-017 — Persist jobs, attempts, events and usage records

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-014](#skr-014), [SKR-015](#skr-015)

**PRD:** FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add canonical job/task-attempt/event/outbox/usage/reservation schemas, uniqueness keys and cursors. Queue payloads contain IDs, not credentials.

**Acceptance:**

- Job state is recoverable independently of Celery result cache
- Duplicate logical attempt IDs cannot create duplicate ledger rows.

**Verification to implement/run:**

- **integration** — Duplicate insertion from two workers. Expected: one logical record persists.
- **integration** — Broker payload inspected. Expected: no page body/session secret present.

<a id="skr-018"></a>
#### SKR-018 — Implement private evidence object storage

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-014](#skr-014), [SKR-016](#skr-016)

**PRD:** FR-09, FR-13

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Provide local and private S3-compatible storage interfaces with scoped keys, size limits, expiration metadata and authorised retrieval.

**Acceptance:**

- Object access requires workspace ownership
- Evidence references survive storage backend swap.

**Verification to implement/run:**

- **integration** — Guess another workspace object key. Expected: access denied.
- **integration** — Oversized or expired blob. Expected: rejected/unavailable with typed status.

### Execution core

<a id="skr-019"></a>
#### SKR-019 — Define typed plans, connector contexts and error schemas

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-015](#skr-015), [SKR-017](#skr-017)

**PRD:** FR-01, FR-03, FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Implement bounded Pydantic contracts from stack document and generate frontend OpenAPI types. Enforce criterion types, maximum schema depth, limits and supported operations.

**Acceptance:**

- Invalid plan cannot dispatch
- Frontend/backend contract drift is detected.

**Verification to implement/run:**

- **unit** — Plan requests negative count or unlimited budget. Expected: validation rejects.
- **contract** — Generated client schema differs from API. Expected: check fails.

<a id="skr-020"></a>
#### SKR-020 — Implement canonical job state machine

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-017](#skr-017), [SKR-019](#skr-019)

**PRD:** FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add legal state transitions, stage field and terminal reason semantics. Distinguish exhausted-source completion from interrupted partial outcome.

**Acceptance:**

- Terminal jobs cannot silently restart
- Partial work is retained on interruption.

**Verification to implement/run:**

- **unit** — Attempt completed-to-running transition. Expected: rejected without explicit new run.
- **integration** — Limit reached with saved results. Expected: partial state and reason preserved.

<a id="skr-021"></a>
#### SKR-021 — Dispatch jobs through transactional outbox

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-017](#skr-017), [SKR-020](#skr-020)

**PRD:** FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Create job and outbox in one transaction; deliver task IDs to RabbitMQ and recover unacknowledged publication. Use idempotent API request keys.

**Acceptance:**

- No committed job is lost between DB and broker
- Duplicate run submission returns same logical job.

**Verification to implement/run:**

- **integration** — Crash after DB commit before publication. Expected: recovery eventually publishes.
- **integration** — Same idempotency key submitted twice. Expected: one logical run.

<a id="skr-022"></a>
#### SKR-022 — Execute checkpointed idempotent worker stages

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-021](#skr-021)

**PRD:** FR-14

**Reuse:** S-CACHE — see source reuse map for exact code/tests.

**Scope:** Copy reusable checkpoint operations where suitable; add product DB leases and stage completion writes. Recover expired leases and keep short bounded stage tasks.

**Acceptance:**

- Duplicate deliveries cannot duplicate final records
- Interrupted external calls remain separately billable/uncertain.

**Verification to implement/run:**

- **integration** — Worker killed after result write before ack. Expected: replay produces no duplicate result.
- **integration** — Lease owner disappears. Expected: recovery resumes unfinished stage.

<a id="skr-023"></a>
#### SKR-023 — Enforce shared source and worker capacity limits

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-022](#skr-022)

**PRD:** FR-04, FR-05, FR-14

**Reuse:** S-RATE — see source reuse map for exact code/tests.

**Scope:** Copy throttling/Retry-After helpers and connect them to shared source/workspace/host leases. Apply HTTP/browser caps and expiring capacity reservations across workers.

**Acceptance:**

- All workers share the same effective caps
- Rate-limit backoff persists beyond one process.

**Verification to implement/run:**

- **integration** — Two workers dispatch same source simultaneously. Expected: source concurrency limit holds.
- **regression** — Retry-After seconds/date plus worker crash. Expected: cadence and lease recovery remain bounded.

<a id="skr-024"></a>
#### SKR-024 — Reserve and reconcile job spending budgets

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-017](#skr-017), [SKR-022](#skr-022)

**PRD:** FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Implement transaction-safe conservative call reservations, usage reconciliation, estimated/confirmed costs and token/traffic/currency counters.

**Acceptance:**

- Parallel calls cannot overspend permitted reservations
- Zero-yield jobs still show actual spend.

**Verification to implement/run:**

- **integration** — Two workers reserve last available budget. Expected: only affordable call proceeds.
- **integration** — Provider timeout with possible charge. Expected: ledger retains explicit estimated charge.

<a id="skr-025"></a>
#### SKR-025 — Implement cancellation, deadline and resume semantics

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-020](#skr-020), [SKR-022](#skr-022), [SKR-023](#skr-023), [SKR-024](#skr-024)

**PRD:** FR-08, FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Check persisted cancellation/deadline before each call, close bounded processes, release leases and resume only valid checkpoints/connections/budget.

**Acceptance:**

- Cancellation stops new dispatch within PRD target
- Resume does not erase original usage or duplicate output.

**Verification to implement/run:**

- **integration** — Cancel during browser/model call. Expected: no new call starts and resources are released.
- **integration** — Resume after quota/session pause. Expected: only unfinished permitted stages run.

<a id="skr-026"></a>
#### SKR-026 — Stream persisted progress with reconnect cursors

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-013](#skr-013), [SKR-017](#skr-017), [SKR-020](#skr-020)

**PRD:** FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Expose authorised event stream and snapshot with ordered cursors, heartbeats and replay. Use headers/secure session, not URL tokens.

**Acceptance:**

- Reconnect neither loses nor duplicates user-visible events
- Counts/stages come from actual persisted work.

**Verification to implement/run:**

- **integration** — Disconnect after sequence N then reconnect. Expected: remaining events replay once.
- **security** — Cross-tenant stream ID or token in query. Expected: access rejected/no credential logging.

### Source safety

<a id="skr-027"></a>
#### SKR-027 — Adapt public URL validation and network egress controls

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-003](#skr-003), [SKR-006](#skr-006), [SKR-007](#skr-007)

**PRD:** FR-03, FR-05

**Reuse:** A-SEC — see source reuse map for exact code/tests.

**Scope:** Copy URL/host validation helpers; add DNS, redirect, rebinding and port checks plus browser/tool network enforcement. Apply to discovered URLs and subresources, not just prompt URLs.

**Acceptance:**

- All production fetch paths deny internal destinations
- Test-only fixture server access is explicit and absent from production config.

**Verification to implement/run:**

- **security** — Public hostname redirects/resolves to metadata or private IP. Expected: request blocked.
- **security** — Browser page loads internal image/XHR target. Expected: network layer denies it.

<a id="skr-028"></a>
#### SKR-028 — Adapt subprocess helpers into isolated backend runner

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-003](#skr-003), [SKR-005](#skr-005), [SKR-027](#skr-027)

**PRD:** FR-03, FR-08

**Reuse:** A-SEC — see source reuse map for exact code/tests.

**Scope:** Copy UTF-8/probe helpers and add fixed read-only commands, explicit minimal environment, process-group timeout, output caps and per-task writable directory. No arbitrary shell interpolation.

**Acceptance:**

- Backend cannot inspect unrelated credentials/home files
- Process timeout kills children and releases capacity.

**Verification to implement/run:**

- **security** — Malicious command argument or page instruction. Expected: treated as data and cannot launch shell.
- **integration** — Backend hangs/spawns child/overflows output. Expected: bounded termination with typed failure.

<a id="skr-029"></a>
#### SKR-029 — Store source credentials with tenant-scoped access

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-014](#skr-014), [SKR-018](#skr-018), [SKR-028](#skr-028)

**PRD:** FR-08, FR-15

**Reuse:** A-SEC — see source reuse map for exact code/tests.

**Scope:** Copy safe path/redaction helpers; add secret references, encryption, allowlisted worker loading and explicit per-workspace runtime config. Remove reliance on shared home credential discovery.

**Acceptance:**

- No raw source secrets enter queue/model/events
- One workspace cannot use another source connection.

**Verification to implement/run:**

- **security** — Tenant A backend attempts tenant B secret. Expected: denied.
- **regression** — Error output includes credential URL/cookie. Expected: output redacted.

<a id="skr-030"></a>
#### SKR-030 — Implement source connect, expire, reconnect and revoke

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-025](#skr-025), [SKR-029](#skr-029)

**PRD:** FR-08

**Reuse:** A-CORE — see source reuse map for exact code/tests.

**Scope:** Persist source connection lifecycle and scopes. Recheck after expiry and before resumed tasks; disconnect stops queued reuse and revokes/removes secrets where supported.

**Acceptance:**

- Source auth is separate from Firebase identity
- Expired source pauses only its own tasks.

**Verification to implement/run:**

- **integration** — Reconnect after paused source task. Expected: same checkpoint resumes with new secret ref.
- **integration** — Disconnect while queued. Expected: no backend call uses revoked connection.

### Discovery

<a id="skr-031"></a>
#### SKR-031 — Adapt channel registry to typed product capabilities

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-003](#skr-003), [SKR-019](#skr-019)

**PRD:** FR-03

**Reuse:** A-CORE — see source reuse map for exact code/tests.

**Scope:** Copy Channel/registry ordering; patch global mutable channel singleton assumptions to per-context instances. Add typed discover/read support and engineering/operational statuses.

**Acceptance:**

- Configuration does not imply tested readiness
- Route is selected by source and operation before generic fallback.

**Verification to implement/run:**

- **regression** — Two tenants choose different backend preferences. Expected: no active_backend state leaks.
- **contract** — Diagnostics-only channel asked to read. Expected: explicit unsupported operation.

<a id="skr-032"></a>
#### SKR-032 — Adapt doctor/probe results and expose connector status

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031)

**PRD:** FR-03, FR-15

**Reuse:** A-CORE, A-SEC — see source reuse map for exact code/tests.

**Scope:** Copy doctor/probe aggregation and adapt to redacted product diagnostics with operation-level health, kill switches and concise setup states.

**Acceptance:**

- A broken source does not break all diagnostics
- Operator disable prevents new tasks without deleting results.

**Verification to implement/run:**

- **regression** — One channel throws during health check. Expected: others report independently.
- **integration** — Disabled read capability. Expected: queued dispatcher will not start it.

<a id="skr-033"></a>
#### SKR-033 — Implement chosen search-provider adapter

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-011](#skr-011), [SKR-019](#skr-019), [SKR-024](#skr-024), [SKR-027](#skr-027)

**PRD:** FR-02

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Wrap chosen provider response/cursors in typed candidates; cap pagination and store provider query/snippet/rank/time. Provider wrapper is new product integration absent from reference trees.

**Acceptance:**

- Calls consume actual shared budget
- Search snippets never masquerade as fetched-page facts.

**Verification to implement/run:**

- **contract** — Provider returns duplicates/empty/429/malformed results. Expected: typed bounded outcome.
- **integration** — Budget permits one page only. Expected: second page is not requested.

<a id="skr-034"></a>
#### SKR-034 — Generate bounded search/dork query variants

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-019](#skr-019), [SKR-033](#skr-033), [SKR-096](#skr-096)

**PRD:** FR-01, FR-02

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Translate validated criteria into domain/phrase/exclusion variants supported by provider. Cap expansion and preserve original interpretation; unsupported operator routes stay visible.

**Acceptance:**

- Provider capabilities determine actual query execution
- Exclusions and must-have criteria are not silently dropped.

**Verification to implement/run:**

- **unit** — LinkedIn fintech founder prompt. Expected: bounded domain-targeted query set with exclusions preserved.
- **contract** — Provider lacks quoted-phrase support. Expected: no exact-match claim.

<a id="skr-035"></a>
#### SKR-035 — Normalise and deduplicate discovered candidates

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-016](#skr-016), [SKR-027](#skr-027), [SKR-033](#skr-033)

**PRD:** FR-02, FR-10

**Reuse:** A-SEC, S-PARSE — see source reuse map for exact code/tests.

**Scope:** Copy safe URL/domain helpers and existing URL joining; retain source-native IDs and original URLs, remove known tracking only, and persist query provenance.

**Acceptance:**

- Meaningful query identifiers survive normalisation
- URL deduplication does not prematurely merge people.

**Verification to implement/run:**

- **unit** — Same profile URL with tracking variants. Expected: one candidate with all provenance.
- **unit** — Similar names with different native IDs or meaningful query parameters. Expected: remain distinct.

### Fetching

<a id="skr-036"></a>
#### SKR-036 — Adapt copied Scrapling HTTP fetching into product stage

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-002](#skr-002), [SKR-023](#skr-023), [SKR-024](#skr-024), [SKR-027](#skr-027), [SKR-035](#skr-035)

**PRD:** FR-04

**Reuse:** S-HTTP, S-PARSE — see source reuse map for exact code/tests.

**Scope:** Use copied fetch/session code with product timeout/deadline/decoded-size limits, connection reuse and source metadata. Disable duplicate hidden retries outside shared attempt budget.

**Acceptance:**

- Fetch engine is copied source, not independent rewrite
- Network time and parser time are separate.

**Verification to implement/run:**

- **integration** — Static company fixture fetched. Expected: expected content and evidence source metadata persist.
- **integration** — Slow or compressed oversized response. Expected: bounded failure without memory growth.

<a id="skr-037"></a>
#### SKR-037 — Classify challenges, empty pages and unavailable access

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-036](#skr-036)

**PRD:** FR-05

**Reuse:** A-PUBLIC, S-HTTP — see source reuse map for exact code/tests.

**Scope:** Copy existing anti-bot page detection where applicable; adapt to source-aware response/content classification before extraction. Distinguish 200 challenge, JS shell, denial and real empty result.

**Acceptance:**

- Blocked HTML is never accepted as profile evidence
- Classification determines applicable next method.

**Verification to implement/run:**

- **unit** — HTTP 200 login/challenge shell. Expected: classified blocked, no lead fields accepted.
- **unit** — Genuine empty result versus JS-only page. Expected: different outcomes.

<a id="skr-038"></a>
#### SKR-038 — Adapt copied dynamic browser engine and bounded pool

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-002](#skr-002), [SKR-023](#skr-023), [SKR-025](#skr-025), [SKR-027](#skr-027), [SKR-037](#skr-037)

**PRD:** FR-05

**Reuse:** S-BROWSER — see source reuse map for exact code/tests.

**Scope:** Integrate copied browser/session code with isolated contexts, readiness selectors, host-wide two-page pool, request resource limits and process cleanup.

**Acceptance:**

- JS fixture can produce intended content
- Browser failure cannot stall API or leak another context.

**Verification to implement/run:**

- **integration** — JS-only page escalates from HTTP. Expected: intended text/locator collected.
- **integration** — Crash/navigation timeout. Expected: pool capacity released and other job continues.

<a id="skr-039"></a>
#### SKR-039 — Adapt copied stealth/challenge engine with bounded retries

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-038](#skr-038)

**PRD:** FR-05

**Reuse:** S-STEALTH — see source reuse map for exact code/tests.

**Scope:** Enable supported copied stealth/challenge capabilities and patch internal solver/retry deadlines into shared attempt accounting. Preserve challenge diagnostics and partial results.

**Acceptance:**

- All methods share per-URL/job budgets
- Controlled fixture tests do not imply universal live bypass.

**Verification to implement/run:**

- **regression** — Copied solver fixture with successful transition. Expected: only resulting real page enters extraction.
- **integration** — Persistent challenge/internal solver hang. Expected: terminates within deadline with typed outcome.

<a id="skr-040"></a>
#### SKR-040 — Adapt copied proxy rotation and session continuity

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-023](#skr-023), [SKR-024](#skr-024), [SKR-029](#skr-029), [SKR-039](#skr-039)

**PRD:** FR-05

**Reuse:** S-RATE — see source reuse map for exact code/tests.

**Scope:** Copy proxy rotation logic; support configured provider credentials, sticky contexts, billable traffic counters and direct path when no proxy is required. No proxy purchasing in this ticket.

**Acceptance:**

- Rotation cannot exceed source/job limits
- Same authenticated task does not silently change session route.

**Verification to implement/run:**

- **regression** — Proxy unavailable or rotation exhausted. Expected: bounded failure/accounting.
- **integration** — Sticky multi-page read. Expected: correct continuity and tenant-specific proxy secret.

<a id="skr-041"></a>
#### SKR-041 — Adapt copied cache logic to access-scoped freshness

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-018](#skr-018), [SKR-030](#skr-030), [SKR-036](#skr-036)

**PRD:** FR-04, FR-12

**Reuse:** S-CACHE — see source reuse map for exact code/tests.

**Scope:** Copy applicable cache operations; add tenant/access/schema/version keys, TTL/content hashes and conditional reads. Differentiate collection date from publication date.

**Acceptance:**

- Private cache never serves another workspace
- Fresh retrieval of old post does not imply recent publication.

**Verification to implement/run:**

- **integration** — Same URL across distinct sessions. Expected: no private cache collision.
- **unit** — Expired role claim/old post fetched today. Expected: freshness criteria remain accurate.

### Extraction

<a id="skr-042"></a>
#### SKR-042 — Adapt copied adaptive storage to tenant/template scope

**Phase:** P0 · **Size:** M · **Status:** done

**Dependencies:** [SKR-002](#skr-002), [SKR-014](#skr-014), [SKR-016](#skr-016)

**PRD:** FR-06

**Reuse:** S-STORE, S-PARSE — see source reuse map for exact code/tests.

**Scope:** Copy StorageSystemMixin/storage operations and adapt to PostgreSQL workspace/source/access/template/version keys. Honour parser constructor/cache contract and concurrency.

**Acceptance:**

- Fingerprints are reusable without cross-tenant state
- Old templates remain available for rollback.

**Verification to implement/run:**

- **regression** — Copied parser receives new storage implementation. Expected: save/retrieve relocation works.
- **integration** — Same domain/selector in two workspaces. Expected: fingerprints stay separate.

<a id="skr-043"></a>
#### SKR-043 — Integrate copied adaptive selector matching with validation

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-036](#skr-036), [SKR-042](#skr-042)

**PRD:** FR-06

**Reuse:** S-PARSE — see source reuse map for exact code/tests.

**Scope:** Use existing similarity/relocation algorithms; add semantic anchors and field relationships. Quarantine ambiguous mappings and version successful recovery.

**Acceptance:**

- Moved element is correctly recovered
- Wrong neighbouring field is rejected rather than silently accepted.

**Verification to implement/run:**

- **regression** — Layout/classes changed on fixture. Expected: expected field and evidence recovered.
- **unit** — Similar sibling contains another person role. Expected: ambiguous/wrong recovery flagged.

<a id="skr-044"></a>
#### SKR-044 — Adapt copied HTML cleanup and chunking without evidence loss

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-004](#skr-004), [SKR-036](#skr-036)

**PRD:** FR-07, FR-09

**Reuse:** G-CLEAN, S-PARSE — see source reuse map for exact code/tests.

**Scope:** Copy cleanup/markdown/chunk helpers; preserve JSON-LD and locators first, disable 20-character truncation mode, bound segments and honour actual return shapes.

**Acceptance:**

- Names/roles/long evidence survive cleanup
- Context volume is bounded without pretending removed content was analysed.

**Verification to implement/run:**

- **regression** — Long name/role plus JSON-LD in head. Expected: complete fields survive transformation.
- **unit** — Huge page/no body/malformed JSON. Expected: controlled output and visible coverage limits.

<a id="skr-045"></a>
#### SKR-045 — Adapt copied model creation and usage callbacks

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-012](#skr-012), [SKR-024](#skr-024), [SKR-044](#skr-044)

**PRD:** FR-01, FR-07

**Reuse:** G-GRAPH, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Copy relevant model/provider construction, parsers/callbacks and dependencies; configure selected provider/model with explicit timeout/token/call limits and redacted logging.

**Acceptance:**

- No unapproved provider fallback
- Internal retries/chunk calls consume the product ledger.

**Verification to implement/run:**

- **contract** — Provider returns quota/timeout/schema error. Expected: typed bounded outcome and usage.
- **security** — Page contains API-key request/instruction. Expected: no secret disclosed to model.

<a id="skr-046"></a>
#### SKR-046 — Adapt SmartScraper graph to already-collected content

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-004](#skr-004), [SKR-044](#skr-044), [SKR-045](#skr-045)

**PRD:** FR-07

**Reuse:** G-GRAPH, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Copy graph/nodes/prompts, use local-content input and inject product evidence IDs. Disable autonomous refetch/reattempt/code generation and uncontrolled chunk parallelism.

**Acceptance:**

- Extraction never repeats a page fetch silently
- Copied nodes drive extraction within one job budget.

**Verification to implement/run:**

- **integration** — Saved HTML passed to graph with fetch network denied. Expected: schema result produced using model stub.
- **integration** — Multiple chunks/failed answer. Expected: all calls accounted and stop at cap.

<a id="skr-047"></a>
#### SKR-047 — Validate extraction fields against schema and evidence

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-016](#skr-016), [SKR-019](#skr-019), [SKR-043](#skr-043), [SKR-046](#skr-046)

**PRD:** FR-07, FR-09

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Adapt output parsing from source; apply strict types, actual evidence existence/value checks and observed/inferred statuses. Unknowns remain null with reasons.

**Acceptance:**

- Valid JSON alone cannot establish factual correctness
- No invented contact reaches accepted results.

**Verification to implement/run:**

- **unit** — Model invents well-formed email absent from evidence. Expected: field rejected.
- **integration** — Evidence ID missing/cross-tenant/deleted. Expected: claim cannot be accepted.

<a id="skr-048"></a>
#### SKR-048 — Adapt bounded LLM selector repair and template promotion

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-025](#skr-025), [SKR-043](#skr-043), [SKR-045](#skr-045), [SKR-047](#skr-047)

**PRD:** FR-06

**Reuse:** G-EXTRACT, S-PARSE — see source reuse map for exact code/tests.

**Scope:** Use copied extraction logic to propose selector/mapping repair. Validate against preserved source and regression fixtures before promotion; support rollback and unknown outcomes.

**Acceptance:**

- Repair returns mapping, not executable generated code
- Failed repair retains old template and typed reason.

**Verification to implement/run:**

- **integration** — Changed DOM requires bounded repair. Expected: verified template version promoted.
- **security** — Model proposes script or wrong selector. Expected: rejected without execution.

### Qualification

<a id="skr-049"></a>
#### SKR-049 — Resolve entity identity with reversible links

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-016](#skr-016), [SKR-035](#skr-035), [SKR-047](#skr-047)

**PRD:** FR-10

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Implement product identity rules using native IDs/domains/corroborating facts, auditable link reasons and reversible merges. No existing SaaS identity resolver found in supplied code.

**Acceptance:**

- Ambiguous links remain suggestions
- Reversing a merge restores correct claim association.

**Verification to implement/run:**

- **unit** — Same-name people at different firms. Expected: do not merge.
- **integration** — Wrong merge reversed after review. Expected: claims/lists retain traceable identity history.

<a id="skr-050"></a>
#### SKR-050 — Evaluate essential criteria and preference ranking

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-019](#skr-019), [SKR-047](#skr-047), [SKR-049](#skr-049)

**PRD:** FR-11

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Implement matched/contradicted/unknown outcomes for each criterion, evidence-backed fit explanations and separate near-match group; preference score is not calibrated certainty.

**Acceptance:**

- Unknown essential fact cannot be a confirmed match
- Results rank preferences only after qualification status.

**Verification to implement/run:**

- **unit** — Founder matches location but company size unknown. Expected: near match, not confirmed.
- **unit** — Recent hiring criterion supported by old post only. Expected: fails freshness requirement.

<a id="skr-051"></a>
#### SKR-051 — Validate contacts and per-claim freshness

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-041](#skr-041), [SKR-047](#skr-047), [SKR-049](#skr-049)

**PRD:** FR-12

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add separate email syntax/domain/ownership checks, explicit published professional channels and supersession of dated roles. No guessing/SMTP verification added to P0.

**Acceptance:**

- MX presence is not mailbox verification
- Current role and historical role remain distinguishable.

**Verification to implement/run:**

- **unit** — Valid email and MX but no ownership evidence. Expected: not labelled verified.
- **integration** — Refresh finds changed role. Expected: old claim retained but not shown as current.

### Product experience

<a id="skr-096"></a>
#### SKR-096 — Implement prompt-to-plan interpretation and clarification service

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-015](#skr-015), [SKR-019](#skr-019), [SKR-024](#skr-024), [SKR-045](#skr-045)

**PRD:** FR-01

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Adapt copied structured-generation/parser logic into the production planner. Extract essential/preferred criteria, geography, source preferences, requested fields and exclusions; clarify material ambiguity and enforce server-side limits.

**Acceptance:**

- Planner creates validated immutable revisions rather than arbitrary execution instructions
- Unsupported criteria and ambiguous meanings are explicit; no invented user preferences.

**Verification to implement/run:**

- **integration** — Founder prompt with location, exclusion and hiring preference. Expected: correct typed criteria, allowed sources and caps.
- **integration** — Ambiguous location or unsupported requested field. Expected: relevant clarification or visible unavailable criterion without dropped intent.

<a id="skr-052"></a>
#### SKR-052 — Build prompt composer and editable interpretation UI

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-006](#skr-006), [SKR-013](#skr-013), [SKR-015](#skr-015), [SKR-019](#skr-019), [SKR-026](#skr-026), [SKR-096](#skr-096)

**PRD:** FR-01

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Create conversational entry, optional compact controls, clarification messages and plan display. No mandatory lead-filter form; submit triggers validated bounded workflow.

**Acceptance:**

- Unambiguous prompt runs without another form
- Material ambiguity asks one relevant clarification.

**Verification to implement/run:**

- **e2e** — User submits founder query. Expected: sees interpreted criteria and genuine progress.
- **e2e** — Ambiguous geography prompt. Expected: clarification response updates plan without losing message.

<a id="skr-053"></a>
#### SKR-053 — Build results and evidence detail views

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-016](#skr-016), [SKR-026](#skr-026), [SKR-049](#skr-049), [SKR-050](#skr-050), [SKR-051](#skr-051)

**PRD:** FR-09, FR-11

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Show confirmed/near matches, references versus read profiles, evidence panel, timestamps/conflicts and discussion view. Preserve source limitations and real counts.

**Acceptance:**

- Every factual field opens supporting evidence
- Discussion author handle is not automatically a named lead.

**Verification to implement/run:**

- **e2e** — Partial LinkedIn reference with no page read. Expected: labelled limited evidence.
- **e2e** — Conflicting role and anonymous discussion. Expected: clear statuses, no fabricated identity.

<a id="skr-054"></a>
#### SKR-054 — Adapt copied export helpers for CSV, JSON and JSONL

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-004](#skr-004), [SKR-018](#skr-018), [SKR-047](#skr-047), [SKR-050](#skr-050), [SKR-051](#skr-051)

**PRD:** FR-13

**Reuse:** G-EXPORT — see source reuse map for exact code/tests.

**Scope:** Copy CSV/JSON helpers, patch schema union/ordering, nulls, empty files, formula safety and private destinations; extend same module for JSONL and evidence/schema metadata.

**Acceptance:**

- Exports represent accepted or explicitly selected near-match group
- Authorisation and expiry checked at download.

**Verification to implement/run:**

- **regression** — Mixed fields, Unicode, nulls and formula-looking values. Expected: valid safe round-trip CSV/JSON.
- **integration** — Cross-tenant export ID or expired signed link. Expected: download denied.

<a id="skr-055"></a>
#### SKR-055 — Implement saved-list snapshots and refresh

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-015](#skr-015), [SKR-049](#skr-049), [SKR-053](#skr-053), [SKR-054](#skr-054)

**PRD:** FR-12, FR-13

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Persist list membership/snapshot revision and trigger bounded refresh retaining prior evidence. Avoid silently rewriting historical exports.

**Acceptance:**

- Snapshot and current refresh are distinguishable
- Suppression applies on refresh.

**Verification to implement/run:**

- **integration** — Role changes after saved list refresh. Expected: old snapshot remains inspectable.
- **integration** — Suppressed entity found under another URL. Expected: not reintroduced.

<a id="skr-056"></a>
#### SKR-056 — Implement evidence-grounded research follow-ups

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-015](#skr-015), [SKR-045](#skr-045), [SKR-047](#skr-047), [SKR-053](#skr-053)

**PRD:** FR-09

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Adapt copied answer-generation node/prompts for cited reports over relevant stored evidence. Expand research through registered operations only within new/remaining run limits.

**Acceptance:**

- Citations resolve to actual accessible evidence
- Inference is labelled separately from observed facts.

**Verification to implement/run:**

- **integration** — Ask why result fits. Expected: report cites qualification evidence.
- **security** — Retrieved page requests unrelated tools/secrets. Expected: plan unchanged and no action dispatched.

<a id="skr-057"></a>
#### SKR-057 — Implement conversational refinement and plan reevaluation

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-034](#skr-034), [SKR-050](#skr-050), [SKR-052](#skr-052), [SKR-055](#skr-055), [SKR-056](#skr-056)

**PRD:** FR-01, FR-13

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Use copied model extraction where suitable to interpret follow-ups and create new immutable revisions. Reuse valid evidence but reevaluate changed criteria.

**Acceptance:**

- Old list does not silently acquire new meaning
- Relaxed essential criteria are explicit.

**Verification to implement/run:**

- **e2e** — Exclude agencies after a run. Expected: new revision filters results and preserves previous run.
- **integration** — More results requested beyond spend cap. Expected: no automatic spend increase.

<a id="skr-058"></a>
#### SKR-058 — Build partial results, reconnect and usage UX

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-024](#skr-024), [SKR-025](#skr-025), [SKR-030](#skr-030), [SKR-032](#skr-032), [SKR-052](#skr-052), [SKR-053](#skr-053)

**PRD:** FR-08, FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Render real counts, missing fields, source reconnect state, spend estimates and cancel/resume. Keep internal stack traces in operator diagnostics.

**Acceptance:**

- No fabricated progress or padding
- User can export useful partial results.

**Verification to implement/run:**

- **e2e** — Quota/session expires mid-run. Expected: source-specific recovery state and saved results visible.
- **e2e** — Asked 25, only 9 qualify. Expected: actual count and separate near matches shown.

### Launch platforms

<a id="skr-059"></a>
#### SKR-059 — Adapt LinkedIn discovery and candidate routing

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-009](#skr-009), [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-034](#skr-034), [SKR-035](#skr-035)

**PRD:** FR-02, FR-03

**Reuse:** A-LI, A-CORE — see source reuse map for exact code/tests.

**Scope:** Copy/adapt LinkedIn routing/configuration plus acquired selected backend logic; expose actual supported discovery operations and source provenance. Indexed references and direct platform search stay distinguishable.

**Acceptance:**

- LinkedIn remains a primary discovery route
- Limited search references do not imply full profile access.

**Verification to implement/run:**

- **contract** — Search returns references but no readable profile. Expected: candidates labelled accordingly.
- **live** — Selected LinkedIn discovery operation. Expected: observed coverage and failure report required before readiness.

<a id="skr-060"></a>
#### SKR-060 — Adapt LinkedIn profile, company and post reads

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-059](#skr-059), [SKR-037](#skr-037), [SKR-039](#skr-039), [SKR-040](#skr-040), [SKR-047](#skr-047), [SKR-051](#skr-051)

**PRD:** FR-03, FR-08, FR-09

**Reuse:** A-LI, S-STEALTH, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Adapt available acquired backend read code under pinned provenance. Map fields/evidence/session outcomes per supported operation, with bounded fetching and unavailable-field behaviour.

**Acceptance:**

- Read-ready status requires actual tested backend operation
- Missing/private contacts remain unavailable.

**Verification to implement/run:**

- **contract** — Expired session or challenge returned as profile. Expected: no accepted claims, reconnect/blocked reason.
- **live** — Supported profile/company/post fixtures and real probe. Expected: field/evidence correctness measured.

<a id="skr-061"></a>
#### SKR-061 — Adapt Reddit discussion discovery

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-010](#skr-010), [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-034](#skr-034), [SKR-035](#skr-035)

**PRD:** FR-02, FR-03

**Reuse:** A-REDDIT, A-CORE — see source reuse map for exact code/tests.

**Scope:** Copy Reddit routing/session diagnostic code and selected acquired search backend. Keep subreddit/search/time filters, typed cursors, source constraints and discussion candidate type.

**Acceptance:**

- Actual search operation tested independently of bridge readiness
- No anonymous user identity inferred.

**Verification to implement/run:**

- **contract** — Available bridge but inaccessible search. Expected: discovery capability stays unavailable.
- **live** — Fixed community/topic query. Expected: actual relevance, pagination and limits documented.

<a id="skr-062"></a>
#### SKR-062 — Adapt Reddit post/comment reading and signal extraction

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-061](#skr-061), [SKR-037](#skr-037), [SKR-047](#skr-047), [SKR-050](#skr-050)

**PRD:** FR-03, FR-09, FR-11

**Reuse:** A-REDDIT, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Adapt selected backend reads and copied AI extraction for stated problems/date/context. Preserve deleted/unavailable content and handle-to-company links only with explicit evidence.

**Acceptance:**

- Demand discussion is not guaranteed buying intent
- Nested comment boundaries and dates preserved.

**Verification to implement/run:**

- **contract** — Deleted comment or insufficient visibility. Expected: unavailable, not invented text.
- **integration** — Anonymous complaint about software. Expected: discussion result with cited problem, no invented email/company.

<a id="skr-063"></a>
#### SKR-063 — Adapt GitHub public research connector

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-035](#skr-035), [SKR-047](#skr-047)

**PRD:** FR-03, FR-09

**Reuse:** A-PUBLIC — see source reuse map for exact code/tests.

**Scope:** Copy GitHub channel credential/config logic; wrap pinned gh/API read operations for public org/repo and explicitly published professional information. No issue/PR write operations.

**Acceptance:**

- Public research and private access distinguished
- Read-only allowlist enforced.

**Verification to implement/run:**

- **contract** — Public repository/company reference. Expected: typed dated evidence.
- **security** — Agent requests gh issue/PR creation or inaccessible private repo. Expected: operation denied/unavailable.

<a id="skr-064"></a>
#### SKR-064 — Adapt RSS/Atom feed connector

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-031](#skr-031), [SKR-035](#skr-035), [SKR-036](#skr-036), [SKR-047](#skr-047)

**PRD:** FR-03, FR-09

**Reuse:** A-PUBLIC — see source reuse map for exact code/tests.

**Scope:** Copy RSS channel and adapt existing feedparser/available Scrapling feed parsing into bounded ingestion with attribution, entry IDs, dates and validated linked URLs.

**Acceptance:**

- Duplicate entries are not new leads
- Feed dates are not replaced with fetch date.

**Verification to implement/run:**

- **contract** — Repeated Atom entry and missing publication date. Expected: deduplication and unknown date.
- **security** — Feed link points to internal address. Expected: denied before follow-up fetch.

<a id="skr-065"></a>
#### SKR-065 — Adapt public YouTube metadata and available transcripts

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-035](#skr-035), [SKR-047](#skr-047)

**PRD:** FR-03, FR-09

**Reuse:** A-PUBLIC — see source reuse map for exact code/tests.

**Scope:** Copy YouTube channel/tool runtime checks; adapt pinned public data/transcript backend output. Preserve timestamped evidence and missing-caption semantics; no private analytics here.

**Acceptance:**

- Public counters labelled public metadata
- Absent transcript does not become a generated transcript.

**Verification to implement/run:**

- **contract** — Video metadata present but captions missing. Expected: metadata retained, transcript unavailable.
- **integration** — Transcript segment supports creator claim. Expected: correct timestamp/source citation.

<a id="skr-066"></a>
#### SKR-066 — Create company/directory extraction presets using copied engine

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-036](#skr-036), [SKR-043](#skr-043), [SKR-044](#skr-044), [SKR-047](#skr-047), [SKR-051](#skr-051)

**PRD:** FR-03, FR-07

**Reuse:** S-PARSE, G-CLEAN — see source reuse map for exact code/tests.

**Scope:** Add a small set of fixture-backed selectors/schemas for company facts, team/careers/service/contact pages using copied parser and cleanup code. No new scraper engine.

**Acceptance:**

- Presets use shared budgets/evidence pipeline
- Directory claims are corroborated or retain source-specific status.

**Verification to implement/run:**

- **integration** — Static company plus team/careers pages. Expected: intended claims and hiring date extracted.
- **regression** — Changed directory markup. Expected: adaptive mapping correct or explicitly flagged.

### Integration gates

<a id="skr-067"></a>
#### SKR-067 — Verify first complete prompt-to-export slice

**Phase:** P0 · **Size:** M · **Status:** implemented_pending_verification

**Dependencies:** [SKR-021](#skr-021), [SKR-022](#skr-022), [SKR-023](#skr-023), [SKR-024](#skr-024), [SKR-025](#skr-025), [SKR-026](#skr-026), [SKR-034](#skr-034), [SKR-036](#skr-036), [SKR-037](#skr-037), [SKR-044](#skr-044), [SKR-047](#skr-047), [SKR-049](#skr-049), [SKR-050](#skr-050), [SKR-051](#skr-051), [SKR-052](#skr-052), [SKR-053](#skr-053), [SKR-054](#skr-054), [SKR-058](#skr-058), [SKR-066](#skr-066)

**PRD:** FR-01, FR-02, FR-04, FR-07, FR-09, FR-10, FR-11, FR-12, FR-13, FR-14

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Wire the real persisted pipeline through fake provider transport and actual copied parser/extractor code. Exercise typed prompt, discovery, read, qualification, streamed results and export without file-list prerequisite.

**Acceptance:**

- One user prompt performs genuine backend stages
- Assertions check expected entity/criteria/evidence, not only HTTP 200.

**Verification to implement/run:**

- **e2e** — Prompt asks 3 fintech founders on labelled corpus. Expected: exact matching identities, sources and CSV contents.
- **integration** — Candidate unavailable and another mismatched. Expected: actual counts/partial evidence preserved.

<a id="skr-068"></a>
#### SKR-068 — Verify combined LinkedIn/Reddit research journey

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-056](#skr-056), [SKR-057](#skr-057), [SKR-059](#skr-059), [SKR-060](#skr-060), [SKR-061](#skr-061), [SKR-062](#skr-062), [SKR-067](#skr-067)

**PRD:** FR-01, FR-02, FR-03, FR-08, FR-09, FR-11, FR-13

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Run a founder discovery followed by relevant demand-discussion research and conversational refinement. Exercise route availability separately from offline replay.

**Acceptance:**

- Sources are identified accurately throughout workflow
- Source outage cannot make another route appear to be LinkedIn/Reddit.

**Verification to implement/run:**

- **e2e** — Founder list plus Reddit context then exclude agencies. Expected: correct revisions and cited reports.
- **live** — Advertised operations tested under pilot configuration. Expected: readiness report must record genuine success/gaps.

### Operations

<a id="skr-069"></a>
#### SKR-069 — Enforce workspace entitlements and abuse limits

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-014](#skr-014), [SKR-024](#skr-024), [SKR-025](#skr-025), [SKR-032](#skr-032)

**PRD:** FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add workspace run/result/source entitlements, capped trial usage and owner-managed settings for manual pilot invoicing. Provider calls cannot bypass entitlement checks.

**Acceptance:**

- No unlimited free or paid execution path
- Raising user-requested count does not silently raise permitted spend.

**Verification to implement/run:**

- **integration** — Trial quota exhausted with queued jobs. Expected: dispatch blocked, usage explained.
- **security** — Client submits custom oversized limits. Expected: server effective limits remain enforced.

<a id="skr-070"></a>
#### SKR-070 — Instrument stages, source health and costs

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-017](#skr-017), [SKR-024](#skr-024), [SKR-032](#skr-032)

**PRD:** FR-04, FR-14, FR-15

**Reuse:** A-SEC — see source reuse map for exact code/tests.

**Scope:** Copy redaction helpers and emit structured stage/source metrics and traces with request IDs. Separate parser/network/browser/queue/LLM times and blocked-response denominators.

**Acceptance:**

- Operational diagnostics contain no secrets/full private pages
- Cost and latency denominators are explicit.

**Verification to implement/run:**

- **integration** — Failed expensive run emits metrics. Expected: spend and failures visible despite zero accepted results.
- **security** — Credentials/private content injected into errors. Expected: redacted trace/log outputs.

<a id="skr-071"></a>
#### SKR-071 — Enforce evidence and export retention

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-018](#skr-018), [SKR-041](#skr-041), [SKR-054](#skr-054)

**PRD:** FR-09, FR-12, FR-13

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add cleanup scheduler, per-source stricter TTLs, export expiry and stale-citation filtering. Retention jobs use leases/idempotency.

**Acceptance:**

- Expired evidence cannot be cited as current
- Cleanup does not remove another tenant retained data.

**Verification to implement/run:**

- **integration** — Advance clock beyond configured TTL. Expected: evidence/export inaccessible and storage removed.
- **integration** — Cleanup task delivered twice. Expected: safe no-op after first completion.

<a id="skr-072"></a>
#### SKR-072 — Propagate deletion and suppress rediscovery

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-030](#skr-030), [SKR-049](#skr-049), [SKR-055](#skr-055), [SKR-071](#skr-071)

**PRD:** FR-09, FR-10, FR-13, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Delete active entity/evidence/object data, revoke relevant queued reuse and invalidate caches/lists/exports. Keep minimum permitted suppression markers and backup deletion replay.

**Acceptance:**

- Deleted data cannot reappear from cache/job replay
- Suppression handles alternate known identity URLs.

**Verification to implement/run:**

- **integration** — Delete while fetch result is in flight. Expected: late result cannot repopulate entity.
- **integration** — Rediscover alternate linked URL/restore backup. Expected: suppression/deletion applied before serving.

<a id="skr-073"></a>
#### SKR-073 — Implement encrypted backups and restore rehearsal

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-017](#skr-017), [SKR-018](#skr-018), [SKR-072](#skr-072)

**PRD:** FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Back up DB/object metadata and blobs as required; record expiry/key access and restore instructions. Restore migrations, deletion replay and tenant context before traffic.

**Acceptance:**

- Measured pilot RPO/RTO recorded
- Restore is demonstrated, not merely backup creation.

**Verification to implement/run:**

- **recovery** — Restore latest backup into clean isolated stack. Expected: verified job/evidence consistency.
- **recovery** — Backup predates deletion. Expected: deletion replay prevents data being served.

<a id="skr-074"></a>
#### SKR-074 — Package and deploy bounded hosted pilot

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-008](#skr-008), [SKR-027](#skr-027), [SKR-028](#skr-028), [SKR-029](#skr-029), [SKR-069](#skr-069), [SKR-070](#skr-070), [SKR-071](#skr-071), [SKR-073](#skr-073)

**PRD:** FR-14, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Build local-source runtime images, private networking, non-root browser/tool workers, TLS, secret delivery, health/restart and persistent volumes. Deployment is a separate authorised operational action.

**Acceptance:**

- Reference folders are not mutable runtime dependencies
- Service restarts preserve canonical state and browser capacity limits.

**Verification to implement/run:**

- **smoke** — Fresh environment launched from images. Expected: prompt API/UI and storage health work.
- **recovery** — API/broker/worker restarted separately. Expected: no lost committed job or credential leak.

### Release gates

<a id="skr-075"></a>
#### SKR-075 — Benchmark parser, full-job latency and resource use

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-038](#skr-038), [SKR-039](#skr-039), [SKR-040](#skr-040), [SKR-067](#skr-067), [SKR-070](#skr-070), [SKR-074](#skr-074)

**PRD:** FR-04, FR-05, FR-14

**Reuse:** S-HTTP, S-PARSE, S-BROWSER, S-STEALTH — see source reuse map for exact code/tests.

**Scope:** Benchmark PRD profile and separate source-access failures, model/network time, memory and cache state. Tune bounded concurrency without rewriting copied engines.

**Acceptance:**

- Measured results compared with provisional PRD targets
- No parser multiplier represented as product speed.

**Verification to implement/run:**

- **performance** — Fixed corpus on declared hardware. Expected: p50/p95 stage/job times and peak memory recorded.
- **performance** — Two workspaces with browser-heavy jobs. Expected: API responsive and host/source caps hold.

<a id="skr-076"></a>
#### SKR-076 — Evaluate field, qualification and identity quality

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-048](#skr-048), [SKR-049](#skr-049), [SKR-050](#skr-050), [SKR-051](#skr-051), [SKR-060](#skr-060), [SKR-062](#skr-062), [SKR-063](#skr-063), [SKR-064](#skr-064), [SKR-065](#skr-065), [SKR-066](#skr-066), [SKR-068](#skr-068)

**PRD:** FR-01, FR-06, FR-07, FR-09, FR-10, FR-11, FR-12

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Run labelled prompt/record/changed-DOM corpus with PRD denominators and per-source breakdown. Review false positives, unknowns, silent repairs and invented contacts.

**Acceptance:**

- Quality gates measured on sufficient labelled samples
- Fixture success does not claim live platform availability.

**Verification to implement/run:**

- **evaluation** — Labelled benchmark with ambiguous people/unknown size. Expected: field/merge/qualification accuracy reported.
- **evaluation** — Adversarial wrong element and fabricated email. Expected: rejected or gate fails.

<a id="skr-077"></a>
#### SKR-077 — Verify tenant boundaries and prompt-injection resistance

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-027](#skr-027), [SKR-028](#skr-028), [SKR-029](#skr-029), [SKR-030](#skr-030), [SKR-047](#skr-047), [SKR-056](#skr-056), [SKR-058](#skr-058), [SKR-072](#skr-072), [SKR-074](#skr-074)

**PRD:** FR-03, FR-08, FR-09, FR-13, FR-15

**Reuse:** A-SEC — see source reuse map for exact code/tests.

**Scope:** Exercise complete hosted routes, copied tools/graphs and network policies for cross-tenant data, secrets, SSRF, malicious sources and unsafe export contents.

**Acceptance:**

- Security suite covers every external execution path
- No critical boundary failure remains before customer pilot.

**Verification to implement/run:**

- **security** — Page/model output tries secret read or unrelated command. Expected: no tool action/secret disclosure.
- **security** — Cross-tenant list/evidence/session/export/events and browser SSRF. Expected: all denied.

<a id="skr-078"></a>
#### SKR-078 — Verify recovery, rate limits and budget races

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-022](#skr-022), [SKR-023](#skr-023), [SKR-024](#skr-024), [SKR-025](#skr-025), [SKR-039](#skr-039), [SKR-068](#skr-068), [SKR-074](#skr-074)

**PRD:** FR-05, FR-08, FR-14, FR-15

**Reuse:** S-CACHE, S-RATE — see source reuse map for exact code/tests.

**Scope:** Inject duplicate messages, crash between charge/result writes, expired sessions, outage/circuit breaker and concurrent reservation races across the complete pipeline.

**Acceptance:**

- No lost logical result or double logical charge
- Real external charge uncertainty remains visible.

**Verification to implement/run:**

- **recovery** — Kill worker after provider reply before acknowledgment. Expected: deterministic recovery with correct ledger.
- **integration** — Shared 429/deadline/cancellation/budget race. Expected: source/job limits never overridden.

<a id="skr-079"></a>
#### SKR-079 — Prepare runbook and execute small customer pilot

**Phase:** P0 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-009](#skr-009), [SKR-010](#skr-010), [SKR-011](#skr-011), [SKR-012](#skr-012), [SKR-068](#skr-068), [SKR-075](#skr-075), [SKR-076](#skr-076), [SKR-077](#skr-077), [SKR-078](#skr-078)

**PRD:** FR-01, FR-03, FR-09, FR-11, FR-15

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Document source readiness/support, rollback/reconnect/kill switches, pricing assumptions and incident handling; run repeated tasks with at least three prospective workspaces and record value/cost.

**Acceptance:**

- Only validated operations advertised
- Product completion requires repeated user workflow value, not a successful scrape.

**Verification to implement/run:**

- **acceptance** — Operator follows outage/reconnect/restore runbook. Expected: users keep usable results and clear status.
- **pilot** — Repeated real customer tasks. Expected: accuracy, review time, spend, limitations and willingness to pay recorded.

### Expansion

<a id="skr-080"></a>
#### SKR-080 — Schedule idempotent saved-research refreshes

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-055](#skr-055), [SKR-071](#skr-071), [SKR-078](#skr-078)

**PRD:** FR-16

**Reuse:** S-CACHE — see source reuse map for exact code/tests.

**Scope:** Add due-record scheduler with workspace/source/budget limits, leases and opt-in cadence. Reuse copied checkpoint operations where suitable.

**Acceptance:**

- Restart does not duplicate scheduled runs
- Deleted/disconnected lists stop future work.

**Verification to implement/run:**

- **integration** — Scheduler restarts at due time. Expected: one logical refresh.
- **integration** — Source disconnected or budget exhausted. Expected: no automatic call.

<a id="skr-081"></a>
#### SKR-081 — Report meaningful changes and optional notifications

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-056](#skr-056), [SKR-072](#skr-072), [SKR-080](#skr-080)

**PRD:** FR-16

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Compare versioned claims, adapt copied report generation for supported meaningful changes and add opt-in delivery channel configuration.

**Acceptance:**

- No notice for unchanged/non-actionable refresh
- Any message delivery needs explicit configured opt-in.

**Verification to implement/run:**

- **integration** — Same evidence refreshed. Expected: no change notice.
- **integration** — Current role changes with new evidence. Expected: accurate cited change report.

<a id="skr-082"></a>
#### SKR-082 — Connect owner-authorised YouTube Analytics OAuth

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-030](#skr-030), [SKR-065](#skr-065)

**PRD:** FR-08, FR-16

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add a distinct owner analytics connection/scopes/revocation flow. This code is not supplied by public YouTube transcript channels.

**Acceptance:**

- Owner analytics never inferred from public metadata
- Tokens belong only to connected workspace/owner.

**Verification to implement/run:**

- **contract** — Wrong owner or missing report scope. Expected: denied.
- **integration** — Revoked token. Expected: analytics pauses without breaking public video research.

<a id="skr-083"></a>
#### SKR-083 — Retrieve and summarise owner analytics reports

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-056](#skr-056), [SKR-082](#skr-082)

**PRD:** FR-09, FR-16

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Implement bounded report/date/metric adapter and use copied generation code for cited summaries. Respect report availability/quota and record currency/timezone where relevant.

**Acceptance:**

- Reports describe authorised owner only
- Unsupported metric remains unavailable.

**Verification to implement/run:**

- **contract** — Valid owner report with date range. Expected: exact metrics and source provenance.
- **integration** — Quota/unsupported metric. Expected: partial typed result without guessed analytics.

<a id="skr-084"></a>
#### SKR-084 — Adapt X discussion/professional connector

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-047](#skr-047), [SKR-079](#skr-079)

**PRD:** FR-03, FR-16

**Reuse:** A-SOCIAL — see source reuse map for exact code/tests.

**Scope:** Copy X routing/probe code and pin/acquire selected read backend. Enable discovery/read only after independent route readiness.

**Acceptance:**

- No posting/DM operations enabled
- Fields/rights/session requirements documented.

**Verification to implement/run:**

- **contract** — Missing backend/session. Expected: unavailable, not successful discovery.
- **live** — Selected X read/search. Expected: actual operation report and bounded usage.

<a id="skr-085"></a>
#### SKR-085 — Adapt Instagram business/creator connector

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-047](#skr-047), [SKR-079](#skr-079)

**PRD:** FR-03, FR-16

**Reuse:** A-SOCIAL — see source reuse map for exact code/tests.

**Scope:** Copy Instagram/OpenCLI channel logic and acquire applicable backend. Define public/business-account operations separately and preserve evidence/freshness.

**Acceptance:**

- Public/private and owner access boundaries explicit
- Host browser account not silently shared.

**Verification to implement/run:**

- **contract** — Browser bridge lacks source session. Expected: needs connection.
- **live** — Selected creator/business operation. Expected: actual supported fields and failures recorded.

<a id="skr-086"></a>
#### SKR-086 — Adapt Facebook company/content connector

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-047](#skr-047), [SKR-079](#skr-079)

**PRD:** FR-03, FR-16

**Reuse:** A-SOCIAL — see source reuse map for exact code/tests.

**Scope:** Copy Facebook/OpenCLI routing and selected backend code. Enable only named read/search operations with source readiness tests.

**Acceptance:**

- Group/private content access not implied by page access
- Evidence/delete policies enforced.

**Verification to implement/run:**

- **contract** — Public page readable but group unavailable. Expected: distinct capabilities.
- **live** — Named company-page operation. Expected: usable output and restrictions recorded.

<a id="skr-087"></a>
#### SKR-087 — Add job/pricing/industry research presets

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-048](#skr-048), [SKR-056](#skr-056), [SKR-066](#skr-066), [SKR-079](#skr-079)

**PRD:** FR-07, FR-16

**Reuse:** S-PARSE, G-CLEAN, G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Extend copied parser/extraction presets for chosen job/pricing/directory sources; preserve currency, billing period, publication date and availability.

**Acceptance:**

- Different source meanings are not collapsed
- No new general scraper engine.

**Verification to implement/run:**

- **regression** — Monthly/annual/localised price fixtures. Expected: correct values with period/currency.
- **integration** — Expired job listing. Expected: not reported as current hiring.

<a id="skr-088"></a>
#### SKR-088 — Export qualified records into selected CRM

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-054](#skr-054), [SKR-072](#skr-072), [SKR-079](#skr-079)

**PRD:** FR-13, FR-16

**Reuse:** G-EXPORT — see source reuse map for exact code/tests.

**Scope:** Extend copied export mapping with one selected CRM destination, explicit field mapping, tenant scopes and idempotent writes. Destination chosen before implementation.

**Acceptance:**

- Near matches/contact states not upgraded during sync
- Suppression/deletion checks precede export.

**Verification to implement/run:**

- **contract** — Same export retried. Expected: no duplicate CRM record.
- **integration** — Entity suppressed before queued sync. Expected: not sent.

<a id="skr-089"></a>
#### SKR-089 — Deliver signed idempotent webhooks

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-027](#skr-027), [SKR-054](#skr-054), [SKR-072](#skr-072), [SKR-079](#skr-079)

**PRD:** FR-13, FR-16

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Add validated endpoint connections, signing, retries, delivery ledger and opt-in triggers. Outbound webhook policy blocks internal destinations.

**Acceptance:**

- No unauthorised external delivery
- Consumers can identify duplicate deliveries.

**Verification to implement/run:**

- **security** — Endpoint redirects to internal address. Expected: delivery blocked.
- **integration** — Receiver timeout/retry. Expected: same event identity, bounded retries and ledger.

<a id="skr-090"></a>
#### SKR-090 — Automate billing and entitlements

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-024](#skr-024), [SKR-069](#skr-069), [SKR-079](#skr-079)

**PRD:** FR-15, FR-16

**Reuse:** New product glue, infrastructure, evaluation or provider integration; no equivalent feature implementation identified in supplied trees.

**Scope:** Select payment provider, implement validated billing events and subscription/usage entitlement transitions. Do not infer product access from client checkout success.

**Acceptance:**

- Verified server events govern entitlements
- Duplicate/out-of-order billing events safe.

**Verification to implement/run:**

- **integration** — Forged payment webhook. Expected: no entitlement change.
- **integration** — Cancellation or repeated event. Expected: consistent capped access and auditable state.

<a id="skr-091"></a>
#### SKR-091 — Add selected language and locale support

**Phase:** P1 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-052](#skr-052), [SKR-054](#skr-054), [SKR-056](#skr-056), [SKR-076](#skr-076)

**PRD:** FR-01, FR-13, FR-16

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Choose language/localisation requirements from pilot evidence; adapt copied model prompts and product formats, keeping source dates/names accurately represented.

**Acceptance:**

- Original names/evidence remain intact
- Locale does not silently reinterpret dates/numbers.

**Verification to implement/run:**

- **evaluation** — Selected-language prompt and multilingual company evidence. Expected: criteria/extraction quality measured.
- **regression** — Ambiguous date/currency and Unicode CSV. Expected: safe explicit interpretation.

### Later roadmap

<a id="skr-092"></a>
#### SKR-092 — Adapt first regional-platform connector

**Phase:** P2 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-031](#skr-031), [SKR-047](#skr-047), [SKR-079](#skr-079)

**PRD:** FR-03, FR-16

**Reuse:** A-SOCIAL — see source reuse map for exact code/tests.

**Scope:** Select one regional source, copy its available channel/formatting/backend code and add operation-specific source readiness. Repeat this ticket template for each later platform.

**Acceptance:**

- Named source has tested capabilities
- Adding one source does not advertise all regional platforms.

**Verification to implement/run:**

- **regression** — Copied source formatter and malformed payload. Expected: typed normalised output.
- **live** — Named discovery/read route. Expected: independent coverage/access/cost report.

<a id="skr-093"></a>
#### SKR-093 — Expose read-only MCP research interface

**Phase:** P2 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-019](#skr-019), [SKR-056](#skr-056), [SKR-069](#skr-069), [SKR-077](#skr-077), [SKR-079](#skr-079)

**PRD:** FR-16

**Reuse:** A-CORE — see source reuse map for exact code/tests.

**Scope:** Copy/adapt Agent-Reach MCP integration scaffolding; expose only bounded product research/list/read operations with workspace auth and normal job budgets.

**Acceptance:**

- MCP does not bypass tenant/entitlement checks
- Arbitrary commands and source writes absent.

**Verification to implement/run:**

- **contract** — MCP client runs normal research. Expected: same schema and cost limits as UI.
- **security** — Client requests another workspace/arbitrary tool. Expected: denied.

<a id="skr-094"></a>
#### SKR-094 — Evaluate optional semantic retrieval before adding infrastructure

**Phase:** P2 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-056](#skr-056), [SKR-070](#skr-070), [SKR-076](#skr-076), [SKR-079](#skr-079)

**PRD:** FR-09, FR-16

**Reuse:** G-EXTRACT — see source reuse map for exact code/tests.

**Scope:** Benchmark existing database/evidence retrieval against any proposed semantic retrieval on labelled follow-up tasks. Add vector infrastructure only after documented quality/cost benefit.

**Acceptance:**

- No speculative extra database
- Decision includes tenancy, deletion and retrieval quality.

**Verification to implement/run:**

- **evaluation** — Labelled evidence questions. Expected: baseline and alternative relevance/cost measured.
- **security** — Semantic index deletion/tenant isolation fixture. Expected: no suppressed/cross-tenant retrieval.

<a id="skr-095"></a>
#### SKR-095 — Evaluate local companion only if selected routes require it

**Phase:** P2 · **Size:** M · **Status:** planned

**Dependencies:** [SKR-009](#skr-009), [SKR-010](#skr-010), [SKR-028](#skr-028), [SKR-030](#skr-030), [SKR-079](#skr-079)

**PRD:** FR-03, FR-08, FR-16

**Reuse:** A-SOCIAL, A-LI, A-REDDIT — see source reuse map for exact code/tests.

**Scope:** If feasibility proves a desktop bridge is necessary, write architecture decision and a bounded proof using copied backend bridge code. Desktop product is not automatically committed by the web PRD.

**Acceptance:**

- Requirement and installation burden demonstrated
- No unattended credential harvesting or shared home context.

**Verification to implement/run:**

- **acceptance** — Chosen source cannot run on hosted route. Expected: decision records capability and local alternative.
- **security** — Companion pairing/revocation test. Expected: only paired workspace can invoke allowed reads.

## Ticket completion note template

```text
Ticket ID / status:
Implemented scope and user outcome:
Copied source paths / manifest IDs / patches:
Commands and test outcomes (pass/fail/skip):
Source readiness (fixture-only or actual validated operation):
Evidence, quality/cost observations, and limitations:
Follow-up tickets / dependency status:
```
